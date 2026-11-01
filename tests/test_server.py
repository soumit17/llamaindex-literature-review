"""M7: the review over real HTTP. A uvicorn server on 127.0.0.1 in this test, the official WorkflowClient,
scripted LLM behind it. Approval is a POST /events/{handler_id}, exactly as a web app would send it."""

import asyncio
import contextlib
from pathlib import Path

import pytest
import uvicorn
from llama_agents.client import WorkflowClient
from llama_agents.server import SqliteWorkflowStore

from litreview.events import OutlineDecision
from litreview.server import build_server
from tests.review_env import review_workflow, scripted

pytestmark = [pytest.mark.enable_socket, pytest.mark.allow_hosts(["127.0.0.1"])]


@contextlib.asynccontextmanager
async def serving(server):
    config = uvicorn.Config(server.app, host="127.0.0.1", port=0, log_level="warning", lifespan="on")
    http = uvicorn.Server(config)
    task = asyncio.create_task(http.serve())
    while not http.started:
        await asyncio.sleep(0.02)
    port = http.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        http.should_exit = True
        await task


async def collect(client: WorkflowClient, handler_id: str, approve: bool) -> list[str]:
    types = []
    async for env in client.get_workflow_events(handler_id):
        types.append(env.type)
        if approve and env.type == "OutlineApprovalRequired":
            await client.send_event(handler_id, OutlineDecision(action="approve"))
    return types


async def test_review_over_http_with_approval_and_two_readers(ingested, tmp_path):
    store = SqliteWorkflowStore(db_path=str(tmp_path / "workflows.db"))
    server = build_server({"review": await review_workflow(scripted())}, workflow_store=store)
    async with serving(server) as base_url:
        client = WorkflowClient(base_url=base_url)
        assert "review" in (await client.list_workflows()).workflows

        started = await client.run_workflow_nowait(
            "review", start_event={"question": "How do agent teams coordinate?"}
        )
        # Two independent readers of one run: one answers the prompt, the other only watches.
        approver, watcher = await asyncio.gather(
            collect(client, started.handler_id, approve=True),
            collect(client, started.handler_id, approve=False),
        )
        handler = await client.get_handler(started.handler_id)

    assert handler.status == "completed", handler.error
    assert "OutlineApprovalRequired" in approver and approver == watcher  # both saw every event
    assert approver[-1] == "ReviewReady"
    result = handler.result
    assert result is not None and result.type == "ReviewReady"
    assert Path(result.value["markdown_path"]).exists()


async def test_finished_run_can_be_replayed_from_the_store(ingested, tmp_path):
    store = SqliteWorkflowStore(db_path=str(tmp_path / "workflows.db"))
    server = build_server({"review": await review_workflow(scripted())}, workflow_store=store)
    async with serving(server) as base_url:
        client = WorkflowClient(base_url=base_url)
        started = await client.run_workflow_nowait("review", start_event={"question": "q?"})
        live = await collect(client, started.handler_id, approve=True)
        replay = await collect(client, started.handler_id, approve=False)  # after the run ended
        listed = await client.get_handlers()

    assert replay == live
    assert started.handler_id in {h.handler_id for h in listed.handlers}


async def test_debugger_ui_knows_the_human_answer_events(ingested, tmp_path):
    server = build_server({"review": await review_workflow(scripted())})
    async with serving(server) as base_url:
        events = await WorkflowClient(base_url=base_url).get_workflow_events_schema("review")
    names = {e.get("title") or e.get("name") for e in events.model_dump()["events"]}
    assert {"OutlineDecision", "Clarified"} <= names
