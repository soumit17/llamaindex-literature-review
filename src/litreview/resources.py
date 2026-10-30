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

from llama_index.core.base.embeddings.base import BaseEmbedding
from llama_index.llms.anthropic import Anthropic
from pydantic import BaseModel, PrivateAttr
from workflows.resource import Resource, ResourceConfig

from litreview import cost
from litreview.config import CONFIG_DIR, get_settings
from litreview.corpus import ArxivClient, CorpusPaths, PaperMeta, Topic, load_papers
from litreview.retrieval.pipeline import SplitterConfig, Storage, ensure_nltk_data, make_splitter


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
        # The SDK would otherwise retry up to 10 times on its own, invisibly. Retries belong to the
        # step's retry_policy (litreview.retry.LLM_RETRY), where ctx.retry_info() can see them.
        max_retries=0,
    )


# cache=True (the default) on purpose: every step that asks for the client gets the same instance,
# so its single RateLimiter spaces *all* arXiv requests 3 s apart, even across parallel workers.
def get_arxiv_client() -> ArxivClient:
    return ArxivClient(CorpusPaths(get_settings().p2_data_dir).cache)


def get_topic() -> Topic:
    return Topic.load(CONFIG_DIR / "topic.json")


def get_papers() -> dict[str, PaperMeta]:
    """papers.json by arxiv_id: titles, years and abstracts for parsing metadata and summaries."""
    return {p.arxiv_id: p for p in load_papers(CorpusPaths(get_settings().p2_data_dir).papers)}


def get_embed_model() -> BaseEmbedding:
    """Local embeddings (Anthropic has no embeddings API). First use downloads the ONNX model
    (~130 MB) into .cache/fastembed; after that it runs offline."""
    from llama_index.embeddings.fastembed import FastEmbedEmbedding

    s = get_settings()
    return FastEmbedEmbedding(model_name=s.embed_model, cache_dir=str(s.p2_cache_dir / "fastembed"))


# Chained twice: config/retrieval.json -> SplitterConfig, plus the embed model, -> Storage.
# One cached Storage per workflow instance, so index_paper and persist share the same index.
def get_storage(
    splitter_config: Annotated[
        SplitterConfig,
        ResourceConfig(config_file=str(CONFIG_DIR / "retrieval.json"), path_selector="splitter"),
    ],
    embed_model: Annotated[BaseEmbedding, Resource(get_embed_model)],
) -> Storage:
    s = get_settings()
    ensure_nltk_data(s.p2_cache_dir)  # before the first SentenceSplitter is built
    return Storage(
        storage_dir=s.p2_data_dir / "storage",
        cache_dir=s.p2_data_dir / "cache",
        splitter=make_splitter(splitter_config, embed_model),
        embed_model=embed_model,
    )
