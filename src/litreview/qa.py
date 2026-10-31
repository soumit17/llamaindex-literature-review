"""Labeled retrieval questions (spec §4.3): Haiku drafts candidates from abstracts, you curate.

data/qa/candidates.jsonl   what Haiku proposed (kept for provenance)
data/qa/labeled.jsonl      what you kept, possibly edited: the retrieval eval's ground truth
data/qa/rejected.jsonl     what you dropped (so curation can resume where you stopped)

Labels are at the paper level: a question is a hit if a relevant paper appears in the top-5 chunks.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from llama_index.core.llms import LLM
from llama_index.core.prompts import PromptTemplate
from pydantic import BaseModel, Field

from litreview.corpus import PaperMeta

PAPERS_PER_BATCH = 5
SPECIFIC_PER_BATCH = 5
CROSS_PER_BATCH = 3

PROMPT = PromptTemplate(
    """[QA] You are building an evaluation set for a retrieval system over ML research papers.

Papers (id, title, abstract):
{papers}

Write {n_specific} SPECIFIC questions, each answerable from exactly one of these papers (about a
mechanism, design choice, experiment or result), and {n_cross} CROSS-PAPER questions, each answered by
2-3 of these papers together (comparative or overview).

Rules:
- Do NOT name the paper, its system, its benchmark or its authors; paraphrase the idea instead, the way
  a researcher who hasn't read it would ask. (Named systems make retrieval trivially easy.)
- The answer must be in the paper's text, not general knowledge.
- relevant_arxiv_ids lists only ids from the papers above.
- relevant_section is one of: introduction, method, experiments, results, discussion, conclusion,
  or null if unsure."""
)


class QACandidate(BaseModel):
    question: str
    relevant_arxiv_ids: list[str] = Field(min_length=1, max_length=3)
    relevant_section: str | None = None
    kind: Literal["specific", "cross"]


class QABatch(BaseModel):
    questions: list[QACandidate]


class LabeledQuestion(BaseModel):
    id: str
    question: str
    relevant_arxiv_ids: list[str]
    relevant_section: str | None = None
    kind: str


def batches(papers: list[PaperMeta]) -> list[list[PaperMeta]]:
    return [papers[i : i + PAPERS_PER_BATCH] for i in range(0, len(papers), PAPERS_PER_BATCH)]


async def draft_batch(llm: LLM, batch: list[PaperMeta]) -> list[QACandidate]:
    papers = "\n\n".join(f"[{p.arxiv_id}] {p.title}\n{p.abstract}" for p in batch)
    # Structured output: Anthropic tool calling under the hood, validated into QABatch.
    result = await llm.astructured_predict(
        QABatch, PROMPT, papers=papers, n_specific=SPECIFIC_PER_BATCH, n_cross=CROSS_PER_BATCH
    )
    valid = {p.arxiv_id for p in batch}
    return [q for q in result.questions if set(q.relevant_arxiv_ids) <= valid]  # drop invented ids


def write_jsonl(path: Path, rows: Sequence[BaseModel]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(r.model_dump_json() + "\n" for r in rows))


def append_jsonl(path: Path, row: BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(row.model_dump_json() + "\n")


def read_labeled(path: Path) -> list[LabeledQuestion]:
    if not path.exists():
        return []
    return [
        LabeledQuestion.model_validate(json.loads(line)) for line in path.read_text().splitlines() if line
    ]
