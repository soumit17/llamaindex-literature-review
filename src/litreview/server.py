"""Serving the workflows over HTTP, with the debugger UI at / (spec §13).

    uv run litreview serve                    # SqliteWorkflowStore: handlers and events survive a restart
    uv run litreview serve --runtime dbos     # DBOS runtime: unfinished runs also *continue* after a restart
    python -m llama_agents.server src/litreview/server_app.py   # the library's own launcher

Endpoints you'll use (all built in):
    POST /workflows/review/run-nowait   {"start_event": {"question": "..."}}           -> handler_id
    GET  /events/{handler_id}?sse=true  live events, incl. OutlineApprovalRequired
    POST /events/{handler_id}           {"event": <OutlineDecision>}                     -> continues
    GET  /handlers/{handler_id}         status and result
    POST /workflows/agent_review/run-nowait  {"start_event": {"user_msg": "..."}}       (Workflow 3)

Events are stored, and every reader follows its own cursor (`after_sequence`), so several clients can
watch one run and a finished run's events can be read again (the spec's "one reader per stream" is no
longer true in this server version; see docs/decisions.md D12).
"""

from __future__ import annotations

from typing import Any

from llama_agents.server import SqliteWorkflowStore, WorkflowServer
from workflows import Workflow

from litreview.config import get_settings
from litreview.events import Clarified, OutlineDecision

# Durable names for DBOS: journal entries are filed under them, so they must not change between
# deployments (rename = new identity; old in-flight runs become invisible). Bump the suffix on purpose.
DURABLE_NAMES = {"review": "litreview-review-v1", "ingest": "litreview-ingest-v1"}
# Waiting for a human can take a while. After this many idle seconds the server releases a waiting run
# from memory and restores it from the store when the answer arrives.
IDLE_TIMEOUT_S = 3600.0


def build_server(
    workflows: dict[str, Workflow],
    workflow_store: Any = None,
    runtime: Any = None,
) -> WorkflowServer:
    """Register each workflow by its HTTP name. Pass a store/runtime pair for persistence."""
    server = WorkflowServer(workflow_store=workflow_store, runtime=runtime, idle_timeout=IDLE_TIMEOUT_S)
    for name, wf in workflows.items():
        # additional_events: the human's answers aren't produced by any step, so the debugger UI's
        # "Send Event" form only offers them if they are registered here.
        extra = [OutlineDecision, Clarified] if name in ("review", "agent_review") else []
        server.add_workflow(name, wf, additional_events=extra)
    return server


async def production_server(runtime: str = "default") -> WorkflowServer:
    from litreview.workflows.ingestion import IngestionWorkflow
    from litreview.workflows.review import ReviewWorkflow

    if runtime == "dbos":
        from litreview.durability import dbos_runtime

        rt = dbos_runtime()
        workflows: dict[str, Workflow] = {
            name: cls(timeout=3600, runtime=rt, workflow_name=DURABLE_NAMES[name])
            for name, cls in (("review", ReviewWorkflow), ("ingest", IngestionWorkflow))
        }
        # agent_review is not served on DBOS: AgentWorkflow keeps its memory in the Context under a key
        # the state store refuses to serialize, so a journal replay would resume without it.
        return build_server(
            workflows, rt.create_workflow_store(), rt.build_server_runtime(idle_timeout=IDLE_TIMEOUT_S)
        )

    from litreview.workflows.agent_review import build_agent_review, production_deps

    db = get_settings().p2_runs_dir / "workflows.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    workflows = {
        "review": ReviewWorkflow(timeout=3600),
        "ingest": IngestionWorkflow(timeout=3600),
        "agent_review": build_agent_review(await production_deps()),
    }
    return build_server(workflows, SqliteWorkflowStore(db_path=str(db)))
