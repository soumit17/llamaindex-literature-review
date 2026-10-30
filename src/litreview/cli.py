"""`litreview` command line. M0 commands: hello, tiny, smoke, draw, cost."""

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
    """Write 'all possible flows' diagrams (interactive HTML + Mermaid) for the M0 workflows."""
    from llama_index.utils.workflow import draw_all_possible_flows, draw_all_possible_flows_mermaid

    from litreview.workflows.hello import HelloWorkflow
    from litreview.workflows.tiny_unbound import TinyWorkflow

    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, wf in [("hello", HelloWorkflow), ("tiny", TinyWorkflow)]:
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
def cost() -> None:
    """Show P2 spend so far from runs/costs.jsonl."""
    ledger = get_settings().p2_runs_dir / "costs.jsonl"
    rows = [json.loads(line) for line in ledger.read_text().splitlines()] if ledger.exists() else []
    total = sum(r["cost_usd"] for r in rows)
    console.print(f"{len(rows)} calls, ${total:.6f} of ${get_settings().p2_spend_cap_usd:.2f} cap")


if __name__ == "__main__":
    app()
