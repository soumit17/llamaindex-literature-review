"""A $0 stand-in for the agents' LLM, plus a helper to build the agent workflow on the fixture corpus.

`PolicyLLM` is a MockFunctionCallingLLM whose replies are decided from the conversation so far (which
agent is speaking, which tool results exist), not from a fixed queue. So a run restored from a
snapshot, in a fresh process with a fresh PolicyLLM, simply continues from where it stopped.

Imports nothing from tests/conftest.py (subprocess-safe, see tests/review_env.py).
"""

from __future__ import annotations

import itertools
import json
import re
from typing import Any

from llama_index.core.llms import ChatMessage, MessageRole
from llama_index.core.llms.llm import ToolSelection
from llama_index.core.llms.mock import MockFunctionCallingLLM
from workflows.resource import Resource

from litreview.resources import (
    get_embed_model,
    get_llm,
    get_papers,
    get_query_engine,
    get_reranker,
    get_storage,
    shared_resources,
)
from litreview.retrieval.summaries import load_all_summaries
from litreview.workflows.agent_review import AgentDeps, build_agent_review
from tests.fakes import CountingEmbedding, ScriptedLLM
from tests.review_env import fake_reranker

QUESTION = "How do agents coordinate?"
SUBQUESTIONS = ["How do hubs route work?", "How do rings pass messages?"]
OUTLINE = {
    "title": "Agent Coordination",
    "sections": [
        {"heading": "Introduction", "points": ["why"], "finding_ids": []},
        {"heading": "Hubs and Rings", "points": ["compare"], "finding_ids": [1, 2]},
        {"heading": "Conclusion", "points": ["wrap"], "finding_ids": []},
    ],
}
SECTION_TEXT = "Hubs route work through an orchestrator [1.1]. Rings pass messages around [2.1]."
_ids = itertools.count(1)


def _tool(name: str, **kwargs: Any) -> ChatMessage:
    call = ToolSelection(tool_id=f"call_{next(_ids)}", tool_name=name, tool_kwargs=kwargs)
    return ChatMessage(role="assistant", content="", additional_kwargs={"tool_calls": [call]})


def _results(messages) -> list[str]:
    return [m.content or "" for m in messages if m.role == MessageRole.TOOL]


def _agent(messages) -> str:
    system = next((m.content or "" for m in messages if m.role == MessageRole.SYSTEM), "")
    match = re.search(r"You are the (\w+)", system)
    return match.group(1) if match else "?"


def policy(messages, **kwargs) -> ChatMessage:
    results, agent = _results(messages), _agent(messages)
    if agent == "Planner":
        if not any(r.startswith("Recorded:") for r in results):
            return _tool("record_subquestions", sub_questions=SUBQUESTIONS)
        return _tool("handoff", to_agent="Researcher", reason="plan recorded")
    if agent == "Researcher":
        done = sum(bool(re.match(r"Recorded \d+ claim", r)) for r in results)
        if done >= len(SUBQUESTIONS):
            return _tool("handoff", to_agent="Writer", reason="all findings recorded")
        last = results[-1] if results else ""
        if last.startswith("node_id:"):  # just searched: record a claim quoting the first passage
            node_id = re.search(r"node_id: (\S+)", last).group(1)
            passage = last.split("\n", 2)[2]
            claim = {
                "statement": f"Claim for sub-question {done + 1}.",
                "node_id": node_id,
                "quote": passage[:40],
            }
            return _tool("record_finding", sub_question_idx=done + 1, claims=[claim])
        return _tool("search_corpus", query=SUBQUESTIONS[done])
    if agent == "Writer":
        if not any(r.startswith("Finding 1") or r.startswith("No findings") for r in results):
            return _tool("get_findings")
        decided = [r for r in results if r.startswith("Outline ") or r.startswith("Rejected by the reader")]
        if not decided or decided[-1].startswith("Rejected"):
            return _tool("propose_outline", outline=OUTLINE)
        written = sum(r.startswith("Saved section") for r in results)
        if written < len(OUTLINE["sections"]):
            return _tool("write_section", section_idx=written, markdown=SECTION_TEXT)
        return _tool("handoff", to_agent="Reviewer", reason="sections written")
    if agent == "Reviewer":
        if not any("citation issue" in r.lower() or "issue(s)" in r for r in results):
            return _tool("check_citations")
        if not any(r.startswith("Review written") for r in results):
            return _tool("finalize_review")
        return ChatMessage(role="assistant", content="Review finished.")
    return ChatMessage(role="assistant", content="?")


class PolicyLLM(MockFunctionCallingLLM):
    """Counts its calls per agent, so tests can check the handoff order."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(response_generator=self._respond, **kwargs)
        self._log: list[str] = []

    def _respond(self, messages, **kwargs) -> ChatMessage:
        self._log.append(_agent(messages))
        return policy(messages, **kwargs)

    @property
    def agent_log(self) -> list[str]:
        return self._log


def judge(verdicts: list[dict] | None = None) -> ScriptedLLM:
    return ScriptedLLM(script={"[CHECK]": json.dumps({"verdicts": verdicts or []})})


async def agent_deps(llm: PolicyLLM, check_llm: ScriptedLLM | None = None) -> AgentDeps:
    """Production retrieval and storage over the fixture corpus (after `ingested`), fake LLMs."""
    from litreview.config import get_settings

    manager = await shared_resources(
        {get_embed_model: CountingEmbedding.make(), get_reranker: fake_reranker(), get_llm: llm}
    )
    return AgentDeps(
        engine=await manager.get(Resource(get_query_engine)),
        storage=await manager.get(Resource(get_storage)),
        llm=llm,
        writer_llm=llm,
        papers=await manager.get(Resource(get_papers)),
        summaries=load_all_summaries(get_settings().p2_data_dir / "summaries"),
        check_llm=check_llm or judge(),
    )


async def agent_workflow(llm: PolicyLLM, check_llm: ScriptedLLM | None = None):
    return build_agent_review(await agent_deps(llm, check_llm))
