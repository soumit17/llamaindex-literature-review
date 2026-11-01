"""Run by tests/test_agent_workflow.py in a separate process: restore a detached *agent* run.

    python -m tests.restore_agent_child <pending_dir> <run_id>

The Context comes from the snapshot file; the agents' conversation comes from the SQLite memory
(runs/agent_memory.db). Nothing else survives from the parent process. Subprocess-safe imports only.
"""

import asyncio
import json
import sys
from functools import partial
from pathlib import Path

from llama_index.core.agent.workflow import ToolCallResult

from litreview.config import get_settings
from litreview.events import OutlineDecision
from litreview.hitl import PendingStore, auto_responder, resume_pending
from litreview.workflows.agent_review import agent_result, attach_memory
from tests.agent_env import PolicyLLM, agent_workflow


async def main(pending_dir: str, run_id: str) -> None:
    settings = get_settings()
    assert "pytest" in str(settings.p2_data_dir) and "pytest" in str(settings.p2_runs_dir), settings
    llm, tools, handlers = PolicyLLM(), [], []
    result = await resume_pending(
        PendingStore(Path(pending_dir)),
        run_id,
        await agent_workflow(llm),
        OutlineDecision(action="approve"),
        auto_responder,
        on_event=lambda ev: tools.append(ev.tool_name) if isinstance(ev, ToolCallResult) else None,
        on_start=handlers.append,
        after_start=partial(attach_memory, session_id=run_id),
    )
    review = await agent_result(handlers[0].ctx)
    print(json.dumps({"final": str(result), "tools": tools, "agents": llm.agent_log, "review": review}))


if __name__ == "__main__":
    asyncio.run(main(*sys.argv[1:3]))
