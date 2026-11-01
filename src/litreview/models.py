"""Domain models (spec §5.2): structured LLM outputs and the data events and state carry.

Two kinds live here:
- *LLM output schemas* (ScopeVerdict, SubQuestionPlan, ResearchAnswer, Outline): what the model must
  return via `astructured_predict`; field descriptions are part of the prompt the model sees.
- *Records* (Citation, FindingClaim, FindingRecord): what the workflow builds from those outputs after
  checking them against the retrieved chunks. They are plain JSON, so state stays snapshot-safe.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# ---------- LLM output schemas ----------
class ScopeVerdict(BaseModel):
    specific: bool = Field(description="True if the question can be researched as asked.")
    reason: str = Field(description="One sentence on why.")
    suggestions: list[str] = Field(
        default_factory=list, description="If not specific: 2-3 sharper versions of the question."
    )


class PlannedQuestion(BaseModel):
    text: str = Field(description="The sub-question.")
    rationale: str = Field(description="One line: why it matters for the main question.")


class SubQuestionPlan(BaseModel):
    sub_questions: list[PlannedQuestion] = Field(description="3-6 non-overlapping sub-questions.")
    scope_note: str = Field(description="One sentence on what the review will and won't cover.")


class Claim(BaseModel):
    statement: str = Field(description="One factual sentence, supported by a single excerpt.")
    excerpt: int = Field(description="Number of the excerpt that supports it (the N in [EN]).")
    quote: str = Field(description="A short span copied verbatim from that excerpt, max 25 words.")


class ResearchAnswer(BaseModel):
    claims: list[Claim] = Field(description="0-8 claims answering the sub-question.")
    gap: str | None = Field(
        default=None, description="What the excerpts do not answer, if anything. Null if fully answered."
    )


class OutlineSection(BaseModel):
    heading: str
    points: list[str] = Field(description="2-4 points the section makes.")
    finding_ids: list[int] = Field(
        description="Ids of the findings this section draws on. Empty for introduction/conclusion."
    )


class Outline(BaseModel):
    title: str
    sections: list[OutlineSection] = Field(description="4-7 sections, including introduction and conclusion.")


# ---------- records built by the workflow ----------
class Citation(BaseModel):
    arxiv_id: str
    node_id: str  # the exact chunk the claim relies on
    page: int | None = None
    quote: str = Field(max_length=300, description="short supporting span from the chunk")
    quote_verified: bool = False  # the quote was found (fuzzy) in the chunk's text


class FindingClaim(BaseModel):
    claim_id: str  # "<finding idx>.<n>", e.g. "2.3"; the writer cites these as [2.3]
    statement: str
    citation: Citation


class FindingRecord(BaseModel):
    idx: int
    sub_question: str
    claims: list[FindingClaim] = []
    gap: str | None = None
    error: str | None = None  # set when research failed and @catch_error stood in

    @property
    def ok(self) -> bool:
        return self.error is None


class CitationIssue(BaseModel):
    section_idx: int
    claim: str  # the sentence, markers stripped
    problem: Literal["no_citation", "citation_not_supporting", "unknown_node"]
    suggested_fix: str | None = None
