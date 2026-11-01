"""Run by tests/test_hitl.py in a *separate process*: restore a detached review run and approve it.

    python -m tests.restore_child <pending_dir> <run_id>

Imports nothing from tests/conftest.py (see tests/review_env.py); the P2_* directories come from the
parent test's environment, and we refuse to run against anything that isn't a pytest temp dir.
"""

import asyncio
import json
import sys
from pathlib import Path

from litreview.config import get_settings
from litreview.events import OutlineDecision
from litreview.hitl import PendingStore, auto_responder, resume_pending
from tests.review_env import review_workflow, scripted

TAGS = ("[SCOPE]", "[PLAN]", "[RESEARCH]", "[OUTLINE]", "[WRITE]", "[CHECK]", "[REVISE]")


async def main(pending_dir: str, run_id: str) -> None:
    settings = get_settings()
    assert "pytest" in str(settings.p2_data_dir) and "pytest" in str(settings.p2_out_dir), settings
    llm = scripted()
    result = await resume_pending(
        PendingStore(Path(pending_dir)),
        run_id,
        await review_workflow(llm),
        OutlineDecision(action="approve"),
        auto_responder,
    )
    calls = {tag: sum(tag in p for p in llm.calls) for tag in TAGS}
    print(json.dumps({"markdown_path": result.markdown_path, "error": result.error, "calls": calls}))


if __name__ == "__main__":
    asyncio.run(main(*sys.argv[1:3]))
