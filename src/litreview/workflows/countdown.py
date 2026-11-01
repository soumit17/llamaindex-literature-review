"""A tiny LLM-free workflow for the server restart demo (scripts/server_restart_demo.py) and DBOS tests.

It lives in the package, not in the demo's server file, because the DBOS runtime pickles events and
pickle can only find classes in importable modules (the server launcher loads its file under a name
pickle can't import).
"""

import asyncio

from workflows import Context, Workflow, step
from workflows.events import Event, StartEvent, StopEvent


class CountdownStart(StartEvent):
    ticks: int = 10
    delay: float = 1.0  # seconds per tick


class Tick(Event):
    n: int
    total: int
    delay: float


class Countdown(Workflow):
    @step
    async def begin(self, ev: CountdownStart) -> Tick:
        return Tick(n=0, total=ev.ticks, delay=ev.delay)

    @step
    async def tick(self, ctx: Context, ev: Tick) -> Tick | StopEvent:
        await asyncio.sleep(ev.delay)
        nxt = ev.model_copy(update={"n": ev.n + 1})
        ctx.write_event_to_stream(nxt)
        return StopEvent(result={"ticks": nxt.n}) if nxt.n >= ev.total else nxt
