"""Retrieval eval matrix (spec §17.1): splitter x {rerank on, off} x {router, vector-only}.

Metric definitions (paper level, on what `research` will actually receive):
- hit-rate@5: 1 if any of the top-5 chunks comes from a relevant paper (LlamaIndex `HitRate`);
- MRR: 1 / rank of the first relevant paper, papers deduplicated in chunk order (LlamaIndex `MRR`).

Embedding + reranking are local ($0). Router configs make one Haiku selector call per question
(~$0.0001 each); they run last, and `--no-router` skips them.

Splitter variants: the ingest index (data/storage, whatever config/retrieval.json says) plus every
index built by scripts/splitter_experiment.py under data/experiments/splitters/.

    uv run python -m evals.retrieval                # full matrix
    uv run python -m evals.retrieval --no-router    # $0
    uv run python -m evals.retrieval --apply        # also write the winner to config/retrieval.json
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import typer
from llama_index.core import StorageContext, VectorStoreIndex, load_index_from_storage
from llama_index.core.base.embeddings.base import BaseEmbedding
from llama_index.core.evaluation.retrieval.metrics import MRR, HitRate
from llama_index.core.schema import QueryBundle
from rich.console import Console
from rich.table import Table

from litreview.config import CONFIG_DIR, PROJECT_ROOT, get_settings
from litreview.qa import LabeledQuestion, read_labeled
from litreview.resources import get_cost_tracker, get_embed_model, get_llm, get_reranker, resolve
from litreview.retrieval.engines import (
    FastEmbedRerank,
    QueryConfig,
    ensure_summary_index,
    load_summary_index,
    make_query_engine,
    make_retriever,
)
from litreview.retrieval.pipeline import SplitterConfig, ensure_nltk_data
from litreview.retrieval.summaries import load_all_summaries

REPORT = PROJECT_ROOT / "evals" / "reports" / "retrieval.md"
console = Console()


@dataclass
class Row:
    splitter: str
    rerank: bool
    router: bool
    hit_rate: float
    mrr: float
    n: int
    seconds: float

    @property
    def name(self) -> str:
        retriever = "router" if self.router else "vector"
        return f"{self.splitter} | rerank {'on' if self.rerank else 'off'} | {retriever}"


def splitter_name(c: SplitterConfig) -> str:
    return "semantic" if c.kind == "semantic" else f"{c.kind}-{c.chunk_size}"


def variants() -> dict[str, Path]:
    data = get_settings().p2_data_dir
    config = SplitterConfig(**json.loads((CONFIG_DIR / "retrieval.json").read_text())["splitter"])
    found = {splitter_name(config): data / "storage"}
    for d in sorted((data / "experiments" / "splitters").glob("*")):
        if (d / "docstore.json").exists():
            found.setdefault(d.name, d)
    return found


def papers_in_rank_order(nodes) -> list[str]:
    seen: list[str] = []
    for n in nodes:
        arxiv_id = n.node.metadata["arxiv_id"]
        if arxiv_id not in seen:
            seen.append(arxiv_id)
    return seen


def evaluate(engine, questions: list[LabeledQuestion]) -> tuple[float, float]:
    hits, mrrs = [], []
    for q in questions:
        retrieved = papers_in_rank_order(engine.retrieve(QueryBundle(q.question)))
        hits.append(HitRate().compute(expected_ids=q.relevant_arxiv_ids, retrieved_ids=retrieved).score)
        mrrs.append(MRR().compute(expected_ids=q.relevant_arxiv_ids, retrieved_ids=retrieved).score)
    return sum(hits) / len(hits), sum(mrrs) / len(mrrs)


def load_variant(path: Path, embed_model: BaseEmbedding):
    index = load_index_from_storage(
        StorageContext.from_defaults(persist_dir=str(path)), embed_model=embed_model
    )
    assert isinstance(index, VectorStoreIndex)
    summaries = load_all_summaries(get_settings().p2_data_dir / "summaries")
    ensure_summary_index(index, summaries, embed_model, path / "summary")  # $0, rebuilt only if stale
    return index, load_summary_index(path / "summary", embed_model)


async def run(router: bool, apply: bool) -> None:
    s = get_settings()
    questions = read_labeled(s.p2_data_dir / "qa" / "labeled.jsonl")
    if not questions:
        raise typer.BadParameter("no data/qa/labeled.jsonl; run scripts/bootstrap_qa.py and curate_qa.py")
    if len(questions) < 25:
        console.print(f"[yellow]only {len(questions)} labeled questions (target 25)[/]")
    ensure_nltk_data(s.p2_cache_dir)
    embed_model = await resolve(get_embed_model)
    reranker: FastEmbedRerank = await resolve(get_reranker)
    llm = await resolve(get_llm) if router else None
    spent_before = get_cost_tracker().spent_usd
    loaded = {name: load_variant(path, embed_model) for name, path in variants().items()}

    rows: list[Row] = []
    for use_router in [False, True] if router else [False]:  # router (paid) configs last
        for name, (vector_index, summary_index) in loaded.items():
            for rerank in (False, True):
                config = QueryConfig(router=use_router, rerank=rerank)
                retriever = make_retriever(vector_index, summary_index, config, llm, embed_model)
                engine = make_query_engine(retriever, config, reranker, llm)
                started = time.time()
                hit, mrr = evaluate(engine, questions)
                row = Row(name, rerank, use_router, hit, mrr, len(questions), time.time() - started)
                rows.append(row)
                console.print(f"  {row.name:<42} hit@5 {hit:.2f}  MRR {mrr:.2f}  ({row.seconds:.0f}s)")

    best = max(rows, key=lambda r: (round(r.hit_rate, 3), round(r.mrr, 3), not r.router, not r.rerank))
    spent = get_cost_tracker().spent_usd - spent_before
    show(rows, best)
    write_report(rows, best, spent)
    console.print(f"report: {REPORT}   cost ${spent:.4f}")
    if apply:
        apply_config(best)


def show(rows: list[Row], best: Row) -> None:
    table = Table(title="Retrieval eval (paper level, top-5 chunks)")
    for col in ("splitter", "rerank", "retriever", "hit@5", "MRR"):
        table.add_column(col)
    for r in sorted(rows, key=lambda r: (-r.hit_rate, -r.mrr)):
        style = "bold green" if r is best else None
        table.add_row(
            r.splitter,
            "on" if r.rerank else "off",
            "router" if r.router else "vector",
            f"{r.hit_rate:.2f}",
            f"{r.mrr:.2f}",
            style=style,
        )
    console.print(table)


def write_report(rows: list[Row], best: Row, spent: float) -> None:
    lines = [
        "# Retrieval eval",
        "",
        f"{rows[0].n} labeled questions (data/qa/labeled.jsonl). Paper-level metrics over the top-5 "
        "chunks: hit-rate@5 and MRR (LlamaIndex `HitRate` / `MRR`).",
        "",
        "| splitter | rerank | retriever | hit@5 | MRR | seconds |",
        "|---|---|---|---|---|---|",
    ]
    for r in sorted(rows, key=lambda r: (-r.hit_rate, -r.mrr)):
        mark = " **(chosen)**" if r is best else ""
        lines.append(
            f"| {r.splitter}{mark} | {'on' if r.rerank else 'off'} | {'router' if r.router else 'vector'} "
            f"| {r.hit_rate:.2f} | {r.mrr:.2f} | {r.seconds:.0f} |"
        )
    lines += [
        "",
        f"Chosen: **{best.name}** (highest hit@5, then MRR; ties prefer the cheaper: no router, no rerank).",
        f"Acceptance (spec M3): hit@5 >= 0.8 -> **{'met' if best.hit_rate >= 0.8 else 'NOT met'}**.",
        f"Eval cost: ${spent:.4f}.",
        "",
        "## Notes (yours)",
        "",
        "- Which change moved hit-rate most: splitter, rerank or router?",
        "- Where did misses come from (look at the questions)?",
        "",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines))
    (REPORT.with_suffix(".json")).write_text(json.dumps([asdict(r) for r in rows], indent=2))


def apply_config(best: Row) -> None:
    path = CONFIG_DIR / "retrieval.json"
    config = json.loads(path.read_text())
    config["query"].update({"router": best.router, "rerank": best.rerank})
    current = splitter_name(SplitterConfig(**config["splitter"]))
    if best.splitter != current:
        kind, _, size = best.splitter.partition("-")
        config["splitter"] = (
            {"kind": "semantic"}
            if kind == "semantic"
            else {"kind": kind, "chunk_size": int(size), "chunk_overlap": int(size) // 8}
        )
        console.print("[yellow]splitter changed: run `uv run litreview ingest --rebuild` to re-index[/]")
    path.write_text(json.dumps(config, indent=2) + "\n")
    console.print(f"wrote {path}")


def main(
    router: bool = typer.Option(True, help="Include router configs (one Haiku call per question)."),
    apply: bool = typer.Option(False, help="Write the winning config to config/retrieval.json."),
) -> None:
    asyncio.run(run(router, apply))


if __name__ == "__main__":
    typer.run(main)
