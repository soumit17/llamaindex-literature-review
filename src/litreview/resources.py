"""Resource factories injected into workflow steps (spec §5.4).

Resources hold everything that must NOT be on events or in `ctx.store`: clients, models, indexes.
They are never serialized, which is what keeps snapshots and durability working.

Caching (verified in llama-index-workflows 2.26.1): a `cache=True` resource is stored on the
Workflow instance's ResourceManager, so it lives as long as that Workflow object, i.e. across
runs of the same instance, not just one run.

Tests replace a resource by pre-seeding a ResourceManager under the factory's name; see
`tests/conftest.py::override_resources`.
"""

from __future__ import annotations

from typing import Annotated, Any

from llama_index.llms.anthropic import Anthropic
from pydantic import BaseModel, PrivateAttr
from workflows.resource import Resource, ResourceConfig

from litreview import cost
from litreview.config import CONFIG_DIR, get_settings


class LLMConfig(BaseModel):
    model: str
    temperature: float
    max_tokens: int  # always set (spec rule 8): caps spend per call


def get_cost_tracker() -> cost.CostTracker:
    s = get_settings()
    tracker = cost.CostTracker(s.p2_runs_dir / "costs.jsonl", s.p2_spend_cap_usd, cost.load_prices())
    cost.install(tracker)
    return tracker


class BudgetedAnthropic(Anthropic):
    """Anthropic LLM that refuses to call the API once the spend cap is reached."""

    _tracker: cost.CostTracker = PrivateAttr()

    def __init__(self, tracker: cost.CostTracker, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._tracker = tracker

    def chat(self, messages, **kwargs):  # type: ignore[override]
        self._tracker.check()
        return super().chat(messages, **kwargs)

    async def achat(self, messages, **kwargs):  # type: ignore[override]
        self._tracker.check()
        return await super().achat(messages, **kwargs)

    def stream_chat(self, messages, **kwargs):  # type: ignore[override]
        self._tracker.check()
        return super().stream_chat(messages, **kwargs)

    async def astream_chat(self, messages, **kwargs):  # type: ignore[override]
        self._tracker.check()
        return await super().astream_chat(messages, **kwargs)


# Chained resource: the framework resolves `config` (JSON -> LLMConfig via ResourceConfig) and
# `tracker` (another Resource) first, then calls this factory with both.
# path_selector="dev" picks the Haiku block of config/llm.json; the Sonnet "final" block arrives in M4.
def get_llm(
    config: Annotated[
        LLMConfig, ResourceConfig(config_file=str(CONFIG_DIR / "llm.json"), path_selector="dev")
    ],
    tracker: Annotated[cost.CostTracker, Resource(get_cost_tracker)],
) -> BudgetedAnthropic:
    return BudgetedAnthropic(
        tracker,
        model=config.model,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        api_key=get_settings().anthropic_api_key or None,
    )
