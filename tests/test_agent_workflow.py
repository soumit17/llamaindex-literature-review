"""M6: the AgentWorkflow variant, driven by PolicyLLM (tool calls decided from the conversation)."""

import json
import re
import subprocess
import sys
from pathlib import Path

from llama_index.core.agent.workflow import AgentInput, ToolCallResult

from litreview.config import PROJECT_ROOT
from litreview.events import OutlineApprovalRequired, OutlineDecision
from litreview.hitl import Detached, PendingStore, auto_responder, detach_responder, drive
from litreview.workflows.agent_review import agent_result, start_agent_review
from tests.agent_env import QUESTION, PolicyLLM, agent_deps, agent_workflow, judge


async def run_agents(llm: PolicyLLM, respond=auto_responder, check_llm=None, session="s1"):
    handler = start_agent_review(await agent_workflow(llm, check_llm), session)
    events: list = []
    result = await drive(handler, respond, on_event=events.append)
    return result, events, handler


def handoffs(events) -> list[str]:
    agents = [e.current_agent_name for e in events if isinstance(e, AgentInput)]
    return [a for i, a in enumerate(agents) if i == 0 or agents[i - 1] != a]


async def test_agents_hand_off_in_order_and_write_a_cited_review(ingested):
    result, events, handler = await run_agents(PolicyLLM())

    assert handoffs(events) == ["Planner", "Researcher", "Writer", "Reviewer"]
    review = await agent_result(handler.ctx)
    md = Path(review["markdown_path"]).read_text()
    assert md.startswith("# Agent Coordination") and "## References" in md
    numbers = {n for g in re.findall(r"\[(\d+(?:, \d+)*)\]", md) for n in g.split(", ")}
    refs = json.loads((Path(review["markdown_path"]).parent / "citations.json").read_text())
    assert numbers == {str(r["n"]) for r in refs} and refs  # every [n] has a reference
    assert "/agent/" in review["markdown_path"]  # next to Workflow 2's output, not over it


async def test_record_finding_rejects_uncited_and_misquoted_claims(ingested):
    from litreview.workflows.agent_review import ReviewTools

    _, _, handler = await run_agents(PolicyLLM())
    tools = ReviewTools(await agent_deps(PolicyLLM()))
    seen_node = (await handler.ctx.store.get("review"))["seen_nodes"][0]
    out = await tools.record_finding(
        handler.ctx,
        1,
        [
            {"statement": "a", "node_id": "never-searched", "quote": "x"},
            {"statement": "b", "node_id": seen_node, "quote": "words that are not in that passage at all"},
        ],
    )
    assert "Recorded 0 claim(s)" in out
    assert "not a node_id from your searches" in out and "quote not found" in out


async def test_outline_tool_waits_for_the_human_and_a_rejection_loops(ingested):
    asked: list[OutlineApprovalRequired] = []

    async def reject_once(ev):
        asked.append(ev)
        if len(asked) == 1:
            return OutlineDecision(action="reject", feedback="add a section on failures")
        return OutlineDecision(action="approve")

    _, events, handler = await run_agents(PolicyLLM(), respond=reject_once)
    assert [e.attempt for e in asked] == [1, 2]  # wait_for_event paused the tool twice
    results = [
        e.tool_output.content
        for e in events
        if isinstance(e, ToolCallResult) and e.tool_name == "propose_outline"
    ]
    assert results[0].startswith("Rejected by the reader: add a section on failures")
    assert (await agent_result(handler.ctx))["markdown_path"]


async def test_reviewer_requests_revision_then_finalizes(ingested):
    bad = judge([{"item": 1, "verdict": "unsupported", "reason": "nope"}])
    _, events, handler = await run_agents(PolicyLLM(), check_llm=bad)
    review = await ctx_review(handler)
    assert review["check_rounds"] == 1 and review["last_issues"]  # PolicyLLM finalizes after one check
    assert (await agent_result(handler.ctx))["unsupported_claims"] == len(review["last_issues"])


async def ctx_review(handler):
    return await handler.ctx.store.get("review")


async def test_detached_agent_run_resumes_in_a_new_process(ingested, tmp_path):
    store = PendingStore(tmp_path / "pending")
    handler = start_agent_review(await agent_workflow(PolicyLLM()), "agent-run-1")
    detached = await drive(handler, detach_responder, pending=(store, "agent-run-1", QUESTION))
    assert isinstance(detached, Detached) and isinstance(detached.waiting_for, OutlineApprovalRequired)

    child = subprocess.run(
        [sys.executable, "-m", "tests.restore_agent_child", str(store.directory), "agent-run-1"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert child.returncode == 0, child.stderr[-3000:]
    out = json.loads(child.stdout.strip().splitlines()[-1])
    # It continued inside the paused propose_outline call, then Writer -> Reviewer; no re-planning.
    assert out["tools"][0] == "propose_outline"
    assert "record_subquestions" not in out["tools"] and "search_corpus" not in out["tools"]
    assert out["agents"][0] == "Writer" and "Planner" not in out["agents"]
    assert out["review"]["markdown_path"] and Path(out["review"]["markdown_path"]).exists()
    assert store.list() == []
