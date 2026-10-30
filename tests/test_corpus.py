"""M1: arXiv client, lock file and the fetch flow, all against fakes (no network)."""

import asyncio
import json

import httpx
import pytest

from litreview.corpus import (
    ArxivClient,
    CorpusLock,
    CorpusPaths,
    LockedPaper,
    PaperMeta,
    RateLimiter,
    Topic,
    download_all,
    ensure_papers_json,
    gather_candidates,
    new_lock,
    parse_selection,
    save_papers,
    sha256_file,
    split_version,
)
from tests.fakes import FakeArxivApi, FakePdfServer, InstantClock, make_result

RESULTS = [make_result(f"2501.0000{i}v{i}", title=f"Paper {i}") for i in range(1, 6)]
SUGGESTED = make_result("2308.08155v2", title="AutoGen")
TOPIC = Topic(
    topic="t", query="q", max_results=5, target_papers=3, suggested_ids=["2308.08155", "2501.00001"]
)


def make_client(paths: CorpusPaths, server: FakePdfServer | None = None, api=None) -> ArxivClient:
    clock = InstantClock()
    return ArxivClient(
        paths.cache,
        api=api or FakeArxivApi(RESULTS, extra=[SUGGESTED]),
        http=(server or FakePdfServer()).client(),
        limiter=RateLimiter(3.0, clock=clock.clock, sleep=clock.sleep),
    )


@pytest.fixture
def paths(tmp_path) -> CorpusPaths:
    return CorpusPaths(tmp_path / "data")


# ---------- pure helpers ----------
def test_split_version_handles_new_and_old_ids():
    assert split_version("2308.00352v7") == ("2308.00352", 7)
    assert split_version("cs/0112017v1") == ("cs/0112017", 1)
    with pytest.raises(ValueError):
        split_version("2308.00352")


def test_paper_meta_from_result_cleans_text():
    p = PaperMeta.from_result(RESULTS[2])
    assert (p.arxiv_id, p.version, p.versioned_id) == ("2501.00003", 3, "2501.00003v3")
    assert p.title == "Paper 3 with a line break"
    assert p.abstract == "We study agents."
    assert p.authors[0] == "Ada Lovelace" and p.year == 2025


@pytest.mark.parametrize(
    ("text", "expected"),
    [("1-3,5", [0, 1, 2, 4]), (" 2 , 2-3 ", [1, 2]), ("all", [0, 1, 2, 3, 4])],
)
def test_parse_selection(text, expected):
    assert parse_selection(text, 5) == expected


@pytest.mark.parametrize("text", ["0", "6", "3-1", "x", "", "1-"])
def test_parse_selection_rejects_bad_input(text):
    with pytest.raises(ValueError):
        parse_selection(text, 5)


def test_old_style_ids_get_a_safe_filename(paths):
    assert paths.pdf("cs/0112017").name == "cs_0112017.pdf"


# ---------- rate limiting ----------
async def test_rate_limiter_spaces_concurrent_callers_3s_apart():
    clock = InstantClock()
    limiter = RateLimiter(3.0, clock=clock.clock, sleep=clock.sleep)
    times = []

    async def call():
        await limiter.wait()
        times.append(clock.now)

    await asyncio.gather(*(call() for _ in range(4)))  # like num_workers=4 hitting arXiv at once
    assert times == [0.0, 3.0, 6.0, 9.0]


# ---------- caching ----------
async def test_search_is_cached_on_disk(paths):
    api = FakeArxivApi(RESULTS)
    first = make_client(paths, api=api)
    assert len(await first.search("q", 5)) == 5
    second = make_client(paths, api=api)  # a later process
    assert len(await second.search("q", 5)) == 5
    assert (first.requests, second.requests, len(api.searches)) == (1, 0, 1)


async def test_search_warms_the_metadata_cache(paths):
    client = make_client(paths)
    await client.search("q", 5)
    metas = await client.lookup(["2501.00002v2", "2501.00004"])
    assert [m.title for m in metas] == ["Paper 2 with a line break", "Paper 4 with a line break"]
    assert client.requests == 1  # only the search


async def test_candidates_append_suggestions_not_already_found(paths):
    client = make_client(paths)
    cands = await gather_candidates(client, TOPIC)
    assert [c.paper.arxiv_id for c in cands if c.suggested] == ["2308.08155"]  # 2501.00001 deduped
    assert len(cands) == 6 and client.requests == 2  # one search + one id lookup


# ---------- downloads ----------
async def test_download_is_idempotent_and_verifies_hash(paths):
    server = FakePdfServer()
    client = make_client(paths, server)
    paper = LockedPaper(arxiv_id="2501.00001", version=1)
    dest = paths.pdf(paper.arxiv_id)

    digest, downloaded = await client.download_pdf(paper, dest)
    assert downloaded and dest.read_bytes().startswith(b"%PDF") and digest == sha256_file(dest)
    assert server.hits == ["2501.00001v1"]  # versioned URL: the lock reproduces this exact file

    paper.sha256 = digest
    assert await client.download_pdf(paper, dest) == (digest, False)
    assert client.requests == 1

    dest.write_bytes(b"%PDF corrupted")  # damaged file: hash no longer matches the lock
    assert await client.download_pdf(paper, dest) == (digest, True)
    assert sha256_file(dest) == digest


async def test_html_instead_of_pdf_is_an_error_and_writes_nothing(paths):
    client = make_client(paths, FakePdfServer(body=b"<html>being generated</html>"))
    paper = LockedPaper(arxiv_id="2501.00001", version=1)
    with pytest.raises(ValueError, match="not a PDF"):
        await client.download_pdf(paper, paths.pdf(paper.arxiv_id))
    assert not paths.pdf(paper.arxiv_id).exists()


async def test_rate_limit_status_surfaces_as_http_error_mentioning_429(paths):
    client = make_client(paths, FakePdfServer(fail={"2501.00001": 429}))
    with pytest.raises(httpx.HTTPStatusError, match="429"):  # what M2's retry_policy will match
        await client.download_pdf(LockedPaper(arxiv_id="2501.00001", version=1), paths.pdf("2501.00001"))


# ---------- the whole M1 flow ----------
async def _first_run(paths: CorpusPaths, server: FakePdfServer) -> CorpusLock:
    client = make_client(paths, server)
    cands = await gather_candidates(client, TOPIC)
    chosen = [cands[i].paper for i in parse_selection("1-2,6", len(cands))]
    lock = new_lock(TOPIC.query, chosen)
    lock.save(paths.lock)
    save_papers(paths.papers, chosen)
    report = await download_all(client, lock, paths)
    assert report.downloaded == ["2501.00001", "2501.00002", "2308.08155"] and not report.failed
    return lock


async def test_rerun_with_lock_makes_zero_network_requests(paths):
    """Spec M1 acceptance: a re-run makes 0 network calls."""
    await _first_run(paths, FakePdfServer())

    lock = CorpusLock.load(paths.lock)
    assert lock is not None and all(p.sha256 for p in lock.papers)  # hashes recorded
    server = FakePdfServer()
    client = make_client(paths, server)
    await ensure_papers_json(client, lock, paths)
    report = await download_all(client, lock, paths)
    assert report.kept == [p.arxiv_id for p in lock.papers]
    assert client.requests == 0 and server.hits == []


async def test_fresh_clone_rebuilds_papers_json_from_lock_in_one_request(paths):
    lock = await _first_run(paths, FakePdfServer())
    paths.papers.unlink()  # git-ignored, so a fresh clone only has the lock...
    for f in paths.cache.rglob("*.json"):
        f.unlink()  # ...and no cache
    client = make_client(paths)
    metas = await ensure_papers_json(client, lock, paths)
    assert [m.versioned_id for m in metas] == ["2501.00001v1", "2501.00002v2", "2308.08155v2"]
    assert client.requests == 1
    assert len(json.loads(paths.papers.read_text())) == 3


async def test_one_failed_download_does_not_stop_the_rest(paths):
    lock = new_lock("q", [PaperMeta.from_result(r) for r in RESULTS[:3]])
    client = make_client(paths, FakePdfServer(fail={"2501.00002": 503}))
    report = await download_all(client, lock, paths)
    assert list(report.failed) == ["2501.00002"]
    assert report.downloaded == ["2501.00001", "2501.00003"]
    saved = CorpusLock.load(paths.lock)
    assert saved is not None and [p.sha256 is not None for p in saved.papers] == [True, False, True]
