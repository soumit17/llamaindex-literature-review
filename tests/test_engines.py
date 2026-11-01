"""M3: summary index from stored summaries, reranker, router, and the query-engine Resource."""

import json

import pytest
from llama_index.core.schema import NodeWithScore, QueryBundle, TextNode
from workflows.resource import Resource

from litreview.config import CONFIG_DIR
from litreview.resources import get_embed_model, get_llm, get_query_engine, get_reranker, get_storage
from litreview.retrieval.engines import (
    FastEmbedRerank,
    QueryConfig,
    ensure_summary_index,
    load_summary_index,
    make_query_engine,
    make_retriever,
)
from litreview.retrieval.summaries import load_all_summaries
from tests.conftest import override_resources
from tests.fakes import CountingEmbedding, ScriptedLLM
from tests.ingest_env import IDS


class WordOverlapEncoder:
    """Stand-in for fastembed's TextCrossEncoder: score = query words found in the text."""

    def rerank(self, query: str, texts: list[str]):
        words = set(query.lower().split())
        return [float(len(words & set(t.lower().split()))) for t in texts]


def fake_reranker(top_n: int = 5) -> FastEmbedRerank:
    reranker = FastEmbedRerank(top_n=top_n)
    reranker._encoder = WordOverlapEncoder()
    return reranker


async def test_ingest_builds_summary_index_from_saved_summaries(ingested):
    path = ingested.root / "storage" / "summary"
    assert json.loads((path / "manifest.json").read_text())["papers"] == IDS

    embed = CountingEmbedding.make()
    index = load_summary_index(path, embed)
    assert index.get_document_summary("2501.00002") == "Ring topology."  # the saved text, no LLM


async def test_summary_chunks_keep_vector_node_ids(ingested):
    manager = await override_resources({get_embed_model: CountingEmbedding.make()})
    storage = await manager.get(Resource(get_storage))
    index = load_summary_index(ingested.root / "storage" / "summary", CountingEmbedding.make())
    chunk_ids = {nid for s in index.index_struct.summary_id_to_node_ids.values() for nid in s}
    assert chunk_ids == set(storage.index.docstore.docs)  # same ids: a citation is the same chunk


async def test_summary_index_rebuilds_only_on_change(ingested):
    from llama_index.core import StorageContext, load_index_from_storage

    embed = CountingEmbedding.make()
    vector = load_index_from_storage(
        StorageContext.from_defaults(persist_dir=str(ingested.root / "storage")), embed_model=embed
    )
    summaries = load_all_summaries(ingested.root / "summaries")
    path = ingested.root / "storage" / "summary"
    assert ensure_summary_index(vector, summaries, embed, path) is False
    assert ensure_summary_index(vector, dict(list(summaries.items())[:2]), embed, path) is True


def test_reranker_reorders_and_truncates():
    nodes = [
        NodeWithScore(node=TextNode(text=t), score=0.9) for t in ["cats", "ring topology agents", "ring"]
    ]
    out = fake_reranker(top_n=2).postprocess_nodes(nodes, query_bundle=QueryBundle("ring topology"))
    assert [n.node.get_content() for n in out] == ["ring topology agents", "ring"]
    assert out[0].score == 2.0


async def test_retrieval_only_engine_returns_top5_and_refuses_query(ingested):
    from llama_index.core import StorageContext, load_index_from_storage

    embed = CountingEmbedding.make()
    vector = load_index_from_storage(
        StorageContext.from_defaults(persist_dir=str(ingested.root / "storage")), embed_model=embed
    )
    config = QueryConfig(router=False, rerank=False, top_k=12, rerank_top_n=5)
    engine = make_query_engine(make_retriever(vector, None, config, None, embed), config, None, None)
    nodes = engine.retrieve(QueryBundle("ring topology"))
    assert 0 < len(nodes) <= 5
    with pytest.raises(RuntimeError, match="retrieval-only"):
        engine.query("ring topology")


async def test_router_sends_overview_question_to_summaries(ingested):
    # Built directly with router=True: config/retrieval.json may have it off (M3's eval decides).
    from llama_index.core import StorageContext, load_index_from_storage

    embed = CountingEmbedding.make()
    vector = load_index_from_storage(
        StorageContext.from_defaults(persist_dir=str(ingested.root / "storage")), embed_model=embed
    )
    summary = load_summary_index(ingested.root / "storage" / "summary", embed)
    # LLMSingleSelector expects a JSON list of {choice (1-based), reason}; choice 2 = summary tool.
    selector_llm = ScriptedLLM(default='[{"choice": 2, "reason": "overview question"}]')
    config = QueryConfig(router=True, rerank=True)
    retriever = make_retriever(vector, summary, config, selector_llm, embed)
    engine = make_query_engine(retriever, config, fake_reranker(), selector_llm)
    nodes = engine.retrieve(QueryBundle("Which papers discuss ring topologies?"))

    assert len(selector_llm.calls) == 1  # one routing decision per question
    assert 0 < len(nodes) <= 5
    # The summary retriever expands its top papers into their chunks; all come from real papers.
    assert {n.node.metadata["arxiv_id"] for n in nodes} <= set(IDS)


async def test_query_engine_resource_follows_config(ingested):
    manager = await override_resources(
        {get_embed_model: CountingEmbedding.make(), get_llm: ScriptedLLM(), get_reranker: fake_reranker()}
    )
    engine = await manager.get(Resource(get_query_engine))
    assert 0 < len(engine.retrieve(QueryBundle("ring topology"))) <= 5


def test_query_config_comes_from_retrieval_json():
    config = json.loads((CONFIG_DIR / "retrieval.json").read_text())
    assert QueryConfig(**config["query"]).rerank_top_n == 5
