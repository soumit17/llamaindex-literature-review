"""M7 Python client demo (spec §13.4): drive a review through the HTTP API, as a web app would.

Start the server in another terminal first:  uv run litreview serve
Then:                                         uv run python scripts/client_demo.py ["question"]

1. POST /workflows/review/run-nowait           -> handler_id
2. two readers on GET /events/{handler_id}     (one approves, one only watches: both see everything)
3. on OutlineApprovalRequired: POST /events/{handler_id} with an OutlineDecision (approve)
4. GET /handlers/{handler_id}                  -> status and the ReviewReady result
5. read the finished run's events again        (they are stored, so a stream can be replayed)

Costs one Haiku review (~$0.01).
"""

from __future__ import annotations

import asyncio
import os

import typer
from llama_agents.client import WorkflowClient
from rich.console import Console

from litreview.config import CONFIG_DIR
from litreview.corpus import Topic
from litreview.events import OutlineDecision

console = Console()


async def read(client: WorkflowClient, handler_id: str, name: str, approve: bool) -> list[str]:
    types: list[str] = []
    async for env in client.get_workflow_events(handler_id):
        types.append(env.type)
        if env.type in ("ResearchProgress", "WriteProgress") and env.value.get("status") in (
            "done",
            "failed",
        ):
            console.print(f"  [dim]{name}[/] {env.type}: {env.value['message'][:70]}")
        elif env.type == "OutlineApprovalRequired":
            outline = env.value["outline"]
            console.print(
                f"  [yellow]{name}[/] outline: {outline['title']} ({len(outline['sections'])} sections)"
            )
            if approve:
                await client.send_event(handler_id, OutlineDecision(action="approve"))
                console.print(
                    f"  [yellow]{name}[/] sent OutlineDecision(approve) via POST /events/{handler_id}"
                )
    return types


async def run(question: str, base_url: str) -> None:
    client = WorkflowClient(base_url=base_url)
    console.print(f"workflows on the server: {(await client.list_workflows()).workflows}")
    started = await client.run_workflow_nowait("review", start_event={"question": question})
    console.print(
        f"started handler [bold]{started.handler_id}[/] (open {base_url}/ to watch it in the debugger UI)"
    )

    approver, watcher = await asyncio.gather(
        read(client, started.handler_id, "reader-1", approve=True),
        read(client, started.handler_id, "reader-2", approve=False),
    )
    handler = await client.get_handler(started.handler_id)
    console.print(f"status: [bold]{handler.status}[/]  {handler.error or ''}")
    if handler.result is not None:
        result = handler.result.value
        console.print(f"review: {result.get('markdown_path')}  citations: {result.get('n_citations')}")
    console.print(
        f"reader-1 saw {len(approver)} events, reader-2 saw {len(watcher)}; identical: {approver == watcher}"
    )
    replay = await read(client, started.handler_id, "replay", approve=False)
    console.print(f"replayed after completion: {len(replay)} events; identical: {replay == approver}")


def main(
    question: str = typer.Argument(None, help="Default: config/topic.json default_question."),
    base_url: str = typer.Option(
        None, help="Default: http://WORKFLOWS_PY_SERVER_HOST:WORKFLOWS_PY_SERVER_PORT (127.0.0.1:8080)."
    ),
) -> None:
    host = os.environ.get("WORKFLOWS_PY_SERVER_HOST", "127.0.0.1")
    port = os.environ.get("WORKFLOWS_PY_SERVER_PORT", "8080")
    asyncio.run(
        run(
            question or Topic.load(CONFIG_DIR / "topic.json").default_question,
            base_url or f"http://{host}:{port}",
        )
    )


if __name__ == "__main__":
    typer.run(main)
