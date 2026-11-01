"""M4: the review workflow end to end on the fixture corpus, with a scripted LLM ($0, no network)."""

import json
import re
from pathlib import Path
from typing import Any

import pytest
from workflows.events import Event, InputRequiredEvent, StepState, StepStateChanged

from litreview.events import (
    Clarified,
    NeedsClarification,
    OutlineApprovalRequired,
    OutlineDecision,
    ResearchProgress,
    ReviewReady,
    ReviewRequest,
    SectionToken,
)
from litreview.hitl import auto_responder, drive
from litreview.models import Outline, OutlineSection
from litreview.resources import get_embed_model, get_llm, get_reranker, get_writer_llm
from litreview.workflows.review import ReviewWorkflow
from tests.conftest import override_resources
from tests.fakes import CountingEmbedding, ScriptedLLM
from tests.test_engines import fake_reranker

SUBQUESTIONS = ["How do hubs route work?", "How do rings pass messages?", "When do trees help?"]
SCRIPT = {
    "[SCOPE]": json.dumps({"specific": True, "reason": "clear", "suggestions": []}),
    "[PLAN]": json.dumps(
        {
            "sub_questions": [{"text": q, "rationale": "r"} for q in SUBQUESTIONS],
            "scope_note": "Coordination topologies only.",
        }
    ),
    "[RESEARCH]": json.dumps(
        {
            "claims": [
                {"statement": "Orchestrators assign roles.", "excerpt": 1, "quote": "assigns roles"},
                {"statement": "Excerpt 9 does not exist.", "excerpt": 9, "quote": "x"},
            ],
            "gap": None,
        }
    ),
    "[OUTLINE]": json.dumps(
        {
            "title": "Coordination Topologies",
            "sections": [
                {"heading": "Introduction", "points": ["why"], "finding_ids": []},
                {"heading": "Hubs and Rings", "points": ["compare"], "finding_ids": [1, 2]},
                {"heading": "Trees", "points": ["when"], "finding_ids": [3, 99]},
                {"heading": "Conclusion", "points": ["wrap"], "finding_ids": []},
            ],
        }
    ),
    # Cites a claim of every finding plus an invented one; each section may only keep its own.
    "[WRITE]": "Agents coordinate through roles [1.1, 2.1]. Trees help depth [3.1]. Made up [9.9].",
}


def scripted(**kwargs: Any) -> ScriptedLLM:
    return ScriptedLLM(script={**SCRIPT, **kwargs.pop("script", {})}, **kwargs)


async def run_review(
    llm: ScriptedLLM, respond=auto_responder, question: str = "How do agent teams coordinate?", **request
):
    """Like `litreview review`: drive the run, answer HITL prompts, keep every streamed event."""
    manager = await override_resources(
        {
            get_embed_model: CountingEmbedding.make(),
            get_reranker: fake_reranker(),
            get_llm: llm,
            get_writer_llm: llm,
        }
    )
    wf = ReviewWorkflow(timeout=60, resource_manager=manager)
    events: list[Event] = []
    handler = wf.run(start_event=ReviewRequest(question=question, **request))
    result = await drive(handler, respond, on_event=events.append, expose_internal=True)
    return result, events, handler


def of_type(events: list[Event], cls: type) -> list[Any]:
    return [e for e in events if isinstance(e, cls)]


async def test_happy_path_writes_a_cited_review(ingested):
    llm = scripted()
    result, events, _ = await run_review(llm)

    assert isinstance(result, ReviewReady) and result.error is None
    md = Path(result.markdown_path).read_text()
    assert md.startswith("# Coordination Topologies")
    assert [h for h in re.findall(r"^## (.+)$", md, re.M)] == [
        "Introduction",
        "Hubs and Rings",
        "Trees",
        "Conclusion",
        "References",
    ]
    assert all(md[m.start() - 2 : m.start()] == "\n\n" for m in re.finditer(r"^## ", md, re.M))
    # Every [n] in the text has a reference line, and every reference traces to real chunks.
    numbers = {int(n) for group in re.findall(r"\[(\d+(?:, \d+)*)\]", md) for n in group.split(", ")}
    refs = json.loads((Path(result.markdown_path).parent / "citations.json").read_text())
    assert numbers == {r["n"] for r in refs} and len(refs) == result.n_citations > 0
    assert all(c["node_id"] for r in refs for c in r["claims"])
    assert "@misc{" in Path(result.bib_path).read_text()
    assert "[9.9]" not in md and result.unknown_markers > 0  # invented markers removed, counted


async def test_research_keeps_only_claims_about_shown_excerpts(ingested):
    result, _, _ = await run_review(scripted())
    # Finding events go step to step, not to the stream; check what reached the citations instead.
    refs = json.loads((Path(result.markdown_path).parent / "citations.json").read_text())
    statements = {c["statement"] for r in refs for c in r["claims"]}
    assert statements == {"Orchestrators assign roles."}  # the excerpt-9 claim was dropped


async def test_section_tokens_are_streamed(ingested):
    _, events, _ = await run_review(scripted())
    tokens = of_type(events, SectionToken)
    assert {t.section_idx for t in tokens} == {0, 1, 2, 3}
    assert len(tokens) > 8  # many deltas, not one blob


async def test_progress_subclasses_reach_log_progress(ingested):
    result, events, _ = await run_review(scripted())
    # log_progress re-streams what it consumed, so subclass instances prove the subclass routing.
    assert len(of_type(events, ResearchProgress)) == 2 * len(SUBQUESTIONS)  # researching + done
    log = (Path(result.markdown_path).parent / "log.txt").read_text()
    assert "ResearchProgress" in log and "WriteProgress" in log and "[plan] Progress" in log


async def test_research_runs_at_most_four_at_once(ingested):
    many = {
        "sub_questions": [{"text": f"Question {i}?", "rationale": "r"} for i in range(6)],
        "scope_note": "s",
    }
    _, events, _ = await run_review(scripted(script={"[PLAN]": json.dumps(many)}), max_subquestions=6)
    running, peak = set(), 0
    for e in of_type(events, StepStateChanged):
        if e.name == "research":
            if e.step_state == StepState.RUNNING:
                running.add(e.worker_id)
            elif e.step_state == StepState.NOT_RUNNING:
                running.discard(e.worker_id)
            peak = max(peak, len(running))
    assert peak == 4


async def test_vague_question_asks_for_clarification_then_continues(ingested):
    vague = json.dumps({"specific": False, "reason": "too broad", "suggestions": ["How do hubs coordinate?"]})
    asked: list[InputRequiredEvent] = []

    async def respond(ev):
        asked.append(ev)
        return await auto_responder(ev)

    result, _, handler = await run_review(
        scripted(script={"[SCOPE]": vague}), respond=respond, question="AI?"
    )
    assert isinstance(asked[0], NeedsClarification) and asked[0].suggestions == ["How do hubs coordinate?"]
    assert isinstance(asked[1], OutlineApprovalRequired)
    assert result.error is None
    state = await handler.ctx.store.get_state()
    assert state.question == "How do hubs coordinate?"  # plan used the clarified question


async def test_failed_subquestion_is_recovered_and_reported(ingested):
    llm = scripted(fail_always={"rings pass messages": "provider exploded"})
    result, events, _ = await run_review(llm)

    assert result.error is None and result.failed_subquestions == ["How do rings pass messages?"]
    assert any(e.status == "failed" for e in of_type(events, ResearchProgress))
    assert (
        "Not covered (research failed): How do rings pass messages?" in Path(result.markdown_path).read_text()
    )


async def test_bad_structured_output_is_retried_with_a_fix_note(ingested):
    llm = scripted(fail_times={"[OUTLINE]": 1})
    result, _, _ = await run_review(llm)

    assert result.error is None
    outline_prompts = [p for p in llm.calls if "[OUTLINE]" in p]
    assert len(outline_prompts) == 2
    assert "previous answer was rejected" in outline_prompts[1]


async def test_wildcard_catch_error_writes_partial_output(ingested):
    result, _, _ = await run_review(scripted(fail_always={"[OUTLINE]": "outline service down"}))

    assert result.error and "draft_outline" in result.error
    assert Path(result.markdown_path).name == "partial.md"
    assert "Orchestrators assign roles." in Path(result.markdown_path).read_text()


async def test_reject_loops_back_to_plan_at_most_three_times(ingested):
    seen: list[OutlineApprovalRequired] = []

    async def always_reject(ev):
        if isinstance(ev, OutlineApprovalRequired):
            seen.append(ev)
            return OutlineDecision(action="reject", feedback=f"try again {ev.attempt}")
        return await auto_responder(ev)

    llm = scripted()
    result, _, handler = await run_review(llm, respond=always_reject)

    assert [e.attempt for e in seen] == [1, 2, 3]  # the 3rd rejection is overruled
    assert result.error is None
    plan_prompts = [p for p in llm.calls if "[PLAN]" in p]
    assert len(plan_prompts) == 3 and "try again 1" in plan_prompts[1] and "try again 2" in plan_prompts[2]


async def test_edited_outline_is_what_gets_written(ingested):
    edited = Outline(
        title="My Own Title",
        sections=[
            OutlineSection(heading="Only Hubs", points=["p"], finding_ids=[1]),
            OutlineSection(heading="Wrap-up", points=["p"], finding_ids=[]),
        ],
    )

    async def edit(ev):
        if isinstance(ev, OutlineApprovalRequired):
            return OutlineDecision(action="edit", edited_outline=edited)
        return await auto_responder(ev)

    result, _, _ = await run_review(scripted(), respond=edit)
    md = Path(result.markdown_path).read_text()
    assert md.startswith("# My Own Title") and "## Only Hubs" in md and "## Trees" not in md


@pytest.mark.parametrize("cls", [NeedsClarification, OutlineApprovalRequired, Clarified, OutlineDecision])
def test_hitl_events_round_trip_through_json(cls):
    samples = {
        NeedsClarification: dict(question="q", reason="r", suggestions=["a"]),
        OutlineApprovalRequired: dict(outline=Outline(title="t", sections=[]), attempt=1),
        Clarified: dict(refined_question="q"),
        OutlineDecision: dict(action="approve"),
    }
    ev = cls(**samples[cls])
    assert cls.model_validate_json(ev.model_dump_json()) == ev
