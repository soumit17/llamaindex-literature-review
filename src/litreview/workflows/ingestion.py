"""Workflow 1: ingestion (spec §6). Lock file -> PDFs -> parsed segments -> indexed chunks -> summaries.

Event flow (each paper travels the chain on its own; up to N papers per step at once):

    IngestRequest ─load_lock─▶ list[PaperToFetch]          fan-out: one branch per paper
      PaperToFetch ─fetch_pdf─▶ PaperFetched               num_workers=2, retried, rate-limited
      PaperFetched ─parse_pdf─▶ PaperParsed                num_workers=4
      PaperParsed ─index_paper─▶ PaperIndexed              num_workers=1 (shared index)
      PaperIndexed ─summarize_paper─▶ PaperSummarized      num_workers=3, retried, LLM
    list[PaperSummarized] ─persist─▶ IngestReport          fan-in: once every branch has finished
    StepFailedEvent(fetch_pdf) ─on_fetch_failure─▶ (branch ends; failure recorded in state)

Every step is idempotent, so a re-run is a no-op: existing PDFs are kept by hash, parsed files and
summaries are reused, and the pipeline docstore skips chunks it has already embedded.
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Annotated

from llama_index.core.base.embeddings.base import BaseEmbedding
from llama_index.core.llms import LLM
from workflows import Context, Workflow, catch_error, step
from workflows.events import StepFailedEvent
from workflows.resource import Resource

from litreview.config import get_settings
from litreview.corpus import (
    ArxivClient,
    CorpusLock,
    CorpusPaths,
    LockedPaper,
    PaperMeta,
    Topic,
    ensure_papers_json,
)
from litreview.events import (
    IngestProgress,
    IngestReport,
    IngestRequest,
    PaperFetched,
    PaperIndexed,
    PaperParsed,
    PaperSummarized,
    PaperToFetch,
)
from litreview.resources import (
    get_arxiv_client,
    get_embed_model,
    get_llm,
    get_papers,
    get_storage,
    get_topic,
)
from litreview.retrieval.engines import ensure_summary_index
from litreview.retrieval.parsing import parse_pdf, read_jsonl, write_jsonl
from litreview.retrieval.pipeline import Storage, documents_from_segments
from litreview.retrieval.summaries import (
    build_messages,
    load_all_summaries,
    load_summary,
    save_summary,
    summarize,
    summary_input,
)
from litreview.retry import FETCH_RETRY, LLM_RETRY
from litreview.state import IngestState


def _paths() -> CorpusPaths:
    return CorpusPaths(get_settings().p2_data_dir)


class IngestionWorkflow(Workflow):
    @step(retry_policy=FETCH_RETRY)  # may make one arXiv metadata request (see below)
    async def load_lock(
        self,
        ctx: Context[IngestState],
        ev: IngestRequest,
        arxiv: Annotated[ArxivClient, Resource(get_arxiv_client)],
    ) -> list[PaperToFetch]:
        # Returning a list is the fan-out: each element becomes its own event, and because the
        # framework opens a "stream" for the list, `persist` can later join exactly these branches.
        paths = _paths()
        lock = CorpusLock.load(paths.lock)
        if lock is None:
            raise FileNotFoundError(f"{paths.lock} not found; run scripts/fetch_corpus.py first")
        papers = lock.papers[: ev.limit] if ev.limit else lock.papers
        # papers.json is git-ignored: on a fresh clone only the lock exists. Rebuild it before any step
        # reads it (get_papers is resolved later, by parse_pdf). One request, cached; a no-op otherwise.
        await ensure_papers_json(arxiv, lock, paths)
        if ev.rebuild:  # before get_storage is first resolved (by index_paper), so it loads empty
            shutil.rmtree(paths.root / "storage", ignore_errors=True)
            shutil.rmtree(paths.root / "parsed", ignore_errors=True)
        async with ctx.store.edit_state() as state:
            state.total = len(papers)
            state.fail_ids = list(ev.fail_ids)
        ctx.write_event_to_stream(IngestProgress(stage="start", done=0, total=len(papers)))
        return [PaperToFetch(arxiv_id=p.arxiv_id, version=p.version, sha256=p.sha256) for p in papers]

    # num_workers=2: two papers in flight, but the shared ArxivClient's limiter still spaces real
    # requests 3 s apart. retry_policy: network errors / 429 / 503 / "not a PDF", exponential backoff.
    @step(num_workers=2, retry_policy=FETCH_RETRY)
    async def fetch_pdf(
        self,
        ctx: Context[IngestState],
        ev: PaperToFetch,
        arxiv: Annotated[ArxivClient, Resource(get_arxiv_client)],
    ) -> PaperFetched:
        state = await ctx.store.get_state()
        retry = ctx.retry_info()
        if retry.last_exception is not None:  # the runtime re-ran this step for the same event
            ctx.write_event_to_stream(
                IngestProgress(
                    stage="fetch",
                    done=len(state.fetched),
                    total=state.total,
                    arxiv_id=ev.arxiv_id,
                    status="retry",
                    message=f"retry {retry.retry_number} after: {retry.last_exception}",
                )
            )
        if ev.arxiv_id in state.fail_ids:
            raise ConnectionError(f"forced failure for {ev.arxiv_id} (--fail demo)")

        dest = _paths().pdf(ev.arxiv_id)
        _, downloaded = await arxiv.download_pdf(LockedPaper(**ev.model_dump()), dest)
        async with ctx.store.edit_state() as state:
            state.fetched.append(ev.arxiv_id)
            done = len(state.fetched)
        ctx.write_event_to_stream(
            IngestProgress(
                stage="fetch",
                done=done,
                total=state.total,
                arxiv_id=ev.arxiv_id,
                status="ok" if downloaded else "cached",
            )
        )
        return PaperFetched(arxiv_id=ev.arxiv_id, pdf_path=str(dest), downloaded=downloaded)

    # Recovery once fetch_pdf's retries are exhausted. Returning None ends this paper's branch;
    # the fan-in in `persist` notices the branch is gone and fires with the remaining papers.
    # (Returning a different event type into that list join is rejected by the validator.)
    @catch_error(for_steps=["fetch_pdf"])
    async def on_fetch_failure(self, ctx: Context[IngestState], ev: StepFailedEvent) -> None:
        arxiv_id = ev.input_event.arxiv_id
        async with ctx.store.edit_state() as state:
            state.failed[arxiv_id] = f"{type(ev.exception).__name__}: {ev.exception}"
            total = state.total
        ctx.write_event_to_stream(
            IngestProgress(
                stage="fetch",
                done=0,
                total=total,
                arxiv_id=arxiv_id,
                status="failed",
                message=f"gave up after {ev.attempts} attempts: {ev.exception}",
            )
        )

    @step(num_workers=4)  # CPU-bound parsing runs in a thread, so 4 papers parse side by side
    async def parse_pdf(
        self,
        ctx: Context[IngestState],
        ev: PaperFetched,
        papers: Annotated[dict[str, PaperMeta], Resource(get_papers)],
    ) -> PaperParsed:
        out = _paths().root / "parsed" / f"{ev.arxiv_id}.jsonl"
        cached = out.exists()
        if cached:
            rows = read_jsonl(out)
            n_pages = max((r["page"] for r in rows), default=0)
        else:
            parsed = await asyncio.to_thread(parse_pdf, Path(ev.pdf_path))
            meta = papers[ev.arxiv_id]
            write_jsonl(out, parsed, {"arxiv_id": ev.arxiv_id, "title": meta.title, "year": meta.year})
            rows = read_jsonl(out)
            n_pages = parsed.n_pages
        async with ctx.store.edit_state() as state:
            state.parsed.append(ev.arxiv_id)
            done, total = len(state.parsed), state.total
        status = "cached" if cached else "ok"
        ctx.write_event_to_stream(
            IngestProgress(stage="parse", done=done, total=total, arxiv_id=ev.arxiv_id, status=status)
        )
        return PaperParsed(
            arxiv_id=ev.arxiv_id,
            n_pages=n_pages,
            n_chars=sum(len(r["text"]) for r in rows),
            n_segments=len(rows),
        )

    # num_workers=1: every paper writes into the same in-memory docstore and index, which are not
    # safe for concurrent writers. Embedding runs in a thread so fetches and LLM calls keep going.
    @step(num_workers=1)
    async def index_paper(
        self,
        ctx: Context[IngestState],
        ev: PaperParsed,
        storage: Annotated[Storage, Resource(get_storage)],
    ) -> PaperIndexed:
        rows = read_jsonl(_paths().root / "parsed" / f"{ev.arxiv_id}.jsonl")
        new_nodes = await asyncio.to_thread(storage.ingest, documents_from_segments(rows))
        if new_nodes:
            # Durable before this step counts as done: a checkpoint taken after this step must never
            # point at chunks that existed only in the memory of a process that was then killed.
            await asyncio.to_thread(storage.persist)
        async with ctx.store.edit_state() as state:
            state.indexed.append(ev.arxiv_id)
            state.new_nodes += new_nodes
            done, total = len(state.indexed), state.total
        ctx.write_event_to_stream(
            IngestProgress(
                stage="index",
                done=done,
                total=total,
                arxiv_id=ev.arxiv_id,
                status="ok" if new_nodes else "cached",
                message=f"{new_nodes} new chunks",
            )
        )
        return PaperIndexed(arxiv_id=ev.arxiv_id, n_nodes=new_nodes)

    @step(num_workers=3, retry_policy=LLM_RETRY)  # 3 concurrent Anthropic calls; transient errors retried
    async def summarize_paper(
        self,
        ctx: Context[IngestState],
        ev: PaperIndexed,
        llm: Annotated[LLM, Resource(get_llm)],
        papers: Annotated[dict[str, PaperMeta], Resource(get_papers)],
        topic: Annotated[Topic, Resource(get_topic)],
    ) -> PaperSummarized:
        path = _paths().root / "summaries" / f"{ev.arxiv_id}.json"
        summary = load_summary(path)  # idempotent: a saved summary is never paid for twice
        generated = summary is None
        if summary is None:
            meta = papers[ev.arxiv_id]
            rows = read_jsonl(_paths().root / "parsed" / f"{ev.arxiv_id}.jsonl")
            intro, conclusion = summary_input(rows, meta.abstract)
            messages = build_messages(topic.topic, meta.title, meta.abstract, intro, conclusion)
            summary = await summarize(llm, ev.arxiv_id, meta.title, messages)  # outside any state lock
            save_summary(path, summary)
        async with ctx.store.edit_state() as state:
            state.summarized.append(ev.arxiv_id)
            state.summaries_generated += int(generated)
            done, total = len(state.summarized), state.total
        ctx.write_event_to_stream(
            IngestProgress(
                stage="summarize",
                done=done,
                total=total,
                arxiv_id=ev.arxiv_id,
                status="ok" if generated else "cached",
            )
        )
        return PaperSummarized(arxiv_id=ev.arxiv_id, summary_chars=len(summary.summary), generated=generated)

    @step
    async def persist(
        self,
        ctx: Context[IngestState],
        done: list[PaperSummarized],  # fan-in: fires once, after every surviving branch arrives
        storage: Annotated[Storage, Resource(get_storage)],
        embed_model: Annotated[BaseEmbedding, Resource(get_embed_model)],  # same cached instance
    ) -> IngestReport:
        await asyncio.to_thread(storage.persist)
        # The DocumentSummaryIndex reuses the saved summaries (no LLM); rebuilt only on change.
        root = _paths().root
        summaries = load_all_summaries(root / "summaries")
        await asyncio.to_thread(
            ensure_summary_index, storage.index, summaries, embed_model, root / "storage" / "summary"
        )
        state = await ctx.store.get_state()
        return IngestReport(
            papers=len(done),
            nodes=storage.n_nodes,
            new_nodes=state.new_nodes,
            summaries_generated=state.summaries_generated,
            failed=sorted(state.failed),
        )
