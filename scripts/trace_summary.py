"""Print the latest traced run from runs/traces/spans.jsonl as a timed tree ($0, no backend needed).

uv run python scripts/trace_summary.py                  # latest ReviewWorkflow run
uv run python scripts/trace_summary.py --root Ingestion # latest IngestionWorkflow run
uv run python scripts/trace_summary.py --all            # include LLM / retrieval / quote spans
"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.tree import Tree

from litreview.config import get_settings
from litreview.traces import Span, latest_trace, load, peak_overlap, tree

console = Console()


def add(node: Tree, span: Span, t0: int, show_all: bool) -> None:
    for child in span.children:
        is_step = child.name.count(".") == 1 and "Workflow" in child.name
        if not (show_all or is_step or child.children):
            continue
        label = f"{child.name}  [dim]+{(child.start_ns - t0) / 1e9:.1f}s, {child.ms:.0f} ms[/]"
        if child.status == "ERROR":
            label += "  [red]error[/]"
        add(node.add(label), child, t0, show_all)


def main(
    root: str = typer.Option("Review", help="Pick the latest run whose root span name contains this."),
    show_all: bool = typer.Option(False, "--all", help="Also show LLM, retrieval and quote spans."),
) -> None:
    spans = load(get_settings().p2_runs_dir / "traces" / "spans.jsonl")
    trace = latest_trace(spans, root_contains=root)
    if not trace:
        raise typer.BadParameter(
            f"no traced run matching {root!r}; run with OTEL_EXPORTER=file (the default)"
        )
    roots = tree(trace)
    t0 = roots[0].start_ns
    for r in roots:
        run_id = next((c.attributes.get("llamaindex.run_id") for c in r.children if c.attributes), "")
        view = Tree(f"[bold]{r.name}[/]  {r.ms / 1000:.1f}s  run {run_id}")
        add(view, r, t0, show_all)
        console.print(view)
    steps = sorted({s.name.split(".")[-1] for s in trace if s.name.count(".") == 1 and "Workflow" in s.name})
    peaks = {step: peak_overlap(trace, "." + step) for step in steps}
    console.print("peak concurrency per step: " + ", ".join(f"{k} {v}" for k, v in peaks.items() if v))


if __name__ == "__main__":
    typer.run(main)
