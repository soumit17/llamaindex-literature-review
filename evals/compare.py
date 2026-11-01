"""Regression gate (spec §17.5): current eval reports vs evals/baseline.json.

Collects one number per metric (0-100 scale) from the latest reports, and fails (exit 1) if any metric
drops more than 3 points below the baseline. Lower-is-better metrics are stored negated.

    uv run python -m evals.compare           # compare; exit 1 on a regression
    uv run python -m evals.compare --save    # make the current numbers the baseline
"""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from litreview.config import PROJECT_ROOT

REPORTS = PROJECT_ROOT / "evals" / "reports"
BASELINE = PROJECT_ROOT / "evals" / "baseline.json"
TOLERANCE = 3.0  # points
console = Console()


def current_metrics(reports: Path = REPORTS) -> dict[str, float]:
    m: dict[str, float] = {}
    retrieval = reports / "retrieval.json"
    if retrieval.exists():
        rows = json.loads(retrieval.read_text())
        best = max(rows, key=lambda r: (r["hit_rate"], r["mrr"]))
        m["retrieval.hit_rate_at_5"] = round(100 * best["hit_rate"], 1)
        m["retrieval.mrr"] = round(100 * best["mrr"], 1)
    citations = reports / "citations.json"
    if citations.exists():
        c = json.loads(citations.read_text())["metrics"]
        m["citations.supported_lenient"] = c["supported_lenient_pct"]
        m["citations.supported_strict"] = c["supported_strict_pct"]
        m["citations.neg_unknown_nodes"] = -c["unknown_node_pct"]  # higher is better after negating
    quality = reports / "quality.json"
    if quality.exists():
        m["quality.judge_mean"] = json.loads(quality.read_text())["mean_pct"]
    return m


def regressions(
    current: dict[str, float], baseline: dict[str, float], tolerance: float = TOLERANCE
) -> list[str]:
    return [
        f"{k}: {baseline[k]} -> {current[k]} ({current[k] - baseline[k]:+.1f})"
        for k in baseline
        if k in current and current[k] < baseline[k] - tolerance
    ]


def main(
    save: bool = typer.Option(False, "--save", help="Store the current metrics as the baseline."),
) -> None:
    current = current_metrics()
    if not current:
        raise typer.BadParameter("no eval reports in evals/reports/; run the evals first")
    if save:
        BASELINE.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n")
        console.print(f"baseline saved: {BASELINE}")
        return
    if not BASELINE.exists():
        raise typer.BadParameter("no evals/baseline.json; run with --save first")
    baseline = json.loads(BASELINE.read_text())
    table = Table(title=f"Evals vs baseline (fail below -{TOLERANCE:g} points)")
    for col in ("metric", "baseline", "now", "change"):
        table.add_column(col)
    for k in sorted(set(baseline) | set(current)):
        b, c = baseline.get(k), current.get(k)
        change = f"{c - b:+.1f}" if b is not None and c is not None else "n/a"
        table.add_row(k, str(b), str(c), change)
    console.print(table)
    failed = regressions(current, baseline)
    if failed:
        console.print("[red]regression:[/] " + "; ".join(failed))
        raise typer.Exit(1)
    console.print("[green]no regression[/]")


if __name__ == "__main__":
    typer.run(main)
