"""M5 crash test (spec §12.1): kill -9 a real `litreview ingest` mid-run, restart it, check the result.

Runs in an isolated copy under runs/crash-test/ (its own data dir, ledger and checkpoint), so your
real index is never touched. The PDFs are symlinked, and the embedding cache is copied, so the run is
mostly summaries: 25 live Haiku calls (~$0.02), which is what "no re-spend" is about. Afterwards the
crash test's ledger rows are appended to runs/costs.jsonl so `litreview cost` stays honest.

    uv run python scripts/crash_ingest.py               # kill after 12 summaries
    uv run python scripts/crash_ingest.py --kill-after 5
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from litreview.config import PROJECT_ROOT, get_settings
from litreview.corpus import CorpusLock

SUMMARIZE_WORKERS = 3  # num_workers of summarize_paper: the most that can be mid-call when killed
console = Console()


def ingest(env: dict[str, str], log: Path) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-m", "litreview.cli", "ingest"],
        env=env,
        stdout=log.open("w"),
        stderr=subprocess.STDOUT,
        cwd=PROJECT_ROOT,
    )


def main(kill_after: int = typer.Option(12, help="SIGKILL once this many summaries exist.")) -> None:
    real = get_settings()
    if not real.anthropic_api_key:
        raise typer.BadParameter("ANTHROPIC_API_KEY is not set; the crash test makes ~25 Haiku calls")
    docstore_path = real.p2_data_dir / "storage" / "docstore.json"
    if docstore_path.exists() and any(
        "/" not in k for k in json.loads(docstore_path.read_text())["docstore/data"]
    ):
        raise typer.BadParameter(
            "your index predates deterministic chunk ids (M5); migrate once first: "
            "rm -rf data/cache/ingestion && uv run litreview ingest --rebuild"
        )
    root = real.p2_runs_dir / "crash-test"
    data, runs = root / "data", root / "runs"
    shutil.rmtree(root, ignore_errors=True)
    (data / "cache").mkdir(parents=True)
    runs.mkdir(parents=True)
    for name in ("corpus.lock.json", "papers.json"):
        shutil.copy(real.p2_data_dir / name, data / name)
    (data / "pdfs").symlink_to((real.p2_data_dir / "pdfs").resolve())
    if (real.p2_data_dir / "cache" / "ingestion").exists():
        shutil.copytree(real.p2_data_dir / "cache" / "ingestion", data / "cache" / "ingestion")
    env = {**os.environ, "P2_DATA_DIR": str(data), "P2_RUNS_DIR": str(runs)}
    lock = CorpusLock.load(data / "corpus.lock.json")
    assert lock is not None
    total = len(lock.papers)
    summaries = data / "summaries"
    checkpoint = runs / "checkpoints" / "ingest.json"

    console.print(f"[cyan]run 1[/]: ingest {total} papers, SIGKILL after {kill_after} summaries")
    first = ingest(env, root / "run1.log")
    while first.poll() is None and len(list(summaries.glob("*.json"))) < kill_after:
        time.sleep(0.2)
    if first.poll() is not None:
        raise SystemExit(f"run 1 ended before the kill (exit {first.returncode}); see {root / 'run1.log'}")
    os.kill(first.pid, signal.SIGKILL)
    first.wait()
    at_kill = len(list(summaries.glob("*.json")))
    console.print(f"  killed with {at_kill} summaries on disk; checkpoint exists: {checkpoint.exists()}")

    console.print("[cyan]run 2[/]: same command again")
    second = ingest(env, root / "run2.log")
    second.wait()
    log2 = (root / "run2.log").read_text()

    ledger = [json.loads(line) for line in (runs / "costs.jsonl").read_text().splitlines() if line]
    docstore = json.loads((data / "storage" / "docstore.json").read_text())["docstore/data"]
    chunks = [(d["__data__"]["metadata"]["arxiv_id"], d["__data__"]["text"]) for d in docstore.values()]
    repeats = len(ledger) - total
    checks = [
        ("run 2 exited cleanly", second.returncode == 0, f"exit {second.returncode}"),
        ("run 2 resumed from the checkpoint", "resuming from checkpoint" in log2, ""),
        (
            "every paper indexed",
            {a for a, _ in chunks} == {p.arxiv_id for p in lock.papers},
            f"{len(chunks)} chunks",
        ),
        ("every paper summarized", len(list(summaries.glob("*.json"))) == total, ""),
        ("no duplicate chunks", len(chunks) == len(set(chunks)), f"{len(chunks) - len(set(chunks))} dups"),
        (
            f"no re-spend beyond in-flight (<= {SUMMARIZE_WORKERS})",
            0 <= repeats <= SUMMARIZE_WORKERS,
            f"{len(ledger)} LLM calls for {total} papers",
        ),
        ("checkpoint removed after success", not checkpoint.exists(), ""),
    ]
    table = Table(title="Crash test")
    for col in ("check", "result", "detail"):
        table.add_column(col)
    for name, ok, detail in checks:
        table.add_row(name, "[green]pass[/]" if ok else "[red]FAIL[/]", detail)
    console.print(table)

    spent = sum(r["cost_usd"] for r in ledger)
    with (real.p2_runs_dir / "costs.jsonl").open("a") as f:  # keep the project total honest
        for row in ledger:
            f.write(json.dumps({**row, "step": "crash_test"}) + "\n")
    console.print(f"cost ${spent:.4f} (added to runs/costs.jsonl). Logs and data kept in {root}")
    raise typer.Exit(0 if all(ok for _, ok, _ in checks) else 1)


if __name__ == "__main__":
    typer.run(main)
