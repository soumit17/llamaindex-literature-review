"""The caller side of human-in-the-loop (spec §10, pattern A).

A step returns an `InputRequiredEvent` subclass; the runtime puts it on the stream and the run waits.
The caller (this module) sees it, decides an answer and sends a `HumanResponseEvent` subclass back with
`handler.send_event(...)`; the step that accepts that type continues the run. The workflow never
knows whether a person, a script or a web form answered.

M4 ships the automatic policy (`auto_responder`); M5 adds an interactive one and detached runs.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from workflows.events import Event, InputRequiredEvent
from workflows.handler import WorkflowHandler

from litreview.events import Clarified, NeedsClarification, OutlineApprovalRequired, OutlineDecision

Responder = Callable[[InputRequiredEvent], Awaitable[Event | None]]


async def auto_responder(ev: InputRequiredEvent) -> Event | None:
    """Accept whatever the workflow proposes: the first suggested rewording, the first outline."""
    if isinstance(ev, NeedsClarification):
        return Clarified(refined_question=ev.suggestions[0] if ev.suggestions else ev.question)
    if isinstance(ev, OutlineApprovalRequired):
        return OutlineDecision(action="approve")
    return None


async def drive(
    handler: WorkflowHandler,
    respond: Responder,
    on_event: Callable[[Event], None] = lambda ev: None,
    expose_internal: bool = False,
):
    """Read the run's stream (there is exactly one reader per run), answer every InputRequiredEvent,
    and return the run's result."""
    async for ev in handler.stream_events(expose_internal=expose_internal):
        on_event(ev)
        if isinstance(ev, InputRequiredEvent):
            answer = await respond(ev)
            if answer is not None:
                await handler.send_event(answer)
    return await handler
