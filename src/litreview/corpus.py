"""arXiv corpus: a rate-limited, cached client plus the lock and metadata files (spec §4.1).

arXiv's API terms: at most one request every 3 seconds, cache everything, never re-download.
- One `RateLimiter` gates *every* request this client makes (search, metadata, PDFs), so
  concurrent callers (M2's `fetch_pdf` with num_workers=2) still queue up 3 s apart.
- Search results and per-paper metadata are cached as JSON under `data/cache/arxiv/`.
- PDFs are kept if their sha256 matches the lock file; downloads are versioned (`...v2`), so a
  lock file reproduces the exact same corpus later.

Everything here is plain data or a client, which is why M2 can inject `ArxivClient` as a Resource
and put only `arxiv_id`s on events.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import arxiv
import httpx
from pydantic import BaseModel

ARXIV_MIN_INTERVAL_S = 3.0
USER_AGENT = "litreview/0.1 (agentic-frameworks lab; personal research; respects 1 req/3s)"


# ---------- data ----------
class PaperMeta(BaseModel):
    """One paper's metadata; `data/papers.json` holds a list of these and feeds BibTeX later."""

    arxiv_id: str  # without version, e.g. "2308.00352"
    version: int
    title: str
    authors: list[str]
    year: int
    published: str  # ISO date
    abstract: str
    categories: list[str]
    primary_category: str
    abs_url: str
    doi: str | None = None
    journal_ref: str | None = None

    @property
    def versioned_id(self) -> str:
        return f"{self.arxiv_id}v{self.version}"

    @classmethod
    def from_result(cls, r: arxiv.Result) -> PaperMeta:
        arxiv_id, version = split_version(r.get_short_id())
        return cls(
            arxiv_id=arxiv_id,
            version=version,
            title=" ".join(r.title.split()),  # arXiv titles contain hard line breaks
            authors=[a.name for a in r.authors],
            year=r.published.year,
            published=r.published.date().isoformat(),
            abstract=" ".join(r.summary.split()),
            categories=list(r.categories),
            primary_category=r.primary_category,
            abs_url=f"https://arxiv.org/abs/{arxiv_id}v{version}",
            doi=r.doi or None,
            journal_ref=r.journal_ref or None,
        )


class LockedPaper(BaseModel):
    arxiv_id: str
    version: int
    sha256: str | None = None  # filled in once the PDF is on disk


class CorpusLock(BaseModel):
    """`data/corpus.lock.json`: the committed, reproducible definition of the corpus."""

    query: str
    created: str
    papers: list[LockedPaper]

    @classmethod
    def load(cls, path: Path) -> CorpusLock | None:
        return cls.model_validate_json(path.read_text()) if path.exists() else None

    def save(self, path: Path) -> None:
        _atomic_write(path, (self.model_dump_json(indent=2) + "\n").encode())


@dataclass(frozen=True)
class CorpusPaths:
    root: Path

    @property
    def lock(self) -> Path:
        return self.root / "corpus.lock.json"

    @property
    def papers(self) -> Path:
        return self.root / "papers.json"

    @property
    def pdfs(self) -> Path:
        return self.root / "pdfs"

    @property
    def cache(self) -> Path:
        return self.root / "cache" / "arxiv"

    def pdf(self, arxiv_id: str) -> Path:
        return self.pdfs / f"{arxiv_id.replace('/', '_')}.pdf"  # old-style ids contain "/"


def split_version(short_id: str) -> tuple[str, int]:
    """'2308.00352v7' -> ('2308.00352', 7); also handles old ids like 'cs/0112017v1'."""
    base, _, version = short_id.rpartition("v")
    if not base or not version.isdigit():
        raise ValueError(f"not a versioned arXiv id: {short_id!r}")
    return base, int(version)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _atomic_write(path: Path, data: bytes) -> None:
    """Write to a temp file, then rename: a crash never leaves a half-written file behind."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def save_papers(path: Path, papers: list[PaperMeta]) -> None:
    _atomic_write(path, (json.dumps([p.model_dump() for p in papers], indent=2) + "\n").encode())


def load_papers(path: Path) -> list[PaperMeta]:
    return [PaperMeta.model_validate(p) for p in json.loads(path.read_text())] if path.exists() else []


# ---------- client ----------
class RateLimiter:
    """Lets one request through per `min_interval` seconds, across every caller sharing it."""

    def __init__(
        self,
        min_interval: float = ARXIV_MIN_INTERVAL_S,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    ) -> None:
        self.min_interval = min_interval
        self._clock = clock
        self._sleep = sleep
        self._last: float | None = None
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            if self._last is not None:
                delay = self._last + self.min_interval - self._clock()
                if delay > 0:
                    await self._sleep(delay)
            self._last = self._clock()


class ArxivApi(Protocol):
    """The slice of `arxiv.Client` we use; tests pass a fake."""

    def results(self, search: arxiv.Search, offset: int = 0) -> Any: ...


class ArxivClient:
    """Rate-limited, disk-cached access to the arXiv API and PDFs. `requests` counts network calls."""

    def __init__(
        self,
        cache_dir: Path,
        *,
        api: ArxivApi | None = None,
        http: httpx.AsyncClient | None = None,
        limiter: RateLimiter | None = None,
    ) -> None:
        self.cache_dir = cache_dir
        self._api = api
        self._http = http
        self.limiter = limiter or RateLimiter()
        self.requests = 0

    async def __aenter__(self) -> ArxivClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._http is not None:
            await self._http.aclose()

    # -- metadata --
    async def search(self, query: str, max_results: int) -> list[PaperMeta]:
        key = hashlib.sha1(f"{query}|{max_results}".encode()).hexdigest()[:16]
        cached = self.cache_dir / f"search-{key}.json"
        if cached.exists():
            return [PaperMeta.model_validate(p) for p in json.loads(cached.read_text())]
        papers = await self._query(arxiv.Search(query=query, max_results=max_results), max_results)
        _atomic_write(cached, json.dumps([p.model_dump() for p in papers], indent=2).encode())
        return papers

    async def lookup(self, ids: list[str]) -> list[PaperMeta]:
        """Metadata for ids (versioned or not), cached per id; all misses go in one request."""
        found: dict[str, PaperMeta] = {}
        missing = []
        for i in ids:
            path = self._meta_path(i)
            if path.exists():
                found[i] = PaperMeta.model_validate_json(path.read_text())
            else:
                missing.append(i)
        if missing:
            for p in await self._query(arxiv.Search(id_list=missing, max_results=len(missing)), len(missing)):
                key = next((i for i in missing if i in (p.arxiv_id, p.versioned_id)), p.arxiv_id)
                found[key] = p
        return [found[i] for i in ids if i in found]

    async def _query(self, search: arxiv.Search, page_size: int) -> list[PaperMeta]:
        # page_size == what we want, so the arxiv library makes exactly one HTTP request.
        api = self._api or arxiv.Client(page_size=min(page_size, 2000), delay_seconds=ARXIV_MIN_INTERVAL_S)
        await self.limiter.wait()
        self.requests += 1
        results = await asyncio.to_thread(lambda: list(api.results(search)))
        papers = [PaperMeta.from_result(r) for r in results]
        for p in papers:  # warm the per-paper cache so later lookups cost nothing
            for key in (p.arxiv_id, p.versioned_id):
                _atomic_write(self._meta_path(key), p.model_dump_json(indent=2).encode())
        return papers

    def _meta_path(self, arxiv_id: str) -> Path:
        return self.cache_dir / "meta" / f"{arxiv_id.replace('/', '_')}.json"

    # -- PDFs --
    async def download_pdf(self, paper: LockedPaper, dest: Path) -> tuple[str, bool]:
        """Return (sha256, downloaded?). Idempotent: a file matching the lock's hash is kept as is.

        HTTP errors propagate as `httpx.HTTPStatusError` (message contains e.g. "429"), which
        M2's `retry_policy` matches on.
        """
        if dest.exists():
            digest = sha256_file(dest)
            if paper.sha256 in (None, digest):
                return digest, False
        if self._http is None:
            self._http = httpx.AsyncClient(
                headers={"User-Agent": USER_AGENT}, timeout=60, follow_redirects=True
            )
        await self.limiter.wait()
        self.requests += 1
        resp = await self._http.get(f"https://arxiv.org/pdf/{paper.arxiv_id}v{paper.version}")
        resp.raise_for_status()
        if not resp.content.startswith(b"%PDF"):  # arXiv sometimes answers with an HTML page
            raise ValueError(f"{paper.arxiv_id}: response is not a PDF ({resp.headers.get('content-type')})")
        digest = hashlib.sha256(resp.content).hexdigest()
        if paper.sha256 is not None and digest != paper.sha256:
            raise ValueError(
                f"{paper.arxiv_id}: sha256 {digest[:12]} does not match lock {paper.sha256[:12]}"
            )
        _atomic_write(dest, resp.content)
        return digest, True


# ---------- the M1 flow (used by scripts/fetch_corpus.py) ----------
class Topic(BaseModel):
    topic: str
    query: str
    max_results: int = 40
    target_papers: int = 25
    suggested_ids: list[str] = []

    @classmethod
    def load(cls, path: Path) -> Topic:
        return cls.model_validate_json(path.read_text())


@dataclass
class Candidate:
    paper: PaperMeta
    suggested: bool  # from topic.suggested_ids rather than the search


def parse_selection(text: str, n: int) -> list[int]:
    """'1-5, 8,10' -> [0,1,2,3,4,7,9] (1-based in, 0-based out). 'all' selects everything."""
    text = text.strip().lower()
    if text == "all":
        return list(range(n))
    chosen: set[int] = set()
    for part in filter(None, (p.strip() for p in text.split(","))):
        lo, dash, hi = part.partition("-")
        if not lo.isdigit() or (dash and not hi.isdigit()):
            raise ValueError(f"can't read {part!r}; use e.g. 1-5,8,10 or all")
        a, b = int(lo), int(hi or lo)
        if not 1 <= a <= b <= n:
            raise ValueError(f"{part!r} is outside 1-{n}")
        chosen.update(range(a - 1, b))
    if not chosen:
        raise ValueError("nothing selected")
    return sorted(chosen)


async def gather_candidates(client: ArxivClient, topic: Topic) -> list[Candidate]:
    found = await client.search(topic.query, topic.max_results)
    seen = {p.arxiv_id for p in found}
    extra = [i for i in topic.suggested_ids if i not in seen]
    suggested = await client.lookup(extra) if extra else []
    return [Candidate(p, False) for p in found] + [Candidate(p, True) for p in suggested]


@dataclass
class DownloadReport:
    downloaded: list[str]
    kept: list[str]
    failed: dict[str, str]


async def download_all(
    client: ArxivClient,
    lock: CorpusLock,
    paths: CorpusPaths,
    on_done: Callable[[str, str], None] = lambda arxiv_id, status: None,
) -> DownloadReport:
    """Fetch every locked PDF (skipping good files); the lock is saved after each new hash."""
    report = DownloadReport([], [], {})
    for paper in lock.papers:
        try:
            digest, downloaded = await client.download_pdf(paper, paths.pdf(paper.arxiv_id))
        except (httpx.HTTPError, ValueError) as e:
            report.failed[paper.arxiv_id] = str(e)
            on_done(paper.arxiv_id, "failed")
            continue
        (report.downloaded if downloaded else report.kept).append(paper.arxiv_id)
        if paper.sha256 != digest:
            paper.sha256 = digest
            lock.save(paths.lock)
        on_done(paper.arxiv_id, "downloaded" if downloaded else "kept")
    return report


def new_lock(query: str, chosen: list[PaperMeta]) -> CorpusLock:
    return CorpusLock(
        query=query,
        created=datetime.now(UTC).isoformat(timespec="seconds"),
        papers=[LockedPaper(arxiv_id=p.arxiv_id, version=p.version) for p in chosen],
    )


async def ensure_papers_json(client: ArxivClient, lock: CorpusLock, paths: CorpusPaths) -> list[PaperMeta]:
    """papers.json mirrors the lock; on a fresh clone it is rebuilt with one metadata request."""
    papers = {p.versioned_id: p for p in load_papers(paths.papers)}
    wanted = [f"{p.arxiv_id}v{p.version}" for p in lock.papers]
    if all(w in papers for w in wanted):
        return [papers[w] for w in wanted]
    metas = await client.lookup(wanted)
    save_papers(paths.papers, metas)
    return metas
