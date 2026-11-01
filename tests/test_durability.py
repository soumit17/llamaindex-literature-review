"""M5: the ingestion checkpoint loop. A run is stopped mid-way; a *new workflow instance* resumes it."""

import json
from pathlib import Path

import pytest
from workflows.events import StepState, StepStateChanged

from litreview.config import get_settings
from litreview.durability import Interrupted, run_checkpointed
from litreview.events import IngestProgress, IngestReport, IngestRequest
from litreview.resources import get_arxiv_client, get_embed_model, get_llm, shared_resources
from litreview.workflows.ingestion import IngestionWorkflow
from tests.fakes import CountingEmbedding, FakePdfServer, InstantClock, ScriptedLLM
from tests.ingest_env import IDS, PDFS

STEPS = {"index_paper", "summarize_paper"}


async def make_workflow(llm: ScriptedLLM) -> IngestionWorkflow:
    from litreview.corpus import ArxivClient, CorpusPaths, RateLimiter

    clock = InstantClock()
    server = FakePdfServer(bodies=PDFS)
    client = ArxivClient(
        CorpusPaths(get_settings().p2_data_dir).cache,
        http=server.client(),
        limiter=RateLimiter(3, clock=clock.clock, sleep=clock.sleep),
    )
    manager = await shared_resources(
        {get_arxiv_client: client, get_llm: llm, get_embed_model: CountingEmbedding.make()}
    )
    return IngestionWorkflow(timeout=60, resource_manager=manager)


def first_summary_done(ev) -> bool:
    return (
        isinstance(ev, StepStateChanged)
        and ev.name == "summarize_paper"
        and ev.step_state == StepState.NOT_RUNNING
    )


@pytest.fixture
def checkpoint(tmp_path) -> Path:
    return tmp_path / "runs" / "checkpoints" / "ingest.json"


async def test_resume_after_interruption_finishes_without_redoing_work(corpus, checkpoint):
    llm1 = ScriptedLLM(default="summary")
    with pytest.raises(Interrupted):
        await run_checkpointed(
            await make_workflow(llm1),
            IngestRequest(),
            checkpoint,
            STEPS,
            every=0,
            stop_after=first_summary_done,
        )
    assert checkpoint.exists()

    # "New process": a fresh workflow instance and fresh fakes, only the files on disk carry over.
    llm2 = ScriptedLLM(default="summary")
    seen: list = []
    resumed: list[bool] = []
    report = await run_checkpointed(
        await make_workflow(llm2),
        IngestRequest(),
        checkpoint,
        STEPS,
        every=0,
        on_event=seen.append,
        on_resume=lambda: resumed.append(True),
    )

    assert resumed == [True]
    assert isinstance(report, IngestReport)
    assert report.papers == len(IDS)  # the list fan-in counted branches finished in *both* runs
    assert not [e for e in seen if isinstance(e, IngestProgress) and e.stage == "start"]  # no re-start
    stages = {e.stage for e in seen if isinstance(e, IngestProgress)}
    assert len(llm2.calls) >= 1 and "fetch" not in stages  # real leftover work, finished steps skipped
    assert len(llm1.calls) + len(llm2.calls) == len(IDS)  # no summary paid for twice
    assert not checkpoint.exists()  # removed after a completed run

    docstore = json.loads((corpus.root / "storage" / "docstore.json").read_text())["docstore/data"]
    texts = [(d["__data__"]["metadata"]["arxiv_id"], d["__data__"]["text"]) for d in docstore.values()]
    assert len(texts) == len(set(texts))  # no duplicated chunks
    assert {a for a, _ in texts} == set(IDS)


async def test_without_checkpoint_it_is_a_normal_run(corpus, checkpoint):
    report = await run_checkpointed(
        await make_workflow(ScriptedLLM(default="s")), IngestRequest(), checkpoint, STEPS, every=0
    )
    assert report.papers == len(IDS) and not checkpoint.exists()


async def test_chunk_ids_are_deterministic(corpus, checkpoint):
    await run_checkpointed(await make_workflow(ScriptedLLM(default="s")), IngestRequest(), checkpoint, STEPS)
    ids = json.loads((corpus.root / "storage" / "docstore.json").read_text())["docstore/data"].keys()
    assert all(i.startswith(tuple(IDS)) and "/" in i for i in ids)  # "<arxiv_id>#<segment>/<chunk>"
