"""The server used by scripts/server_restart_demo.py: one tiny, LLM-free workflow that takes ~10 s.

python -m llama_agents.server scripts/restart_demo_server.py
(P2_RUNTIME=default -> SqliteWorkflowStore; P2_RUNTIME=dbos -> DBOS runtime; dbs under P2_RUNS_DIR)
"""

import os

from llama_agents.server import SqliteWorkflowStore, WorkflowServer

from litreview.config import get_settings
from litreview.workflows.countdown import Countdown

runs = get_settings().p2_runs_dir
runs.mkdir(parents=True, exist_ok=True)
if os.environ.get("P2_RUNTIME") == "dbos":
    from litreview.durability import dbos_runtime

    rt = dbos_runtime()
    server = WorkflowServer(workflow_store=rt.create_workflow_store(), runtime=rt.build_server_runtime())
    server.add_workflow(
        "countdown", Countdown(runtime=rt, workflow_name="litreview-countdown-v1", timeout=120)
    )
else:
    server = WorkflowServer(workflow_store=SqliteWorkflowStore(db_path=str(runs / "restart_demo.db")))
    server.add_workflow("countdown", Countdown(timeout=120))
