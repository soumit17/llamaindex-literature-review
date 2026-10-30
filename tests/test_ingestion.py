"""M2: the ingestion workflow end to end, with fake arXiv, fake LLM and counting embeddings."""

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

import pytest
from workflows.events import StepState, StepStateChanged
from workflows.testing import WorkflowTestRunner

from litreview.config import get_settings
from litreview.corpus import (
    ArxivClient,
    CorpusLock,
    CorpusPaths,
    LockedPaper,
    PaperMeta,
    RateLimiter,
    save_papers,
)
from litreview.events import IngestProgress, IngestReport, IngestRequest
from litreview.resources import get_arxiv_client, get_embed_model, get_llm
from litreview.workflows.ingestion import IngestionWorkflow
from tests.conftest import override_resources
from tests.fakes import CountingEmbedding, FakePdfServer, InstantClock, ScriptedLLM, make_paper_pdf

IDS = ["2501.00001", "2501.00002", "2501.00003"]
PDFS = {
    i: make_paper_pdf(f"Paper {n}", w)
    for n, (i, w) in enumerate(zip(IDS, ["hub", "ring", "tree"], strict=True), 1)
}


@dataclass
class Env:
    """One "process": a fresh workflow instance with its own fakes, over the shared tmp data dir."""

    server: FakePdfServer = field(default_factory=FakePdfServer)
    llm: Any = field(default_factory=lambda: ScriptedLLM(default="A short summary of the paper."))
    embed: Any = field(default_factory=CountingEmbedding.make)

    async def run(self, **request: Any):
        paths = CorpusPaths(get_settings().p2_data_dir)
        clock = InstantClock()
        self.server.bodies = PDFS
        client = ArxivClient(
            paths.cache,
            http=self.server.client(),
            limiter=RateLimiter(3, clock=clock.clock, sleep=clock.sleep),
        )
        manager = await override_resources(
            {get_arxiv_client: client, get_llm: self.llm, get_embed_model: self.embed}
        )
        wf = IngestionWorkflow(timeout=60, resource_manager=manager)
        return await WorkflowTestRunner(wf).run(IngestRequest(**request))


@pytest.fixture
def corpus():
    """A lock file + papers.json for three fixture papers, as scripts/fetch_corpus.py would write."""
    paths = CorpusPaths(get_settings().p2_data_dir)
    lock = CorpusLock(
        query="q",
        created="2026-10-30",
        papers=[LockedPaper(arxiv_id=i, version=1, sha256=hashlib.sha256(PDFS[i]).hexdigest()) for i in IDS],
    )
    lock.save(paths.lock)
    metas = [
        PaperMeta(
            arxiv_id=i,
            version=1,
            title=f"Paper {n}",
            authors=["Ada Lovelace"],
            year=2025,
            published="2025-01-02",
            abstract=f"Abstract of paper {n}.",
            categories=["cs.MA"],
            primary_category="cs.MA",
            abs_url=f"https://arxiv.org/abs/{i}v1",
        )
        for n, i in enumerate(IDS, 1)
    ]
    save_papers(paths.papers, metas)
    return paths


def progress(result, **match) -> list[IngestProgress]:
    return [
        e
        for e in result.collected
        if isinstance(e, IngestProgress) and all(getattr(e, k) == v for k, v in match.items())
    ]


def max_concurrent(result, step_name: str) -> int:
    running: set[str] = set()
    peak = 0
    for e in result.collected:
        if isinstance(e, StepStateChanged) and e.name == step_name:
            if e.step_state == StepState.RUNNING:
                running.add(e.worker_id)
            elif e.step_state == StepState.NOT_RUNNING:
                running.discard(e.worker_id)
            peak = max(peak, len(running))
    return peak


async def test_full_ingest(corpus):
    env = Env()
    r = await env.run()
    report = r.result

    assert isinstance(report, IngestReport)
    assert (report.papers, report.summaries_generated, report.failed) == (3, 3, [])
    assert report.nodes == report.new_nodes > 0
    for stage in ("fetch", "parse", "index", "summarize"):
        assert len(progress(r, stage=stage)) == 3
    # Files on disk: the events only ever carried ids.
    assert all((corpus.root / "parsed" / f"{i}.jsonl").exists() for i in IDS)
    summary = json.loads((corpus.root / "summaries" / f"{IDS[0]}.json").read_text())
    assert summary["summary"] == "A short summary of the paper."
    assert (corpus.root / "storage" / "docstore.json").exists()
    # The LLM saw the abstract, intro and conclusion, and never the references.
    assert len(env.llm.calls) == 3
    prompt = next(c for c in env.llm.calls if "Paper 1" in c)
    assert "Abstract of paper 1." in prompt and "hub patterns" in prompt and "twelve points" in prompt
    assert "Some cited paper" not in prompt


async def test_rerun_is_a_free_no_op(corpus):
    """M2 acceptance: a re-run is a no-op (0 new nodes, $0)."""
    first = await Env().run()
    env = Env()  # a new "process": new workflow, new fakes, same data dir
    r = await env.run()

    assert r.result.new_nodes == 0 and r.result.nodes == first.result.nodes
    assert r.result.summaries_generated == 0 and env.llm.calls == []
    assert env.server.hits == [] and env.embed.texts_embedded == 0
    assert {e.status for e in progress(r, stage="summarize")} == {"cached"}


async def test_rebuild_reindexes_from_the_embedding_cache(corpus):
    first = await Env().run()
    env = Env()
    r = await env.run(rebuild=True)

    assert r.result.new_nodes == first.result.nodes  # index rebuilt from scratch...
    assert env.embed.texts_embedded == 0  # ...without re-embedding (IngestionCache survived)
    assert env.llm.calls == []  # and summaries are kept


async def test_fetch_retries_then_succeeds(corpus):
    env = Env(server=FakePdfServer(fail_times={IDS[1]: 2}))
    r = await env.run()

    retries = progress(r, stage="fetch", arxiv_id=IDS[1], status="retry")
    assert [e.message.split(" after")[0] for e in retries] == ["retry 1", "retry 2"]
    assert "503" in retries[0].message
    assert r.result.papers == 3 and r.result.failed == []


async def test_catch_error_lets_the_rest_finish(corpus):
    """M2 acceptance: the forced failure of one paper is recovered via catch_error."""
    env = Env(server=FakePdfServer(fail={IDS[1]: 503}))
    r = await env.run()

    assert r.result.failed == [IDS[1]]
    assert r.result.papers == 2 and r.result.summaries_generated == 2
    assert len(progress(r, stage="fetch", arxiv_id=IDS[1], status="retry")) == 3  # 4 attempts in all
    [failed] = progress(r, status="failed")
    assert "4 attempts" in failed.message


async def test_demo_fail_flag_and_all_papers_failing(corpus):
    r = await Env().run(fail_ids=IDS)  # every branch is dropped: the fan-in still fires, with []
    assert r.result.papers == 0 and r.result.failed == sorted(IDS)


async def test_limit_takes_the_first_papers(corpus):
    r = await Env().run(limit=1)
    assert r.result.papers == 1 and r.result.summaries_generated == 1


async def test_worker_limits_hold(corpus):
    r = await Env().run()
    assert max_concurrent(r, "fetch_pdf") <= 2
    assert max_concurrent(r, "index_paper") == 1
