"""M1: build the arXiv corpus (spec §4.1). Outside Workflows on purpose; M2's ingestion takes over.

First run:  search arXiv -> you pick ~25 from a numbered list -> data/corpus.lock.json + papers.json
            -> download PDFs into data/pdfs/ (one request every 3 s).
Re-run:     the lock exists, so no search; cached metadata; PDFs whose hash matches are kept.
            Expect "network requests: 0".

    uv run python scripts/fetch_corpus.py                 # interactive pick
    uv run python scripts/fetch_corpus.py --select 1-25   # non-interactive
    uv run python scripts/fetch_corpus.py --repick        # pick again (search is cached, $0, 0 requests)
"""

from __future__ import annotations

import asyncio

import typer
from rich.console import Console
from rich.prompt import Confirm, Prompt
from rich.table import Table

from litreview.config import CONFIG_DIR, get_settings
from litreview.corpus import (
    ArxivClient,
    Candidate,
    CorpusLock,
    CorpusPaths,
    Topic,
    download_all,
    ensure_papers_json,
    gather_candidates,
    new_lock,
    parse_selection,
    save_papers,
)

console = Console()


def show(candidates: list[Candidate]) -> None:
    table = Table(title="Candidates (★ = suggested in config/topic.json, not from the search)")
    for col in ("#", "id", "year", "cat", "title", "first author"):
        table.add_column(col, overflow="fold" if col == "title" else "ellipsis")
    for i, c in enumerate(candidates, 1):
        p = c.paper
        star = "★ " if c.suggested else ""
        table.add_row(str(i), p.arxiv_id, str(p.year), p.primary_category, star + p.title, p.authors[0])
    console.print(table)


def pick(candidates: list[Candidate], target: int, select: str | None) -> list[int]:
    if select is not None:
        return parse_selection(select, len(candidates))
    while True:
        text = Prompt.ask(f"Pick ~{target} papers (e.g. [cyan]1-20,23,41-44[/] or [cyan]all[/])")
        try:
            chosen = parse_selection(text, len(candidates))
        except ValueError as e:
            console.print(f"[red]{e}[/]")
            continue
        if Confirm.ask(f"{len(chosen)} papers selected. Write the lock file?", default=True):
            return chosen


async def run(select: str | None, repick: bool) -> int:
    paths = CorpusPaths(get_settings().p2_data_dir)
    topic = Topic.load(CONFIG_DIR / "topic.json")
    async with ArxivClient(paths.cache) as client:
        lock = None if repick else CorpusLock.load(paths.lock)
        if lock is None:
            candidates = await gather_candidates(client, topic)
            show(candidates)
            chosen = [candidates[i].paper for i in pick(candidates, topic.target_papers, select)]
            lock = new_lock(topic.query, chosen)
            lock.save(paths.lock)
            save_papers(paths.papers, chosen)
            console.print(f"wrote {paths.lock} ({len(chosen)} papers)")
        else:
            console.print(f"using existing {paths.lock} ({len(lock.papers)} papers); no search")
        await ensure_papers_json(client, lock, paths)

        console.print(f"PDFs -> {paths.pdfs} (new downloads are spaced 3 s apart)")
        marks = {"downloaded": "[green]downloaded[/]", "kept": "[dim]kept[/]", "failed": "[red]FAILED[/]"}
        report = await download_all(
            client, lock, paths, on_done=lambda i, status: console.print(f"  {i:14} {marks[status]}")
        )

    console.print(
        f"\n{len(report.downloaded) + len(report.kept)}/{len(lock.papers)} PDFs on disk "
        f"(downloaded {len(report.downloaded)}, kept {len(report.kept)}, failed {len(report.failed)})"
        f"\nnetwork requests: {client.requests}"
    )
    for arxiv_id, error in report.failed.items():
        console.print(f"[red]{arxiv_id}: {error}[/]  (re-run to retry)")
    return 1 if report.failed else 0


def main(
    select: str | None = typer.Option(None, help="Selection like '1-25' instead of the prompt."),
    repick: bool = typer.Option(False, help="Ignore the existing lock and pick again."),
) -> None:
    raise typer.Exit(asyncio.run(run(select, repick)))


if __name__ == "__main__":
    typer.run(main)
