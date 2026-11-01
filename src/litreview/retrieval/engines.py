"""Query side of the retrieval layer (spec §9.2, §9.3).

    question ─▶ [router: LLM picks one] ─┬─▶ vector retriever    top-12 chunks by embedding
                                         └─▶ summary retriever   all chunks of the 2 papers whose
                                                                 summaries match best
             ─▶ reranker (cross-encoder) ─▶ top-5 chunks

Everything is wrapped in a `RetrieverQueryEngine`: `.retrieve()` runs retriever + reranker and returns
nodes without any LLM answer (what M4's `research` step and the eval use); `.query()` also synthesizes
an answer (used only for the SubQuestionQueryEngine comparison).

Every LlamaIndex object here gets its LLM and embed model passed explicitly: when one is omitted,
LlamaIndex falls back to the global `Settings`, whose default is OpenAI (not installed).

The summary index reuses the per-paper summaries from ingestion: `StoredSummarySynthesizer` hands
DocumentSummaryIndex the saved text instead of asking an LLM, so building it costs $0.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from llama_index.core import StorageContext, VectorStoreIndex, load_index_from_storage
from llama_index.core.base.embeddings.base import BaseEmbedding
from llama_index.core.base.response.schema import Response
from llama_index.core.indices.document_summary import (
    DocumentSummaryIndex,
    DocumentSummaryIndexEmbeddingRetriever,
)
from llama_index.core.llms import LLM, MockLLM
from llama_index.core.postprocessor.types import BaseNodePostprocessor
from llama_index.core.prompts.mixin import PromptDictType
from llama_index.core.query_engine import RetrieverQueryEngine
from llama_index.core.response_synthesizers import BaseSynthesizer, get_response_synthesizer
from llama_index.core.retrievers import BaseRetriever, RouterRetriever
from llama_index.core.schema import (
    MetadataMode,
    NodeRelationship,
    NodeWithScore,
    QueryBundle,
    RelatedNodeInfo,
    TextNode,
)
from llama_index.core.selectors import LLMSingleSelector
from llama_index.core.tools import RetrieverTool
from pydantic import BaseModel, PrivateAttr

VECTOR_DESCRIPTION = (
    "Specific passages from the papers. Use for questions about a particular mechanism, method, "
    "experiment, result, number, or design detail."
)
SUMMARY_DESCRIPTION = (
    "Whole-paper summaries. Use for overview questions: which papers address a topic, what a line of "
    "work proposes overall, or how approaches compare at a high level."
)


class QueryConfig(BaseModel):
    top_k: int = 12  # candidates from the vector retriever
    rerank_top_n: int = 5  # chunks kept after reranking (spec §21: <= 5 chunks per research call)
    summary_top_papers: int = 2  # papers the summary retriever expands into chunks
    router: bool = True
    rerank: bool = True


# ---------- reranker ----------
class FastEmbedRerank(BaseNodePostprocessor):
    """Cross-encoder reranker on fastembed's ONNX runtime (no PyTorch).

    Same role as LlamaIndex's SentenceTransformerRerank: score every (query, chunk) pair jointly,
    keep the best `top_n`. A cross-encoder reads query and chunk together, so it judges relevance
    better than comparing two separately computed embeddings, but it is too slow to run over the
    whole corpus; hence retrieve 12 cheaply, rerank to 5.
    """

    model: str = "Xenova/ms-marco-MiniLM-L-6-v2"
    top_n: int = 5
    cache_dir: str | None = None
    _encoder: Any = PrivateAttr(default=None)

    @classmethod
    def class_name(cls) -> str:
        return "FastEmbedRerank"

    def _postprocess_nodes(
        self, nodes: list[NodeWithScore], query_bundle: QueryBundle | None = None
    ) -> list[NodeWithScore]:
        if query_bundle is None or not nodes:
            return nodes[: self.top_n]
        if self._encoder is None:  # lazy: the 80 MB model loads on first use, not at import
            from fastembed.rerank.cross_encoder import TextCrossEncoder

            self._encoder = TextCrossEncoder(model_name=self.model, cache_dir=self.cache_dir)
        texts = [n.node.get_content(metadata_mode=MetadataMode.EMBED) for n in nodes]
        scores = list(self._encoder.rerank(query_bundle.query_str, texts))
        ranked = sorted(zip(nodes, scores, strict=True), key=lambda pair: pair[1], reverse=True)
        return [NodeWithScore(node=n.node, score=float(s)) for n, s in ranked[: self.top_n]]


# ---------- summary index ----------
class StoredSummarySynthesizer(BaseSynthesizer):
    """Answers DocumentSummaryIndex's "summarize this document" request with the saved summary."""

    def __init__(self, summaries: dict[str, str]) -> None:
        super().__init__(llm=MockLLM())  # never called; avoids the Settings.llm (OpenAI) default
        self._summaries = summaries

    def synthesize(self, query: Any, nodes: list[NodeWithScore], **kwargs: Any) -> Response:  # type: ignore[override]
        arxiv_id = nodes[0].node.ref_doc_id if nodes else None
        return Response(response=self._summaries.get(arxiv_id or "", ""))

    async def asynthesize(self, query: Any, nodes: list[NodeWithScore], **kwargs: Any) -> Response:  # type: ignore[override]
        return self.synthesize(query, nodes, **kwargs)

    def get_response(self, *args: Any, **kwargs: Any) -> str:
        raise NotImplementedError("summaries come from data/summaries, not from an LLM")

    async def aget_response(self, *args: Any, **kwargs: Any) -> str:
        raise NotImplementedError("summaries come from data/summaries, not from an LLM")

    def _get_prompts(self) -> PromptDictType:
        return {}

    def _update_prompts(self, prompts_dict: PromptDictType) -> None:
        pass


def _regroup_by_paper(vector_index: VectorStoreIndex, papers: set[str]) -> list[TextNode]:
    """Copies of the chunk nodes whose source is the *paper* (ingestion's source is a page segment).

    DocumentSummaryIndex groups nodes by `ref_doc_id`. Node ids stay identical, so a citation means
    the same chunk whichever index retrieved it; the copies live in their own docstore so the
    vector index's nodes keep their original source.
    """
    nodes = []
    for node in vector_index.docstore.docs.values():
        arxiv_id = node.metadata.get("arxiv_id")
        if arxiv_id in papers and isinstance(node, TextNode):
            copy = node.model_copy()
            copy.relationships = {NodeRelationship.SOURCE: RelatedNodeInfo(node_id=arxiv_id)}
            copy.embedding = None  # the summary index embeds summaries, not chunks
            nodes.append(copy)
    return nodes


def ensure_summary_index(
    vector_index: VectorStoreIndex, summaries: dict[str, str], embed_model: BaseEmbedding, persist_dir: Path
) -> bool:
    """(Re)build the summary index when its papers or chunks changed. Returns True if it rebuilt."""
    nodes = _regroup_by_paper(vector_index, set(summaries))
    manifest_path = persist_dir / "manifest.json"
    # The chunk ids, not just their count: a rebuild with new ids must rebuild this index too.
    ids_digest = hashlib.sha1("".join(sorted(n.node_id for n in nodes)).encode()).hexdigest()
    manifest = {"papers": sorted(summaries), "nodes": len(nodes), "node_ids_sha1": ids_digest}
    if manifest_path.exists() and json.loads(manifest_path.read_text()) == manifest:
        return False
    index = DocumentSummaryIndex(
        nodes=nodes,
        embed_model=embed_model,
        llm=MockLLM(),  # only DocumentSummaryIndexLLMRetriever would use it; we use the embedding one
        response_synthesizer=StoredSummarySynthesizer(summaries),
        embed_summaries=True,
        show_progress=False,
    )
    index.storage_context.persist(persist_dir=str(persist_dir))
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return True


def load_summary_index(persist_dir: Path, embed_model: BaseEmbedding) -> DocumentSummaryIndex:
    context = StorageContext.from_defaults(persist_dir=str(persist_dir))
    index = load_index_from_storage(
        context, embed_model=embed_model, llm=MockLLM(), response_synthesizer=StoredSummarySynthesizer({})
    )
    assert isinstance(index, DocumentSummaryIndex)
    return index


# ---------- composition ----------
def make_retriever(
    vector_index: VectorStoreIndex,
    summary_index: DocumentSummaryIndex | None,
    config: QueryConfig,
    llm: LLM | None,
    embed_model: BaseEmbedding,
) -> BaseRetriever:
    vector = vector_index.as_retriever(similarity_top_k=config.top_k, embed_model=embed_model)
    if not config.router or summary_index is None:
        return vector
    if llm is None:
        raise ValueError("the router needs an LLM to choose between retrievers")
    summary = DocumentSummaryIndexEmbeddingRetriever(
        summary_index, similarity_top_k=config.summary_top_papers, embed_model=embed_model
    )
    return RouterRetriever(
        selector=LLMSingleSelector.from_defaults(llm=llm),
        retriever_tools=[
            RetrieverTool.from_defaults(retriever=vector, description=VECTOR_DESCRIPTION),
            RetrieverTool.from_defaults(retriever=summary, description=SUMMARY_DESCRIPTION),
        ],
        llm=llm,
    )


def make_query_engine(
    retriever: BaseRetriever, config: QueryConfig, reranker: BaseNodePostprocessor | None, llm: LLM | None
) -> RetrieverQueryEngine:
    postprocessors: list[BaseNodePostprocessor] = (
        [reranker]
        if config.rerank and reranker is not None
        else [_TopN(top_n=config.rerank_top_n)]  # keep "@5" honest without a reranker
    )
    return RetrieverQueryEngine(
        retriever=retriever,
        node_postprocessors=postprocessors,
        # Explicit LLM: otherwise LlamaIndex falls back to Settings.llm (OpenAI by default).
        response_synthesizer=get_response_synthesizer(llm=llm) if llm is not None else _RetrievalOnly(),
    )


class _TopN(BaseNodePostprocessor):
    top_n: int = 5

    def _postprocess_nodes(
        self, nodes: list[NodeWithScore], query_bundle: QueryBundle | None = None
    ) -> list[NodeWithScore]:
        return nodes[: self.top_n]


class _RetrievalOnly(BaseSynthesizer):
    """For engines built without an LLM: `.retrieve()` works, `.query()` fails loudly."""

    def __init__(self) -> None:
        super().__init__(llm=MockLLM())  # never called; avoids the Settings.llm (OpenAI) default

    def get_response(self, *args: Any, **kwargs: Any) -> str:
        raise RuntimeError("retrieval-only query engine: build it with an LLM to call .query()")

    async def aget_response(self, *args: Any, **kwargs: Any) -> str:
        raise RuntimeError("retrieval-only query engine: build it with an LLM to call .query()")

    def _get_prompts(self) -> PromptDictType:
        return {}

    def _update_prompts(self, prompts_dict: PromptDictType) -> None:
        pass
