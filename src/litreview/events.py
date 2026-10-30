"""Workflow events (spec §5.1). Ingestion events now; review events arrive in M4.

Events carry ids and small numbers, never PDFs, text or clients: everything on an event must be
JSON-serializable so a run's Context can be snapshotted (M5 durability). Bulky data goes to files
under data/ and is looked up by `arxiv_id`.
"""

from __future__ import annotations

from typing import Literal

from workflows.events import Event, StartEvent, StopEvent


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
