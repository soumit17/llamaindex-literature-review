"""M7: what survives a server restart, with a store vs with a durable runtime (spec §13.5). $0.

For each runtime: start the server, start a 10-tick run, kill -9 the server after ~3 ticks, keep it down
until 32 s after the run started, start it again, and watch the same handler for 20 s.

Why the wait: on start, the default server resumes running handlers from their persisted ticks, but
skips handlers created less than 30 s earlier (a grace window, so that a just-started run isn't picked
up twice). DBOS recovers its own unfinished runs regardless.

    uv run python scripts/server_restart_demo.py
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import signal
import socket
import subprocess
import sys
import time

import httpx
from llama_agents.client import WorkflowClient
from rich.console import Console
from rich.table import Table

from litreview.config import PROJECT_ROOT, get_settings

console = Console()


def free_port() -> int:
    """Any port nobody is listening on (other local projects may be using fixed ones)."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


PORT = free_port()


def start_server(env: dict[str, str], log) -> subprocess.Popen:
    proc = subprocess.Popen(
        [sys.executable, "-m", "llama_agents.server", "scripts/restart_demo_server.py"],
        cwd=PROJECT_ROOT,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    for _ in range(100):  # wait for /health
        try:
            if httpx.get(f"http://127.0.0.1:{PORT}/health", timeout=0.5).status_code == 200:
                return proc
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    raise RuntimeError("server did not start")


async def ticks_seen(client: WorkflowClient, handler_id: str, seconds: float) -> list[int]:
    seen: list[int] = []

    async def read() -> None:
        async for env in client.get_workflow_events(handler_id):
            if env.type == "Tick":
                seen.append(env.value["n"])

    with contextlib.suppress(asyncio.TimeoutError):
        await asyncio.wait_for(read(), timeout=seconds)
    return seen


async def trial(runtime: str, down_until: float) -> dict:
    root = get_settings().p2_runs_dir / "restart-demo" / runtime
    shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True)
    env = {
        **os.environ,
        "P2_RUNTIME": runtime,
        "P2_RUNS_DIR": str(root),
        "WORKFLOWS_PY_SERVER_HOST": "127.0.0.1",
        "WORKFLOWS_PY_SERVER_PORT": str(PORT),
    }
    client = WorkflowClient(base_url=f"http://127.0.0.1:{PORT}")
    with (root / "server.log").open("w") as log:
        server = start_server(env, log)
        handler = await client.run_workflow_nowait("countdown", start_event={})
        started = time.monotonic()
        before = await ticks_seen(client, handler.handler_id, 3.5)
        server.send_signal(signal.SIGKILL)
        server.wait()
        await asyncio.sleep(max(0.0, down_until - (time.monotonic() - started)))
        server = start_server(env, log)
        after = await ticks_seen(client, handler.handler_id, 20)
        final = await client.get_handler(handler.handler_id)
        server.send_signal(signal.SIGTERM)
        server.wait()
    return {
        "runtime": runtime,
        "restart": f"{down_until:.0f}s after start" if down_until else "immediately",
        "ticks before kill": max(before, default=0),
        "ticks after restart": sorted(set(after) - set(before)),
        "status": final.status,
        "result": final.result.value if final.result else None,
    }


def main() -> None:
    # Restart immediately (inside the default server's 30 s resume grace), then after an outage.
    rows = [asyncio.run(trial(rt, wait)) for wait in (0.0, 32.0) for rt in ("default", "dbos")]
    table = Table(title="Server killed mid-run, then restarted")
    for col in (
        "runtime",
        "restart",
        "ticks before kill",
        "new ticks after restart",
        "handler status",
        "result",
    ):
        table.add_column(col)
    for r in rows:
        table.add_row(
            "SqliteWorkflowStore" if r["runtime"] == "default" else "DBOS runtime",
            r["restart"],
            str(r["ticks before kill"]),
            str(r["ticks after restart"]),
            r["status"],
            str(r["result"]),
        )
    console.print(table)


if __name__ == "__main__":
    main()
