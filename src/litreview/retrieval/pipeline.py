"""IngestionPipeline + VectorStoreIndex storage (spec §9.1, §9.2).

How a paper becomes searchable chunks:

    data/parsed/<id>.jsonl ──Documents──▶ IngestionPipeline [splitter → embed_model]
                                              │ docstore: skips documents it has seen (same id + hash)
                                              │ cache: skips transformations it has run (same input)
                                              ▼
                                       new nodes, already embedded ──insert_nodes──▶ VectorStoreIndex

Why the pipeline does not write to the vector store itself: `SimpleVectorStore` keeps embeddings but
not text, so retrieval needs the nodes in the index's docstore too. `insert_nodes` puts them in
both, and skips embedding because the nodes already carry one.

On disk (all JSON):
    data/storage/            index: docstore.json, default__vector_store.json, index_store.json
    data/storage/pipeline/   the pipeline's docstore (seen-document hashes)
    data/cache/ingestion/    the pipeline's transformation cache; outside storage/ so it survives
                             `--rebuild`, which therefore re-splits but does not re-embed
"""

from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path
from typing import Literal

from llama_index.core import Document, StorageContext, VectorStoreIndex, load_index_from_storage
from llama_index.core.base.embeddings.base import BaseEmbedding
from llama_index.core.ingestion import DocstoreStrategy, IngestionCache, IngestionPipeline
from llama_index.core.node_parser import NodeParser, SemanticSplitterNodeParser, SentenceSplitter
from llama_index.core.schema import BaseNode
from llama_index.core.storage.docstore import SimpleDocumentStore
from pydantic import BaseModel

# Kept out of the embedded text: ids and numbers add noise to similarity. The LLM still sees them.
EMBED_EXCLUDED_METADATA = ["arxiv_id", "page", "year", "heading"]


class SplitterConfig(BaseModel):
    kind: Literal["sentence", "semantic"] = "sentence"
    chunk_size: int = 512
    chunk_overlap: int = 64
    breakpoint_percentile: int = 95  # semantic only


def ensure_nltk_data(cache_dir: Path) -> None:
    """Make LlamaIndex's bundled NLTK data loadable, without touching the network.

    NLTK >= 3.10 refuses data directories that other accounts could write to. With a group-writable
    umask (0002) the copy inside .venv is rejected, and SentenceSplitter then fails. So copy it to
    a private directory and point NLTK_DATA there; LlamaIndex reads that variable.
    """
    if os.environ.get("NLTK_DATA"):
        return
    import llama_index.core

    target = cache_dir / "nltk_data"
    if not target.exists():
        bundled = Path(llama_index.core.__file__).parent / "_static" / "nltk_cache"
        tmp = target.with_name("nltk_data.tmp")
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.copytree(bundled, tmp)
        for root, dirs, files in os.walk(tmp):
            for name in dirs + files:
                p = Path(root, name)
                p.chmod(p.stat().st_mode & ~(stat.S_IWGRP | stat.S_IWOTH))
        tmp.chmod(0o755)
        tmp.replace(target)
    os.environ["NLTK_DATA"] = str(target)


def make_splitter(config: SplitterConfig, embed_model: BaseEmbedding) -> NodeParser:
    if config.kind == "semantic":
        return SemanticSplitterNodeParser(
            embed_model=embed_model,
            breakpoint_percentile_threshold=config.breakpoint_percentile,
            id_func=chunk_id,
        )
    return SentenceSplitter(
        chunk_size=config.chunk_size, chunk_overlap=config.chunk_overlap, id_func=chunk_id
    )


def chunk_id(i: int, doc: BaseNode) -> str:
    """Deterministic chunk ids ("2308.00352#004/1": segment 4, chunk 1) instead of uuid4.

    Re-indexing the same segment yields the same ids, so a resumed run (at-least-once) overwrites a
    chunk instead of duplicating it, and a citation's node_id survives `ingest --rebuild`.
    """
    return f"{doc.node_id}/{i}"


def documents_from_segments(rows: list[dict]) -> list[Document]:
    """One Document per parsed segment; a deterministic id is what lets the docstore dedupe."""
    docs = []
    for i, row in enumerate(rows):
        metadata = {k: v for k, v in row.items() if k != "text"}
        docs.append(
            Document(
                text=row["text"],
                id_=f"{row['arxiv_id']}#{i:03d}",
                metadata=metadata,
                excluded_embed_metadata_keys=EMBED_EXCLUDED_METADATA,
            )
        )
    return docs


class Storage:
    """The pipeline and the index it feeds, loaded from and saved to disk together."""

    def __init__(self, storage_dir: Path, cache_dir: Path, splitter: NodeParser, embed_model: BaseEmbedding):
        self.storage_dir = storage_dir
        self.cache_path = cache_dir / "ingestion" / "cache.json"
        self.pipeline_docstore_path = storage_dir / "pipeline" / "docstore.json"

        if (storage_dir / "docstore.json").exists():
            context = StorageContext.from_defaults(persist_dir=str(storage_dir))
            index = load_index_from_storage(context, embed_model=embed_model)
            assert isinstance(index, VectorStoreIndex)
            self.index = index
        else:
            self.index = VectorStoreIndex(nodes=[], embed_model=embed_model)

        self.pipeline = IngestionPipeline(
            transformations=[splitter, embed_model],
            docstore=(
                SimpleDocumentStore.from_persist_path(str(self.pipeline_docstore_path))
                if self.pipeline_docstore_path.exists()
                else SimpleDocumentStore()
            ),
            cache=(
                IngestionCache.from_persist_path(str(self.cache_path))
                if self.cache_path.exists()
                else IngestionCache()
            ),
            # Explicit: without a vector store attached, "upserts" silently falls back to this anyway.
            docstore_strategy=DocstoreStrategy.DUPLICATES_ONLY,
        )

    def ingest(self, documents: list[Document]) -> int:
        """Split + embed only unseen documents, add them to the index. Returns the new node count.

        Blocking (CPU-bound embedding): steps call it through `asyncio.to_thread`.
        """
        nodes = self.pipeline.run(documents=documents)
        stale = [n.node_id for n in nodes if "/" not in n.node_id]
        if stale:  # a cache hit returns the *stored* nodes, ids included (see chunk_id)
            raise RuntimeError(
                f"the embedding cache predates deterministic chunk ids (e.g. {stale[0]}); run once: "
                "rm -rf data/cache/ingestion && uv run litreview ingest --rebuild"
            )
        if nodes:
            self.index.insert_nodes(nodes)
        return len(nodes)

    @property
    def n_nodes(self) -> int:
        return len(self.index.docstore.docs)

    def persist(self) -> None:
        """Write everything to a temp dir, then move each file into place with an atomic rename, so
        a kill -9 mid-write never leaves a truncated JSON file. The pipeline docstore (which says
        "these documents are done") goes last: if we die before it, the documents are re-ingested,
        and deterministic chunk ids make that an overwrite, not a duplicate."""
        assert self.pipeline.docstore is not None and self.pipeline.cache is not None
        tmp = self.storage_dir.with_name(self.storage_dir.name + ".tmp")
        shutil.rmtree(tmp, ignore_errors=True)
        self.index.storage_context.persist(persist_dir=str(tmp))
        self.pipeline.cache.persist(str(tmp / "cache.json"))
        self.pipeline.docstore.persist(str(tmp / "pipeline_docstore.json"))
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        for f in sorted(tmp.glob("*.json")):
            if f.name not in ("cache.json", "pipeline_docstore.json"):
                os.replace(f, self.storage_dir / f.name)
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        os.replace(tmp / "cache.json", self.cache_path)
        self.pipeline_docstore_path.parent.mkdir(parents=True, exist_ok=True)
        os.replace(tmp / "pipeline_docstore.json", self.pipeline_docstore_path)
        shutil.rmtree(tmp, ignore_errors=True)
