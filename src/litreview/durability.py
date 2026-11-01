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
