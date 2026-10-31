"""M3: curate the drafted questions into data/qa/labeled.jsonl (spec §4.3). You decide; $0.

For each candidate: [k]eep, [e]dit (question text and/or relevant papers), [d]rop, [s]kip, [q]uit.
Decisions are saved as you go, so you can stop and resume. Aim for 25 kept.

    uv run python scripts/curate_qa.py
"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from litreview.config import get_settings
from litreview.corpus import CorpusPaths, load_papers
from litreview.qa import append_jsonl, read_labeled

TARGET = 25
console = Console()


def main() -> None:
    s = get_settings()
    qa = s.p2_data_dir / "qa"
    candidates = read_labeled(qa / "candidates.jsonl")
    if not candidates:
        raise typer.BadParameter("no candidates; run scripts/bootstrap_qa.py first")
    titles = {p.arxiv_id: p.title for p in load_papers(CorpusPaths(s.p2_data_dir).papers)}
    kept, rejected = read_labeled(qa / "labeled.jsonl"), read_labeled(qa / "rejected.jsonl")
    decided = {q.id for q in kept + rejected}

    for c in candidates:
        if c.id in decided:
            continue
        papers = "\n".join(f"  {i}  {titles.get(i, '?')}" for i in c.relevant_arxiv_ids)
        console.print(
            Panel(
                f"[bold]{c.question}[/]\n\n[dim]{c.kind}, section: {c.relevant_section}[/]\n{papers}",
                title=f"{c.id}   kept {len(kept)}/{TARGET}",
            )
        )
        choice = Prompt.ask("[k]eep [e]dit [d]rop [s]kip [q]uit", choices=list("kedsq"), default="k")
        if choice == "q":
            break
        if choice == "s":
            continue
        if choice == "d":
            append_jsonl(qa / "rejected.jsonl", c)
            continue
        if choice == "e":
            c.question = Prompt.ask("question", default=c.question)
            ids = Prompt.ask("relevant arxiv ids (comma-separated)", default=",".join(c.relevant_arxiv_ids))
            c.relevant_arxiv_ids = [i.strip() for i in ids.split(",") if i.strip() in titles]
            if not c.relevant_arxiv_ids:
                console.print("[red]no valid ids; skipped[/]")
                continue
        append_jsonl(qa / "labeled.jsonl", c)
        kept.append(c)

    console.print(f"\n{len(kept)} kept in {qa / 'labeled.jsonl'} (target {TARGET})")
    if len(kept) >= TARGET:
        console.print("next: uv run python -m evals.retrieval")


if __name__ == "__main__":
    typer.run(main)
