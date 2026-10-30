"""Typed workflow state (spec §5.3). Every field has a default so the store can create it.

Steps update it with `async with ctx.store.edit_state() as s:`, which holds the store's lock for
the block, so parallel workers never lose each other's appends. Never call an LLM inside that block.
"""

from pydantic import BaseModel


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
