"""Shared fixture corpus for workflow tests: three generated PDFs, a lock file and papers.json."""

import hashlib
from dataclasses import dataclass, field
from typing import Any

from workflows.testing import WorkflowTestRunner

from litreview.config import get_settings
from litreview.corpus import (
    ArxivClient,
    CorpusLock,
    CorpusPaths,
    LockedPaper,
    PaperMeta,
    RateLimiter,
    save_papers,
)
from litreview.events import IngestRequest
from litreview.resources import get_arxiv_client, get_embed_model, get_llm, shared_resources
from litreview.workflows.ingestion import IngestionWorkflow
from tests.fakes import CountingEmbedding, FakePdfServer, InstantClock, ScriptedLLM, make_paper_pdf

IDS = ["2501.00001", "2501.00002", "2501.00003"]
PDFS = {
    i: make_paper_pdf(f"Paper {n}", w)
    for n, (i, w) in enumerate(zip(IDS, ["hub", "ring", "tree"], strict=True), 1)
}


@dataclass
class Env:
    """One "process": a fresh workflow instance with its own fakes, over the shared tmp data dir."""

    server: FakePdfServer = field(default_factory=FakePdfServer)
    llm: Any = field(default_factory=lambda: ScriptedLLM(default="A short summary of the paper."))
    embed: Any = field(default_factory=CountingEmbedding.make)

    async def run(self, **request: Any):
        paths = CorpusPaths(get_settings().p2_data_dir)
        clock = InstantClock()
        self.server.bodies = PDFS
        client = ArxivClient(
            paths.cache,
            http=self.server.client(),
            limiter=RateLimiter(3, clock=clock.clock, sleep=clock.sleep),
        )
        manager = await shared_resources(
            {get_arxiv_client: client, get_llm: self.llm, get_embed_model: self.embed}
        )
        wf = IngestionWorkflow(timeout=60, resource_manager=manager)
        return await WorkflowTestRunner(wf).run(IngestRequest(**request))


def make_corpus() -> CorpusPaths:
    """A lock file + papers.json for three fixture papers, as scripts/fetch_corpus.py would write."""
    paths = CorpusPaths(get_settings().p2_data_dir)
    lock = CorpusLock(
        query="q",
        created="2026-10-30",
        papers=[LockedPaper(arxiv_id=i, version=1, sha256=hashlib.sha256(PDFS[i]).hexdigest()) for i in IDS],
    )
    lock.save(paths.lock)
    metas = [
        PaperMeta(
            arxiv_id=i,
            version=1,
            title=f"Paper {n}",
            authors=["Ada Lovelace"],
            year=2025,
            published="2025-01-02",
            abstract=f"Abstract of paper {n}.",
            categories=["cs.MA"],
            primary_category="cs.MA",
            abs_url=f"https://arxiv.org/abs/{i}v1",
        )
        for n, i in enumerate(IDS, 1)
    ]
    save_papers(paths.papers, metas)
    return paths
