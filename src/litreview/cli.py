"""`litreview` command line. M0: hello, tiny, smoke, draw, cost. M2: ingest. M4: review."""

from __future__ import annotations

import asyncio
import contextlib
import json
from pathlib import Path

import typer
from rich.console import Console
from workflows import Workflow
from workflows.events import StepStateChanged

from litreview.config import PROJECT_ROOT, get_settings

app = typer.Typer(no_args_is_help=True, add_completion=False)
console = Console()


def _short(event_name: str) -> str:
    """StepStateChanged reports names as "Tick" or "<class 'pkg.mod.Tick'>"; keep just "Tick"."""
    return event_name.rsplit(".", 1)[-1].rstrip("'>")


async def _run_streaming(wf: Workflow, start_event, debug_steps: bool):
    """Run a workflow and print every streamed event. This is the caller side of streaming:
    steps call `ctx.write_event_to_stream(...)`, the caller iterates `handler.stream_events()`."""
    handler = wf.run(start_event=start_event)
    async for ev in handler.stream_events(expose_internal=debug_steps):
        if isinstance(ev, StepStateChanged):
            # Internal events: lets you *see* each step start/finish and which worker ran it.
            out = f" -> {_short(ev.output_event_name)}" if ev.output_event_name else ""
            console.print(
                f"  [dim]{ev.name:<8} {ev.step_state.value:<12} in={_short(ev.input_event_name)}{out}[/dim]"
            )
        else:
            console.print(f"  [cyan]stream[/cyan] {type(ev).__name__}: {ev.model_dump()}")
    return await handler


@app.command()
def hello(
    name: str = typer.Argument("world"),
    rounds: int = typer.Option(3, help="How many times the tick step loops."),
    debug_steps: bool = typer.Option(
        False, "--debug-steps", help="Also show internal StepStateChanged events."
    ),
) -> None:
    """Run the M0 hello workflow (branch, loop, streaming, typed state). Free: no LLM."""
    from litreview.workflows.hello import Greet, HelloWorkflow

    result = asyncio.run(
        _run_streaming(HelloWorkflow(timeout=30), Greet(name=name, rounds=rounds), debug_steps)
    )
    console.print(f"[green]result[/green] {result!r}")


@app.command()
def tiny(text: str = typer.Argument("hello workflows")) -> None:
    """Run the unbound-function workflow. Free: no LLM."""
    from litreview.workflows.tiny_unbound import Shout, TinyWorkflow

    async def go() -> str:
        return await TinyWorkflow(timeout=30).run(start_event=Shout(text=text))

    console.print(asyncio.run(go()))


@app.command()
def smoke(prompt: str = typer.Option(None, help="Override the question sent to Haiku.")) -> None:
    """ONE live Haiku call through the Resource-injected LLM. Costs roughly $0.0001."""
    from litreview.resources import get_cost_tracker
    from litreview.workflows.smoke import Ask, SmokeWorkflow

    if not get_settings().anthropic_api_key:
        raise typer.BadParameter("ANTHROPIC_API_KEY is not set; put it in .env")
    tracker = get_cost_tracker()
    before = tracker.spent_usd
    start = Ask(prompt=prompt) if prompt else Ask()

    async def go() -> str:
        return await SmokeWorkflow(timeout=60).run(start_event=start)

    console.print(f"[green]Haiku says:[/green] {asyncio.run(go())}")
    # The workflow built its own tracker via the Resource; re-read the ledger for the true total.
    after = get_cost_tracker().spent_usd
    console.print(
        f"[yellow]this call:[/yellow] ${after - before:.6f}   [yellow]P2 total:[/yellow] ${after:.6f}"
    )


@app.command()
def draw(out_dir: Path = typer.Option(PROJECT_ROOT / "docs")) -> None:
    """Write 'all possible flows' diagrams (interactive HTML + Mermaid) for every workflow so far."""
    from llama_index.utils.workflow import draw_all_possible_flows, draw_all_possible_flows_mermaid

    from litreview.workflows.hello import HelloWorkflow
    from litreview.workflows.tiny_unbound import TinyWorkflow

    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    from litreview.workflows.ingestion import IngestionWorkflow
    from litreview.workflows.review import ReviewWorkflow

    flows = [
        ("hello", HelloWorkflow),
        ("tiny", TinyWorkflow),
        ("ingest", IngestionWorkflow),
        ("review", ReviewWorkflow),
    ]
    for name, wf in flows:
        html = out_dir / f"{name}_flow.html"
        # pyvis copies its JS helpers into ./lib and the HTML references them relatively,
        # so render from inside out_dir to keep lib/ next to the HTML.
        with contextlib.chdir(out_dir):
            draw_all_possible_flows(wf, filename=str(html))
        mermaid = draw_all_possible_flows_mermaid(wf, filename=str(out_dir / f"{name}_flow.mermaid"))
        (out_dir / f"{name}_flow.md").write_text(
            f"# {name} workflow: all possible flows\n\n```mermaid\n{mermaid}\n```\n"
        )
        (out_dir / f"{name}_flow.mermaid").unlink(missing_ok=True)
        console.print(f"wrote {html} and {name}_flow.md")


@app.command()
def ingest(
    limit: int = typer.Option(None, help="Only the first N papers in the lock file."),
    rebuild: bool = typer.Option(False, help="Re-parse and re-index (summaries and embeddings stay cached)."),
    fail: list[str] = typer.Option(
        [], "--fail", help="Demo: make fetch_pdf fail for this arxiv id (watch retries + catch_error)."
    ),
    debug_steps: bool = typer.Option(False, "--debug-steps", help="Show StepStateChanged events."),
) -> None:
    """Run the ingestion workflow: fetch -> parse -> index -> summarize. Summaries cost ~$0.001/paper."""
    from llama_index.utils.workflow import draw_most_recent_execution_mermaid
    from rich.progress import BarColumn, MofNCompleteColumn, Progress, TaskID, TextColumn, TimeElapsedColumn

    from litreview.corpus import CorpusLock, CorpusPaths
    from litreview.events import IngestProgress, IngestReport, IngestRequest
    from litreview.resources import get_cost_tracker
    from litreview.workflows.ingestion import IngestionWorkflow

    s = get_settings()
    paths = CorpusPaths(s.p2_data_dir)
    lock = CorpusLock.load(paths.lock)
    if lock is None:
        raise typer.BadParameter(f"{paths.lock} not found; run scripts/fetch_corpus.py first")
    todo = [p for p in lock.papers[:limit] if not (paths.root / "summaries" / f"{p.arxiv_id}.json").exists()]
    if todo and not s.anthropic_api_key:
        raise typer.BadParameter(f"{len(todo)} papers need a summary but ANTHROPIC_API_KEY is not set")
    spent_before = get_cost_tracker().spent_usd
    marks = {"retry": "[yellow]retry[/]", "failed": "[red]FAILED[/]"}

    async def go() -> IngestReport:
        handler = IngestionWorkflow(timeout=3600).run(
            start_event=IngestRequest(limit=limit, rebuild=rebuild, fail_ids=fail)
        )
        columns = (TextColumn("{task.description:<10}"), BarColumn(), MofNCompleteColumn())
        with Progress(*columns, TimeElapsedColumn(), console=console) as progress:
            bars: dict[str, TaskID] = {}
            async for ev in handler.stream_events(expose_internal=debug_steps):
                if isinstance(ev, IngestProgress):
                    if ev.stage == "start":
                        for stage in ("fetch", "parse", "index", "summarize"):
                            bars[stage] = progress.add_task(stage, total=ev.total)
                    elif ev.status in marks:
                        progress.console.print(f"  {marks[ev.status]} {ev.arxiv_id}: {ev.message}")
                    else:
                        progress.update(bars[ev.stage], completed=ev.done)
                elif isinstance(ev, StepStateChanged):
                    progress.console.print(
                        f"  [dim]{ev.name:<16} {ev.step_state.value:<12} worker={ev.worker_id}[/dim]"
                    )
            report = await handler
        out = s.p2_runs_dir / "ingest_execution.mermaid"
        out.parent.mkdir(parents=True, exist_ok=True)
        draw_most_recent_execution_mermaid(handler, filename=str(out))
        return report

    report = asyncio.run(go())
    spent = get_cost_tracker().spent_usd
    console.print(
        f"\n[green]ingested[/] {report.papers} papers   [green]chunks[/] {report.nodes} "
        f"(+{report.new_nodes} new)   [green]summaries generated[/] {report.summaries_generated}"
        f"   [yellow]cost[/] ${spent - spent_before:.4f} (P2 total ${spent:.4f})"
    )
    if report.failed:
        console.print(f"[red]failed:[/] {', '.join(report.failed)}  (re-run to retry them)")
    console.print(f"[dim]execution diagram: {s.p2_runs_dir / 'ingest_execution.mermaid'}[/]")


@app.command()
def review(
    question: str = typer.Argument(None, help="Research question (default: topic.json default_question)."),
    max_subquestions: int = typer.Option(5, "--max-subquestions", help="3-6; fewer is cheaper."),
    target_words: int = typer.Option(1500, "--target-words"),
    final: bool = typer.Option(False, "--final", help="Write sections with Sonnet instead of Haiku (~10x)."),
    debug_steps: bool = typer.Option(
        False, "--debug-steps", help="Show StepStateChanged (watch num_workers)."
    ),
    as_json: bool = typer.Option(False, "--json", help="Print every streamed event as NDJSON."),
    quiet: bool = typer.Option(False, "--quiet", help="Print only the output paths."),
) -> None:
    """Write a cited literature review: plan -> research -> outline -> write. ~$0.01 on Haiku."""
    import os

    from llama_index.utils.workflow import draw_most_recent_execution_mermaid
    from rich.live import Live

    from litreview.config import CONFIG_DIR
    from litreview.corpus import Topic
    from litreview.events import ReviewReady, ReviewRequest
    from litreview.hitl import auto_responder, drive
    from litreview.review_view import ReviewView
    from litreview.workflows.review import ReviewWorkflow

    if final:  # read by get_writer_llm when the Resource is first resolved
        os.environ["P2_LLM_PROFILE"] = "final"
        get_settings.cache_clear()
    s = get_settings()
    if not s.anthropic_api_key:
        raise typer.BadParameter("ANTHROPIC_API_KEY is not set; put it in .env")
    if not (s.p2_data_dir / "storage" / "docstore.json").exists():
        raise typer.BadParameter("no index yet; run `uv run litreview ingest` first")
    question = question or Topic.load(CONFIG_DIR / "topic.json").default_question
    request = ReviewRequest(question=question, max_subquestions=max_subquestions, target_words=target_words)
    view = ReviewView(s.p2_runs_dir / "costs.jsonl")

    def on_event(ev) -> None:
        if as_json:
            print(json.dumps({"type": type(ev).__name__, **ev.model_dump(mode="json")}), flush=True)
            return
        view.update(ev)
        if isinstance(ev, StepStateChanged) and not quiet:
            out = f" -> {_short(ev.output_event_name)}" if ev.output_event_name else ""
            console.print(
                f"  [dim]{ev.name:<20} {ev.step_state.value:<12} worker={ev.worker_id}"
                f" in={_short(ev.input_event_name)}{out}[/dim]"
            )

    async def go() -> ReviewReady:
        handler = ReviewWorkflow(timeout=1800).run(start_event=request)
        # M4: the outline is approved (and a vague question clarified) automatically; M5 asks you.
        if as_json or quiet:
            result = await drive(handler, auto_responder, on_event, expose_internal=debug_steps)
        else:
            with Live(view, console=console, refresh_per_second=8, transient=False):
                result = await drive(handler, auto_responder, on_event, expose_internal=debug_steps)
        folder = Path(result.markdown_path).parent
        mermaid = draw_most_recent_execution_mermaid(handler, filename=str(folder / "execution.mermaid"))
        (folder / "execution.md").write_text(f"# Execution of this run\n\n```mermaid\n{mermaid}\n```\n")
        (folder / "execution.mermaid").unlink(missing_ok=True)
        return result

    result = asyncio.run(go())
    if as_json:
        return
    if quiet:
        print(result.markdown_path)
        print(result.bib_path)
        return
    if result.error:
        console.print(f"[red]run failed, partial output written:[/] {result.error}")
    console.print(
        f"\n[green]review[/] {result.markdown_path}\n[green]bibtex[/] {result.bib_path}\n"
        f"[green]citations[/] {result.n_citations}   [yellow]quotes not found in chunk[/] "
        f"{result.unsupported_claims}   [yellow]invented markers removed[/] {result.unknown_markers}\n"
        f"[yellow]cost[/] ${result.cost_usd:.4f}"
    )
    if result.failed_subquestions:
        console.print(f"[red]research failed for:[/] {'; '.join(result.failed_subquestions)}")


@app.command()
def cost() -> None:
    """Show P2 spend so far from runs/costs.jsonl."""
    ledger = get_settings().p2_runs_dir / "costs.jsonl"
    rows = [json.loads(line) for line in ledger.read_text().splitlines()] if ledger.exists() else []
    total = sum(r["cost_usd"] for r in rows)
    console.print(f"{len(rows)} calls, ${total:.6f} of ${get_settings().p2_spend_cap_usd:.2f} cap")


if __name__ == "__main__":
    app()
