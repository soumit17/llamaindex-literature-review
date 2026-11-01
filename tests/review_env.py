"""Shared review-workflow fixtures: scripted LLM replies, fake reranker, a run helper.

Imports nothing from tests/conftest.py on purpose: tests/restore_child.py runs in a subprocess, and
conftest clears the P2_* directory settings at import time, which would point that child process at
the real data directory.
"""

import json
from typing import Any

from workflows.events import Event

from litreview.events import ReviewRequest
from litreview.hitl import auto_responder, drive
from litreview.resources import get_embed_model, get_llm, get_reranker, get_writer_llm, shared_resources
from litreview.retrieval.engines import FastEmbedRerank
from litreview.workflows.review import ReviewWorkflow
from tests.fakes import CountingEmbedding, ScriptedLLM


class WordOverlapEncoder:
    """Stand-in for fastembed's TextCrossEncoder: score = query words found in the text."""

    def rerank(self, query: str, texts: list[str]):
        words = set(query.lower().split())
        return [float(len(words & set(t.lower().split()))) for t in texts]


def fake_reranker(top_n: int = 5) -> FastEmbedRerank:
    reranker = FastEmbedRerank(top_n=top_n)
    reranker._encoder = WordOverlapEncoder()
    return reranker


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
                {
                    "statement": "Orchestrators assign roles.",
                    "excerpt": 1,
                    "quote": "agent",
                },  # in every fixture chunk
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
    "[CHECK]": json.dumps({"verdicts": []}),  # the citation check finds nothing wrong
    "[REVISE]": "Orchestrators assign roles [1.1].",
}


def scripted(**kwargs: Any) -> ScriptedLLM:
    return ScriptedLLM(script={**SCRIPT, **kwargs.pop("script", {})}, **kwargs)


async def run_review(
    llm: ScriptedLLM, respond=auto_responder, question: str = "How do agent teams coordinate?", **request
):
    """Like `litreview review`: drive the run, answer HITL prompts, keep every streamed event."""
    wf = await review_workflow(llm)
    events: list[Event] = []
    handler = wf.run(start_event=ReviewRequest(question=question, **request))
    result = await drive(handler, respond, on_event=events.append, expose_internal=True)
    return result, events, handler


async def review_workflow(llm: ScriptedLLM) -> ReviewWorkflow:
    manager = await shared_resources(
        {
            get_embed_model: CountingEmbedding.make(),
            get_reranker: fake_reranker(),
            get_llm: llm,
            get_writer_llm: llm,
        }
    )
    return ReviewWorkflow(timeout=60, resource_manager=manager)
