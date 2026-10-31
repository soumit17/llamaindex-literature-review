"""Per-paper summaries (spec §6.2 summarize_paper). They feed the DocumentSummaryIndex in M3.

Cost control (spec §21): the LLM sees only the abstract, the introduction and the conclusion,
capped at ~18k characters (~4.5k tokens, under the 6k-token budget), never the whole paper.
Each summary is saved to data/summaries/<id>.json and never regenerated while that file exists.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from llama_index.core.llms import LLM, ChatMessage
from pydantic import BaseModel

INTRO_CHARS = 10_000
CONCLUSION_CHARS = 6_000

SYSTEM = (
    "You summarize machine-learning research papers for a literature review on: {topic}. "
    "Use only the text provided. Be concrete and factual; do not speculate."
)
USER = """[SUMMARY]
Title: {title}

Abstract:
{abstract}

Introduction (excerpt):
{intro}

Conclusion (excerpt):
{conclusion}

Write a summary of at most 200 words covering, in order: (1) the problem, (2) the multi-agent
orchestration or coordination approach (agent roles, communication topology, control flow),
(3) key results with numbers where given, (4) stated limitations. Plain prose, no headings."""


class PaperSummary(BaseModel):
    arxiv_id: str
    title: str
    summary: str
    model: str
    input_chars: int
    created: str


def summary_input(rows: list[dict], abstract: str) -> tuple[str, str]:
    """(introduction excerpt, conclusion excerpt) from parsed segments, with fallbacks for papers
    whose headings the parser missed."""

    def text_of(*sections: str) -> str:
        return " ".join(r["text"] for r in rows if r["section"] in sections)

    body = [r for r in rows if r["section"] not in ("front", "abstract")]
    intro = text_of("introduction") or " ".join(r["text"] for r in body[:4])
    conclusion = text_of("conclusion") or text_of("discussion") or " ".join(r["text"] for r in body[-3:])
    return intro[:INTRO_CHARS], conclusion[-CONCLUSION_CHARS:]


def build_messages(topic: str, title: str, abstract: str, intro: str, conclusion: str) -> list[ChatMessage]:
    return [
        ChatMessage(role="system", content=SYSTEM.format(topic=topic)),
        ChatMessage(
            role="user",
            content=USER.format(title=title, abstract=abstract, intro=intro, conclusion=conclusion),
        ),
    ]


async def summarize(llm: LLM, arxiv_id: str, title: str, messages: list[ChatMessage]) -> PaperSummary:
    response = await llm.achat(messages)
    return PaperSummary(
        arxiv_id=arxiv_id,
        title=title,
        summary=(response.message.content or "").strip(),
        model=llm.metadata.model_name,
        input_chars=sum(len(m.content or "") for m in messages),
        created=datetime.now(UTC).isoformat(timespec="seconds"),
    )


def load_summary(path: Path) -> PaperSummary | None:
    return PaperSummary.model_validate_json(path.read_text()) if path.exists() else None


def load_all_summaries(directory: Path) -> dict[str, str]:
    """arxiv_id -> summary text, for every saved summary."""
    return {s.arxiv_id: s.summary for p in sorted(directory.glob("*.json")) if (s := load_summary(p))}


def save_summary(path: Path, summary: PaperSummary) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(summary.model_dump(), indent=2) + "\n")
    tmp.replace(path)  # atomic: a crash never leaves a half-written summary that would be "cached"
