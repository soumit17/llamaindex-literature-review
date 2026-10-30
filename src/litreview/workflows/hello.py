"""M0 hello workflow: custom start/stop events, a branch, a loop, streaming, typed state.
Flow: Greet -start-> Greeted (empty name) | Tick -tick-> Tick ... -> Done -finish-> Greeted
"""

from pydantic import BaseModel
from workflows import Context, Workflow, step
from workflows.events import Event, StartEvent, StopEvent


class Greet(StartEvent):  # custom StartEvent: typed fields instead of a loose dict
    name: str
    rounds: int = 3


class Greeted(StopEvent):  # custom StopEvent: `await handler` returns this instance itself
    message: str
    rounds_done: int


class Tick(Event):  # returning Tick from the step that consumes Tick is what makes the loop
    n: int


class Done(Event):
    pass


class Progress(Event):  # never consumed by a step; only written to the caller's stream
    message: str


class HelloState(BaseModel):  # typed state: every field needs a default
    name: str = ""
    rounds: int = 0
    rounds_done: int = 0


class HelloWorkflow(Workflow):
    @step
    async def start(self, ctx: Context[HelloState], ev: Greet) -> Tick | Greeted:
        # Branch: the union return type declares both edges; the value returned picks one.
        if not ev.name.strip():
            return Greeted(message="Nobody to greet.", rounds_done=0)
        async with ctx.store.edit_state() as state:
            state.name, state.rounds = ev.name, ev.rounds
        return Tick(n=0)

    @step
    async def tick(self, ctx: Context[HelloState], ev: Tick) -> Tick | Done:
        async with ctx.store.edit_state() as state:  # atomic read-modify-write on typed state
            state.rounds_done += 1
            rounds = state.rounds
        ctx.write_event_to_stream(Progress(message=f"round {ev.n + 1}/{rounds}"))
        return Tick(n=ev.n + 1) if ev.n + 1 < rounds else Done()

    @step
    async def finish(self, ctx: Context[HelloState], ev: Done) -> Greeted:
        state = await ctx.store.get_state()
        return Greeted(message=f"Hello {state.name}!", rounds_done=state.rounds_done)
