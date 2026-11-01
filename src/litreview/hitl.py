"""The caller side of human-in-the-loop (spec §10).

A step returns an `InputRequiredEvent` subclass; the runtime puts it on the stream and the run waits.
The caller (this module) sees it, decides an answer and sends a `HumanResponseEvent` subclass back with
`handler.send_event(...)`; the step that accepts that type continues the run. The workflow never
knows who answered, or when, or from which process.

Pattern A (`interactive_responder`): answer in this terminal while the run waits.
Pattern B (`DETACH`, `PendingStore`, `resume_pending`): snapshot the run's Context to disk, cancel it,
and continue later, from any process, by restoring the snapshot and sending the answer.
Automatic (`auto_responder`): accept what the workflow proposes (scripts, `--yes`).
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import tempfile
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError
from rich.console import Console
from rich.prompt import Prompt
from workflows import Context, Workflow
from workflows.events import Event, InputRequiredEvent
from workflows.handler import WorkflowHandler

from litreview.events import Clarified, NeedsClarification, OutlineApprovalRequired, OutlineDecision
from litreview.models import Outline

DETACH = object()  # a responder returns this to hand the run off instead of answering
Responder = Callable[[InputRequiredEvent], Awaitable[Any]]  # -> Event | None | DETACH
PROMPT_TYPES: dict[str, type[InputRequiredEvent]] = {
    "NeedsClarification": NeedsClarification,
    "OutlineApprovalRequired": OutlineApprovalRequired,
}


# ---------- automatic ----------
async def auto_responder(ev: InputRequiredEvent) -> Event | None:
    """Accept whatever the workflow proposes: the first suggested rewording, the first outline."""
    if isinstance(ev, NeedsClarification):
        return Clarified(refined_question=ev.suggestions[0] if ev.suggestions else ev.question)
    if isinstance(ev, OutlineApprovalRequired):
        return OutlineDecision(action="approve")
    return None


async def detach_responder(ev: InputRequiredEvent) -> Any:
    return DETACH


# ---------- pattern A: interactive ----------
Ask = Callable[..., str]  # rich.prompt.Prompt.ask's shape; tests pass a scripted one
EditText = Callable[[str], str]


def edit_in_editor(text: str) -> str:
    """Open $VISUAL / $EDITOR (else nano or vi) on `text`; return what was saved."""
    editor = os.environ.get("VISUAL") or os.environ.get("EDITOR") or shutil.which("nano") or "vi"
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        f.write(text)
        path = f.name
    try:
        subprocess.run([*editor.split(), path], check=True)
        return Path(path).read_text()
    finally:
        os.unlink(path)


def outline_to_yaml(outline: Outline) -> str:
    header = "# Edit the outline, save and close. Keys: title, sections[heading, points, finding_ids].\n"
    return header + yaml.safe_dump(outline.model_dump(), sort_keys=False, allow_unicode=True, width=100)


def show_outline(console: Console, ev: OutlineApprovalRequired) -> None:
    console.rule(f"Proposed outline (attempt {ev.attempt})")
    console.print(f"[bold]{ev.outline.title}[/]")
    for i, s in enumerate(ev.outline.sections, start=1):
        findings = f" [dim](findings {', '.join(map(str, s.finding_ids))})[/]" if s.finding_ids else ""
        console.print(f"{i}. {s.heading}{findings}")
        for point in s.points:
            console.print(f"     - {point}", style="dim")


def interactive_responder(
    console: Console, ask: Ask = Prompt.ask, edit: EditText = edit_in_editor
) -> Responder:
    async def respond(ev: InputRequiredEvent) -> Event | None:
        # Blocking prompts run in a thread so the event loop (and the waiting run) stays responsive.
        def run(fn, *args, **kwargs):
            return asyncio.to_thread(fn, *args, **kwargs)

        if isinstance(ev, NeedsClarification):
            console.rule("The question is too vague to plan")
            console.print(f"{ev.question}\n[dim]{ev.reason}[/]")
            for i, s in enumerate(ev.suggestions, start=1):
                console.print(f"  {i}. {s}")
            answer = await run(ask, "Pick a number, or type your own question", default="1")
            if answer.isdigit() and 1 <= int(answer) <= len(ev.suggestions):
                answer = ev.suggestions[int(answer) - 1]
            return Clarified(refined_question=answer)

        if isinstance(ev, OutlineApprovalRequired):
            show_outline(console, ev)
            while True:
                choice = await run(ask, "[a]pprove  [e]dit  [r]eject", choices=["a", "e", "r"], default="a")
                if choice == "a":
                    return OutlineDecision(action="approve")
                if choice == "r":
                    feedback = await run(ask, "What should change? (fed back into planning)")
                    return OutlineDecision(action="reject", feedback=feedback)
                text = await run(edit, outline_to_yaml(ev.outline))
                try:
                    edited = Outline.model_validate(yaml.safe_load(text))
                except (ValidationError, yaml.YAMLError, TypeError) as e:
                    console.print(f"[red]That outline doesn't validate:[/] {e}")
                    continue
                return OutlineDecision(action="edit", edited_outline=edited)
        return None

    return respond


# ---------- pattern B: detach, store, resume ----------
@dataclass
class PendingRun:
    run_id: str
    created: str
    question: str
    waiting_for: InputRequiredEvent
    ctx: dict[str, Any]


@dataclass
class Detached:
    run_id: str
    path: Path
    waiting_for: InputRequiredEvent


class PendingStore:
    """runs/pending/<run_id>.json: the snapshot plus what the run is waiting for."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def path(self, run_id: str) -> Path:
        return self.directory / f"{run_id}.json"

    def save(self, run_id: str, ctx: Context[Any], waiting_for: InputRequiredEvent, question: str) -> Path:
        record = {
            "run_id": run_id,
            "created": datetime.now(UTC).isoformat(timespec="seconds"),
            "question": question,
            "waiting_for": {"type": type(waiting_for).__name__, "data": waiting_for.model_dump(mode="json")},
            "ctx": ctx.to_dict(),  # everything the run needs, as JSON; fails loudly if anything isn't
        }
        path = self.path(run_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(record))
        tmp.replace(path)
        return path

    def load(self, run_id: str) -> PendingRun:
        path = self.path(run_id)
        if not path.exists():
            raise FileNotFoundError(f"no pending run {run_id!r} in {self.directory}")
        r = json.loads(path.read_text())
        prompt_cls = PROMPT_TYPES[r["waiting_for"]["type"]]
        return PendingRun(
            run_id=r["run_id"],
            created=r["created"],
            question=r["question"],
            waiting_for=prompt_cls.model_validate(r["waiting_for"]["data"]),
            ctx=r["ctx"],
        )

    def list(self) -> list[PendingRun]:
        return [self.load(p.stem) for p in sorted(self.directory.glob("*.json"))]

    def delete(self, run_id: str) -> None:
        self.path(run_id).unlink(missing_ok=True)


def new_run_id() -> str:
    return datetime.now(UTC).strftime("%m%d-%H%M%S-") + uuid.uuid4().hex[:4]


# ---------- driving a run ----------
async def drive(
    handler: WorkflowHandler,
    respond: Responder,
    on_event: Callable[[Event], None] = lambda ev: None,
    expose_internal: bool = False,
    pending: tuple[PendingStore, str, str] | None = None,  # (store, run_id, question) for DETACH
):
    """Read the run's stream (exactly one reader per run), answer every InputRequiredEvent, and return
    the run's result, or `Detached` if the responder handed the run off."""
    async for ev in handler.stream_events(expose_internal=expose_internal):
        on_event(ev)
        if not isinstance(ev, InputRequiredEvent):
            continue
        answer = await respond(ev)
        if answer is DETACH:
            if pending is None:
                raise ValueError("a responder detached, but drive() got no PendingStore")
            store, run_id, question = pending
            path = store.save(run_id, handler.ctx, ev, question)
            # Cancel the in-memory run: the answer will go to a restored copy, not to this one.
            await handler.cancel_run()
            return Detached(run_id=run_id, path=path, waiting_for=ev)
        if answer is not None:
            await handler.send_event(answer)
    return await handler


async def resume_pending(
    store: PendingStore,
    run_id: str,
    workflow: Workflow,
    answer: Event,
    respond: Responder,
    on_event: Callable[[Event], None] = lambda ev: None,
    expose_internal: bool = False,
    on_start: Callable[[WorkflowHandler], None] = lambda handler: None,
):
    """Restore a detached run into `workflow`, send the human's answer, and drive it on. A later prompt
    goes to `respond` again (DETACH re-saves under the same run_id). The pending file is removed when
    the run finishes."""
    pending = store.load(run_id)
    ctx = Context.from_dict(workflow, pending.ctx)
    handler = workflow.run(ctx=ctx)  # no start event: the run continues where the snapshot left it
    on_start(handler)
    await handler.send_event(answer)
    result = await drive(handler, respond, on_event, expose_internal, (store, run_id, pending.question))
    if not isinstance(result, Detached):
        store.delete(run_id)
    return result
