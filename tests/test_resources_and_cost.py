import json
from types import SimpleNamespace

import pytest
from llama_index.core.base.llms.types import ChatMessage, ChatResponse
from llama_index.core.instrumentation.events.llm import LLMChatEndEvent
from workflows.resource import Resource, ResourceManager
from workflows.testing import WorkflowTestRunner

from litreview import cost
from litreview.resources import BudgetedAnthropic, get_cost_tracker, get_llm, shared_resources
from litreview.workflows.smoke import Ask, SmokeWorkflow
from tests.fakes import ScriptedLLM

PRICES = {"claude-haiku-5-5": {"input": 0.10, "cache_write": 0.125, "cache_read": 0.01, "output": 0.50}}


async def test_smoke_workflow_uses_the_injected_llm():
    fake = ScriptedLLM(script={"event-driven": "Steps react to events."}, calls=[])
    manager = await shared_resources({get_llm: fake})

    r = await WorkflowTestRunner(SmokeWorkflow(timeout=10, resource_manager=manager)).run(Ask())

    assert r.result == "Steps react to events."
    assert len(fake.calls) == 1


async def test_chained_resource_builds_haiku_from_json_config():
    # Resolves the real chain (ResourceConfig -> LLMConfig, plus the cost-tracker Resource)
    # but makes no API call: constructing the client is offline.
    llm = await ResourceManager().get(Resource(get_llm))

    assert isinstance(llm, BudgetedAnthropic)
    assert (llm.model, llm.max_tokens) == ("claude-haiku-5-5", 1500)


def test_price_math_and_snapshot_model_ids(tmp_path):
    t = cost.CostTracker(tmp_path / "c.jsonl", 10, PRICES)
    usage = SimpleNamespace(
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
    )

    assert t.price("claude-haiku-5-5", usage) == pytest.approx(0.60)
    assert t.price("claude-haiku-5-5-20261001", usage) == pytest.approx(0.60)
    with pytest.raises(KeyError):
        t.price("claude-unknown", usage)


def test_ledger_dedupes_replayed_responses_and_survives_restart(tmp_path):
    ledger = tmp_path / "c.jsonl"
    t = cost.CostTracker(ledger, 10, PRICES)
    usage = {"input_tokens": 1000, "output_tokens": 100}

    t.record("claude-haiku-5-5", usage, "msg_1")
    t.record("claude-haiku-5-5", usage, "msg_1")  # same response replayed after a resume

    assert len(ledger.read_text().splitlines()) == 1
    reopened = cost.CostTracker(ledger, 10, PRICES)
    assert reopened.spent_usd == pytest.approx(t.spent_usd)
    assert reopened.record("claude-haiku-5-5", usage, "msg_1") == 0.0


def test_instrumentation_handler_records_anthropic_responses(tmp_path):
    t = cost.CostTracker(tmp_path / "c.jsonl", 10, PRICES)
    handler = cost.CostEventHandler(tracker=t)
    raw = {"id": "msg_9", "model": "claude-haiku-5-5", "usage": {"input_tokens": 10, "output_tokens": 5}}
    msg = ChatMessage(role="assistant", content="hi")

    handler.handle(LLMChatEndEvent(messages=[], response=ChatResponse(message=msg, raw=raw)))
    handler.handle(LLMChatEndEvent(messages=[], response=ChatResponse(message=msg)))  # MockLLM: ignored

    rows = [json.loads(line) for line in (tmp_path / "c.jsonl").read_text().splitlines()]
    assert [r["response_id"] for r in rows] == ["msg_9"]


async def test_budget_guard_blocks_the_call_before_any_network(monkeypatch):
    monkeypatch.setenv("P2_SPEND_CAP_USD", "0")
    from litreview.config import get_settings

    get_settings.cache_clear()
    llm = BudgetedAnthropic(get_cost_tracker(), model="claude-haiku-5-5", max_tokens=10, api_key="x")

    with pytest.raises(cost.BudgetExceeded):
        await llm.achat([ChatMessage(role="user", content="hi")])
