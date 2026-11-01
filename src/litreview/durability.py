"""Durability level 1: the checkpoint loop (spec §12.1).

There is no built-in checkpointer. While a run streams, `StepStateChanged(NOT_RUNNING)` marks a step
finishing; at that moment `handler.ctx.to_dict()` is a consistent, resumable snapshot (events still
in flight + the state store + partial fan-in buffers). We write it to disk, at most every `every`
seconds. After a crash, `Context.from_dict(...)` + `run(ctx=...)` continues: completed steps don't
re-run; steps that were mid-flight re-run from the top (at-least-once), which is why every ingestion
step is idempotent.

What a snapshot does NOT contain: Resources (index, embed model, LLM). They are rebuilt by their
factories on resume, from disk; `index_paper` persists the index before it finishes for that reason.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from workflows import Context, Workflow
from workflows.events import Event, StartEvent, StepState, StepStateChanged
from workflows.handler import WorkflowHandler


class Interrupted(RuntimeError):
    """Raised by run_checkpointed when `stop_after` asked it to stop early."""


def save_snapshot(path: Path, ctx: Context[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(ctx.to_dict()))  # to_dict fails as a whole if anything isn't JSON
    os.replace(tmp, path)


def load_snapshot(path: Path, workflow: Workflow) -> Context[Any] | None:
    return Context.from_dict(workflow, json.loads(path.read_text())) if path.exists() else None


async def run_checkpointed(
    workflow: Workflow,
    start_event: StartEvent,
    checkpoint: Path,
    steps: set[str],
    on_event: Callable[[Event], None] = lambda ev: None,
    on_resume: Callable[[], None] = lambda: None,
    on_start: Callable[[WorkflowHandler], None] = lambda handler: None,
    every: float = 2.0,
    expose_internal: bool = False,
    stop_after: Callable[[Event], bool] | None = None,
):
    """Run `workflow`, snapshotting to `checkpoint` whenever one of `steps` finishes (throttled).

    If `checkpoint` exists, resume from it instead and DON'T send `start_event`: the pending work is
    already inside the snapshot. The checkpoint is deleted once the run completes.

    `stop_after` simulates a crash for tests: when it returns True for an event, the run is cancelled
    right there (no extra snapshot) and `Interrupted` is raised.
    """
    ctx = load_snapshot(checkpoint, workflow)
    if ctx is not None:
        on_resume()
        handler = workflow.run(ctx=ctx)
    else:
        handler = workflow.run(start_event=start_event)
    on_start(handler)
    last = 0.0
    async for ev in handler.stream_events(expose_internal=True):  # internal events drive the loop
        if (
            isinstance(ev, StepStateChanged)
            and ev.step_state == StepState.NOT_RUNNING
            and ev.name in steps
            and time.monotonic() - last >= every
        ):
            save_snapshot(checkpoint, handler.ctx)
            last = time.monotonic()
        if expose_internal or not isinstance(ev, StepStateChanged):
            on_event(ev)
        if stop_after is not None and stop_after(ev):
            await handler.cancel_run()
            raise Interrupted(str(checkpoint))
    result = await handler
    checkpoint.unlink(missing_ok=True)
    return result


# ---------- durability level 2: the DBOS runtime (spec §12.2) ----------
# Same workflows, different runtime: DBOS journals every step transition to SQLite and, when a
# process restarts, replays the journal of its unfinished runs. There is no snapshot code here; what
# we keep is only the run id, so a restart asks DBOS for *the same* run.

_dbos_configured = False


def dbos_runtime():
    """Configure DBOS once per process (it is a process-wide singleton) and return a runtime."""
    global _dbos_configured
    from dbos import DBOS
    from llama_agents.dbos import DBOSRuntime

    from litreview.config import get_settings

    if not _dbos_configured:
        runs = get_settings().p2_runs_dir
        runs.mkdir(parents=True, exist_ok=True)
        DBOS(
            config={
                "name": "litreview",
                "run_admin_server": False,
                "system_database_url": f"sqlite:///{runs / 'dbos.sqlite'}",
            }
        )
        _dbos_configured = True
    return DBOSRuntime()


async def run_durable(
    build: Callable[[Any], Workflow],
    start_event: StartEvent,
    run_id_file: Path,
    on_event: Callable[[Event], None] = lambda ev: None,
    on_resume: Callable[[str], None] = lambda run_id: None,
):
    """Run `build(runtime)` on the DBOS runtime under a stable run id.

    DBOS keys runs by id: the same id after a crash resumes the unfinished run; the same id after a
    *finished* run just returns its stored result. So the id lives in `run_id_file` from start until
    success, and a fresh one is minted for the next run.
    """
    import uuid

    runtime = dbos_runtime()
    workflow = build(runtime)
    await runtime.launch()  # also re-launches unfinished runs this process (executor) owns
    try:
        if run_id_file.exists():
            run_id = run_id_file.read_text().strip()
            on_resume(run_id)
        else:
            run_id = f"run-{uuid.uuid4().hex[:12]}"
            run_id_file.parent.mkdir(parents=True, exist_ok=True)
            run_id_file.write_text(run_id)
        handler = workflow.run(start_event=start_event, run_id=run_id)
        async for ev in handler.stream_events():  # under DBOS this replays from the start on resume
            on_event(ev)
        result = await handler
        run_id_file.unlink(missing_ok=True)
        return result
    finally:
        await runtime.destroy()
