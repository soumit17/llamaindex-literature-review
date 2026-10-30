"""M2 splitter experiment (spec §9.1): same parsed papers, three ways to chunk them. $0, local only.

For each splitter it prints chunk statistics and builds a vector index under
data/experiments/splitters/<name>/. M3's retrieval eval loads those indexes and measures
hit-rate@5, which is what decides the winner (written to config/retrieval.json).

Needs `litreview ingest` first (it reads data/parsed/). Embedding is CPU-bound (~0.2 s per chunk);
sentence-512 reuses the ingest's embedding cache, the other two take a few minutes each.

    uv run python scripts/splitter_experiment.py                 # all three
    uv run python scripts/splitter_experiment.py --only semantic
"""

from __future__ import annotations

import statistics
import time

import typer
from rich.console import Console
from rich.table import Table

from litreview.config import get_settings
from litreview.resources import get_embed_model
from litreview.retrieval.parsing import read_jsonl
from litreview.retrieval.pipeline import (
    SplitterConfig,
    Storage,
    documents_from_segments,
    ensure_nltk_data,
    make_splitter,
)

VARIANTS = {
    "sentence-512": SplitterConfig(kind="sentence", chunk_size=512, chunk_overlap=64),
    "sentence-1024": SplitterConfig(kind="sentence", chunk_size=1024, chunk_overlap=128),
    "semantic": SplitterConfig(kind="semantic"),
}
console = Console()


def main(only: str | None = typer.Option(None, help=f"One of {', '.join(VARIANTS)}.")) -> None:
    s = get_settings()
    parsed = sorted((s.p2_data_dir / "parsed").glob("*.jsonl"))
    if not parsed:
        raise typer.BadParameter("no data/parsed/*.jsonl; run `uv run litreview ingest` first")
    ensure_nltk_data(s.p2_cache_dir)
    documents = [d for path in parsed for d in documents_from_segments(read_jsonl(path))]
    embed_model = get_embed_model()
    console.print(f"{len(parsed)} papers, {len(documents)} parsed segments")

    table = Table(title="Splitter experiment (hit-rate@5 comes in M3)")
    for col in ("splitter", "chunks", "median tokens", "p90 tokens", "seconds"):
        table.add_column(col, justify="right" if col != "splitter" else "left")
    for name, config in VARIANTS.items():
        if only and name != only:
            continue
        console.print(f"[cyan]{name}[/]: splitting and embedding...")
        started = time.time()
        storage = Storage(
            storage_dir=s.p2_data_dir / "experiments" / "splitters" / name,
            cache_dir=s.p2_data_dir / "cache",  # shared: sentence-512 hits the ingest's cache
            splitter=make_splitter(config, embed_model),
            embed_model=embed_model,
        )
        storage.ingest(documents)
        storage.persist()
        sizes = [_tokens(n.get_content()) for n in storage.index.docstore.docs.values()]
        table.add_row(
            name,
            str(len(sizes)),
            str(int(statistics.median(sizes))),
            str(int(statistics.quantiles(sizes, n=10)[-1])),
            f"{time.time() - started:.0f}",
        )
    console.print(table)


def _tokens(text: str) -> int:
    return len(text.split()) * 4 // 3  # rough: ~0.75 words per token; enough to compare splitters


if __name__ == "__main__":
    typer.run(main)
