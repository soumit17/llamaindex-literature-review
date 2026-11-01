"""Workflow events (spec §5.1): ingestion (Workflow 1) and review (Workflow 2).

Events carry ids and small numbers, never PDFs, text or clients: everything on an event must be
JSON-serializable so a run's Context can be snapshotted (M5 durability). Bulky data goes to files
under data/ and is looked up by `arxiv_id`.
"""

from __future__ import annotations

from typing import Literal

from workflows.events import Event, HumanResponseEvent, InputRequiredEvent, StartEvent, StopEvent

from litreview.models import FindingRecord, Outline


# ---------- ingestion ----------
class IngestRequest(StartEvent):
    lock_file: str = "data/corpus.lock.json"  # informational; the path comes from P2_DATA_DIR
    rebuild: bool = False  # re-parse and re-index from scratch (summaries and embeddings stay cached)
    limit: int | None = None  # only the first N locked papers (cheap iteration)
    fail_ids: list[str] = []  # demo: make fetch_pdf fail for these ids (shows retry + catch_error)


class PaperToFetch(Event):
    arxiv_id: str
    version: int
    sha256: str | None = None


class PaperFetched(Event):
    arxiv_id: str
    pdf_path: str
    downloaded: bool


class PaperParsed(Event):
    arxiv_id: str
    n_pages: int
    n_chars: int
    n_segments: int


class PaperIndexed(Event):
    arxiv_id: str
    n_nodes: int  # new nodes this run; 0 when the docstore already had this paper


class PaperSummarized(Event):
    arxiv_id: str
    summary_chars: int
    generated: bool  # False when data/summaries/<id>.json already existed ($0)


class IngestProgress(Event):
    """Written to the stream only (no step consumes it); the CLI turns it into progress bars."""

    stage: Literal["start", "fetch", "parse", "index", "summarize"]
    done: int
    total: int
    arxiv_id: str | None = None
    status: Literal["ok", "cached", "retry", "failed"] = "ok"
    message: str | None = None


class IngestReport(StopEvent):
    papers: int  # fully ingested this run (fetched -> summarized)
    nodes: int  # chunks in the index after this run
    new_nodes: int
    summaries_generated: int
    failed: list[str]


# ---------- review (Workflow 2) ----------
class ReviewRequest(StartEvent):
    question: str
    max_subquestions: int = 5
    target_words: int = 1500
    audience: str = "ML engineers"


class NeedsClarification(InputRequiredEvent):  # branch: the question is too vague to plan
    question: str
    reason: str
    suggestions: list[str]


class Clarified(HumanResponseEvent):
    refined_question: str


class QuestionScoped(Event):  # the other branch: the question is fine as asked
    question: str


class SubQuestion(Event):
    idx: int
    text: str
    rationale: str


class Finding(Event):
    """One per sub-question, success or failure: `collect_events` counts exact types, so a separate
    FindingFailed type would make the expected mix unknowable (see docs/decisions.md D9)."""

    record: FindingRecord


class FindingsReady(Event):
    n_ok: int
    n_failed: int


class OutlineApprovalRequired(InputRequiredEvent):
    outline: Outline
    attempt: int


class OutlineDecision(HumanResponseEvent):
    action: Literal["approve", "edit", "reject"]
    edited_outline: Outline | None = None
    feedback: str | None = None


class ReplanRequested(Event):  # outline rejected: loop back to `plan` with the feedback
    feedback: str


class WriteSection(Event):
    section_idx: int
    heading: str
    points: list[str]
    finding_ids: list[int]


class SectionToken(Event):  # streamed only: live LLM tokens for the section being written
    section_idx: int
    delta: str
    restart: bool = False  # True on a retry: the UI should clear what it showed so far


class SectionDraft(Event):
    section_idx: int
    heading: str
    markdown: str  # with claim markers like [2.3]
    unknown_markers: int  # markers the writer invented; removed from `markdown`


class DraftAssembled(Event):
    title: str
    sections: list[SectionDraft]


class Progress(Event):
    """Base progress event. Steps `ctx.send_event` subclasses; `log_progress` takes them all because it
    sets accept_event_subclasses=True (routing is by exact type otherwise)."""

    stage: str
    message: str


class ResearchProgress(Progress):
    idx: int
    status: Literal["researching", "done", "failed", "retry"]


class WriteProgress(Progress):
    section_idx: int
    status: Literal["writing", "done", "retry"]


class ReviewReady(StopEvent):
    markdown_path: str
    bib_path: str
    n_citations: int
    unsupported_claims: int  # citations whose quote wasn't found in the chunk (checked properly in M5)
    unknown_markers: int  # writer markers that matched no claim (removed)
    failed_subquestions: list[str]
    cost_usd: float
    error: str | None = None  # set by the wildcard @catch_error: partial output
