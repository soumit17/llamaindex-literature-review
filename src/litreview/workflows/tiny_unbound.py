"""Unbound-function workflow: steps are plain module-level functions attached with
`@step(workflow=TinyWorkflow)` instead of methods. No `self`, and the class body stays empty.

Compare with hello.py: same routing-by-type, but steps can live in different modules and be
attached to a workflow class from outside it.
"""

from workflows import Workflow, step
from workflows.events import Event, StartEvent, StopEvent


class Shout(StartEvent):
    text: str


class Shouted(Event):
    text: str


class TinyWorkflow(Workflow):
    pass


@step(workflow=TinyWorkflow)
async def shout(ev: Shout) -> Shouted:
    return Shouted(text=ev.text.upper())


@step(workflow=TinyWorkflow)
async def exclaim(ev: Shouted) -> StopEvent:
    return StopEvent(result=ev.text + "!")  # plain StopEvent: `await handler` returns .result
