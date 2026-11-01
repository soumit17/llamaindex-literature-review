"""Typed workflow state (spec §5.3). Every field has a default so the store can create it.

Steps update it with `async with ctx.store.edit_state() as s:`, which holds the store's lock for
the block, so parallel workers never lose each other's appends. Never call an LLM inside that block.
"""

from pydantic import BaseModel

from litreview.models import FindingRecord, Outline


class IngestState(BaseModel):
    total: int = 0
    fail_ids: list[str] = []  # copied from IngestRequest so fetch_pdf can see it
    fetched: list[str] = []
    parsed: list[str] = []
    indexed: list[str] = []
    summarized: list[str] = []
    new_nodes: int = 0
    summaries_generated: int = 0
    failed: dict[str, str] = {}  # arxiv_id -> error, filled by the catch_error handler


class SectionDraftRecord(BaseModel):
    heading: str
    markdown: str
    unknown_markers: int = 0


class ReviewState(BaseModel):
    question: str = ""
    audience: str = "ML engineers"
    target_words: int = 1500
    max_subquestions: int = 5
    sub_questions: list[str] = []
    expected_findings: int = 0  # how many Finding events gather_findings waits for
    findings: dict[int, FindingRecord] = {}  # by idx
    replan_feedback: list[str] = []  # from rejected outlines, fed back into `plan`
    outline: Outline | None = None
    outline_attempts: int = 0
    expected_sections: int = 0
    drafts: dict[int, SectionDraftRecord] = {}  # latest draft per section (revisions replace)
    citation_rounds: int = 0  # how many times the citation check ran
    revisions: int = 0  # how many revise rounds ran (<= MAX_REVISIONS)
    cost_at_start: float = 0.0  # ledger total when the run began; cost = now - this
    log: list[str] = []  # every Progress event, appended by log_progress
