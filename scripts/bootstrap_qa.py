"""M3: draft ~40 candidate retrieval questions with Haiku from the paper abstracts (spec §4.3).

Five calls (5 papers each), about $0.003 in total. Then curate with scripts/curate_qa.py.

    uv run python scripts/bootstrap_qa.py
"""

from __future__ import annotations

import asyncio

import typer
from rich.console import Console

from litreview.config import get_settings
from litreview.corpus import CorpusPaths, load_papers
from litreview.qa import LabeledQuestion, batches, draft_batch, write_jsonl
from litreview.resources import get_cost_tracker, get_llm, resolve

console = Console()


async def run(force: bool) -> None:
    s = get_settings()
    out = s.p2_data_dir / "qa" / "candidates.jsonl"
    if out.exists() and not force:
        raise typer.BadParameter(f"{out} exists; pass --force to draft (and pay for) a new set")
    papers = load_papers(CorpusPaths(s.p2_data_dir).papers)
    llm = await resolve(get_llm)
    before = get_cost_tracker().spent_usd

    rows: list[LabeledQuestion] = []
    for n, batch in enumerate(batches(papers), start=1):
        drafted = await draft_batch(llm, batch)
        for q in drafted:
            rows.append(LabeledQuestion(id=f"c{len(rows) + 1:02d}", **q.model_dump()))
        console.print(f"batch {n}: {len(drafted)} questions")
    write_jsonl(out, rows)
    spent = get_cost_tracker().spent_usd
    console.print(f"wrote {len(rows)} candidates to {out}   cost ${spent - before:.4f}")
    console.print("next: uv run python scripts/curate_qa.py")


def main(force: bool = typer.Option(False, help="Overwrite existing candidates.")) -> None:
    if not get_settings().anthropic_api_key:
        raise typer.BadParameter("ANTHROPIC_API_KEY is not set; put it in .env")
    asyncio.run(run(force))


if __name__ == "__main__":
    typer.run(main)
