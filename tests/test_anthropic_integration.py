"""Exercise the real llama-index Anthropic code path with only the HTTP call faked.

Mock LLMs skip request building entirely, which is how an incompatible `anthropic` SDK
(2.x turned `MessageParam` into a Union) slipped past the other tests. See docs/decisions.md D5.
"""

import json

from anthropic.types import Message, TextBlock, Usage
from llama_index.core.llms import ChatMessage
from workflows.testing import WorkflowTestRunner

from litreview.config import get_settings
from litreview.resources import BudgetedAnthropic, get_cost_tracker
from litreview.workflows.smoke import Ask, SmokeWorkflow
from tests.conftest import override_resources


def _llm_with_fake_http(sent: list[dict]) -> BudgetedAnthropic:
    llm = BudgetedAnthropic(get_cost_tracker(), model="claude-haiku-5-5", max_tokens=50, api_key="x")

    async def fake_create(**kwargs):
        sent.append(kwargs)
        return Message(
            id="msg_test_1",
            type="message",
            role="assistant",
            model="claude-haiku-5-5",
            content=[TextBlock(type="text", text="Steps react to events.")],
            stop_reason="end_turn",
            usage=Usage(input_tokens=20, output_tokens=8),
        )

    llm._aclient.messages.create = fake_create  # type: ignore[method-assign]
    return llm


async def test_request_building_response_parsing_and_cost_ledger():
    sent: list[dict] = []
    llm = _llm_with_fake_http(sent)

    resp = await llm.achat([ChatMessage(role="user", content="hi")])

    assert resp.message.content == "Steps react to events."
    assert sent[0]["messages"] == [{"role": "user", "content": [{"type": "text", "text": "hi"}]}]
    assert (sent[0]["model"], sent[0]["max_tokens"]) == ("claude-haiku-5-5", 50)
    rows = [json.loads(x) for x in (get_settings().p2_runs_dir / "costs.jsonl").read_text().splitlines()]
    recorded = [(r["response_id"], r["input_tokens"], r["output_tokens"]) for r in rows]
    assert recorded == [("msg_test_1", 20, 8)]


async def test_smoke_workflow_end_to_end_with_real_integration():
    from litreview.resources import get_llm

    manager = await override_resources({get_llm: _llm_with_fake_http([])})

    r = await WorkflowTestRunner(SmokeWorkflow(timeout=10, resource_manager=manager)).run(Ask())

    assert r.result == "Steps react to events."
