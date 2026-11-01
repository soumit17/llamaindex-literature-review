"""M5: human-in-the-loop callers. Pattern A (interactive) and pattern B (detach, restore elsewhere)."""

import io
import json
import subprocess
import sys
from pathlib import Path

import pytest
from rich.console import Console

from litreview.config import PROJECT_ROOT, get_settings
from litreview.events import (
    Clarified,
    NeedsClarification,
    OutlineApprovalRequired,
    OutlineDecision,
    ReviewRequest,
)
from litreview.hitl import (
    Detached,
    PendingStore,
    auto_responder,
    detach_responder,
    drive,
    interactive_responder,
    outline_to_yaml,
)
from litreview.models import Outline, OutlineSection
from tests.review_env import review_workflow, run_review, scripted

OUTLINE = Outline(
    title="T",
    sections=[
        OutlineSection(heading="Intro", points=["p"], finding_ids=[]),
        OutlineSection(heading="Body", points=["q"], finding_ids=[1]),
    ],
)
PROMPT = OutlineApprovalRequired(outline=OUTLINE, attempt=1)


def scripted_ask(*answers: str):
    queue = list(answers)

    def ask(question: str, **kwargs) -> str:
        return queue.pop(0)

    return ask


def quiet_console() -> Console:
    return Console(file=io.StringIO())


# ---------- pattern A ----------
async def test_interactive_approve_and_reject():
    approve = interactive_responder(quiet_console(), ask=scripted_ask("a"))
    assert await approve(PROMPT) == OutlineDecision(action="approve")
    reject = interactive_responder(quiet_console(), ask=scripted_ask("r", "more on failure handling"))
    assert await reject(PROMPT) == OutlineDecision(action="reject", feedback="more on failure handling")


async def test_interactive_edit_retries_until_the_yaml_validates():
    edits = iter(["title: [not, valid", outline_to_yaml(OUTLINE).replace("title: T", "title: Mine")])
    respond = interactive_responder(
        quiet_console(), ask=scripted_ask("e", "e"), edit=lambda text: next(edits)
    )
    decision = await respond(PROMPT)
    assert decision.action == "edit" and decision.edited_outline.title == "Mine"


async def test_outline_yaml_round_trips():
    import yaml

    assert Outline.model_validate(yaml.safe_load(outline_to_yaml(OUTLINE))) == OUTLINE


@pytest.mark.parametrize(
    ("typed", "expected"), [("2", "Sharper B?"), ("My own question?", "My own question?")]
)
async def test_interactive_clarification(typed, expected):
    respond = interactive_responder(quiet_console(), ask=scripted_ask(typed))
    ev = NeedsClarification(question="AI?", reason="vague", suggestions=["Sharper A?", "Sharper B?"])
    assert await respond(ev) == Clarified(refined_question=expected)


async def test_interactive_responder_drives_a_real_run(ingested):
    respond = interactive_responder(quiet_console(), ask=scripted_ask("r", "different angle", "a"))
    result, _, handler = await run_review(scripted(), respond=respond)
    assert result.error is None
    assert (await handler.ctx.store.get_state()).replan_feedback == ["different angle"]


# ---------- pattern B ----------
async def test_detach_writes_a_restorable_snapshot_and_stops_the_run(ingested, tmp_path):
    store = PendingStore(tmp_path / "pending")
    wf = await review_workflow(scripted())
    handler = wf.run(start_event=ReviewRequest(question="How do agent teams coordinate?"))
    detached = await drive(
        handler, detach_responder, pending=(store, "run-1", "How do agent teams coordinate?")
    )

    assert isinstance(detached, Detached) and detached.run_id == "run-1"
    [saved] = store.list()
    assert isinstance(saved.waiting_for, OutlineApprovalRequired)
    assert saved.waiting_for.outline.title == "Coordination Topologies"
    assert handler.is_done()  # cancelled: nothing keeps waiting in this process
    assert not (get_settings().p2_out_dir).exists() or not list(get_settings().p2_out_dir.rglob("review.md"))


async def test_detached_run_finishes_in_another_process_with_the_same_result(ingested, tmp_path):
    question = "How do agent teams coordinate?"
    uninterrupted, _, _ = await run_review(scripted(), question=question)
    expected = Path(uninterrupted.markdown_path).read_text()
    Path(uninterrupted.markdown_path).unlink()

    store = PendingStore(tmp_path / "pending")
    wf = await review_workflow(scripted())
    handler = wf.run(start_event=ReviewRequest(question=question))
    detached = await drive(handler, detach_responder, pending=(store, "run-2", question))
    assert isinstance(detached, Detached)

    child = subprocess.run(  # a new Python process: nothing in memory survives, only the snapshot file
        [sys.executable, "-m", "tests.restore_child", str(store.directory), "run-2"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert child.returncode == 0, child.stderr[-2000:]
    out = json.loads(child.stdout.strip().splitlines()[-1])

    assert out["error"] is None
    assert Path(out["markdown_path"]).read_text() == expected  # same review as without the hand-off
    # Completed steps were not re-run after the restore: only writing and checking happened there.
    assert out["calls"]["[SCOPE]"] == out["calls"]["[PLAN]"] == out["calls"]["[RESEARCH]"] == 0
    assert out["calls"]["[OUTLINE]"] == 0 and out["calls"]["[WRITE]"] == 4
    assert store.list() == []  # the pending file is removed once the run completes


async def test_auto_responder_needs_no_human():
    assert await auto_responder(PROMPT) == OutlineDecision(action="approve")
