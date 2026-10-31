"""Deterministic stand-ins for live services."""

from __future__ import annotations

from typing import Any

from llama_index.core.llms import CompletionResponse, CompletionResponseGen, CustomLLM, LLMMetadata
from llama_index.core.llms.callbacks import llm_completion_callback


class ScriptedLLM(CustomLLM):
    """Returns a canned reply chosen by a tag found in the prompt, e.g. "[PLAN]" -> plan JSON.

    Later milestones give each prompt a tag so structured-output steps get exact, valid JSON.
    `calls` records every prompt, so tests can count LLM calls (e.g. "no re-spend after resume").
    """

    script: dict[str, str] = {}
    default: str = "ok"
    calls: list[str] = []

    @property
    def metadata(self) -> LLMMetadata:
        return LLMMetadata(model_name="scripted")

    def _reply(self, prompt: str) -> str:
        self.calls.append(prompt)
        return next((reply for tag, reply in self.script.items() if tag in prompt), self.default)

    @llm_completion_callback()
    def complete(self, prompt: str, formatted: bool = False, **kwargs: Any) -> CompletionResponse:
        return CompletionResponse(text=self._reply(prompt))

    @llm_completion_callback()
    def stream_complete(self, prompt: str, formatted: bool = False, **kwargs: Any) -> CompletionResponseGen:
        text = self._reply(prompt)
        yield CompletionResponse(text=text, delta=text)


# ---------- arXiv ----------
def make_result(short_id: str, title: str = "A Paper", year: int = 2025) -> Any:
    """A real `arxiv.Result`, as the library would parse it from the API feed."""
    from datetime import UTC, datetime

    import arxiv

    return arxiv.Result(
        entry_id=f"http://arxiv.org/abs/{short_id}",
        published=datetime(year, 1, 2, tzinfo=UTC),
        title=f"{title}\n  with a line break",
        authors=[arxiv.Result.Author("Ada Lovelace"), arxiv.Result.Author("Alan Turing")],
        summary="We study\nagents.",
        primary_category="cs.MA",
        categories=["cs.MA", "cs.AI"],
    )


class FakeArxivApi:
    """Stands in for `arxiv.Client`: answers searches from a fixed list, id lookups by id."""

    def __init__(self, results: list[Any], extra: list[Any] | None = None) -> None:
        self.results_list = results
        self.by_id = {r.get_short_id().rpartition("v")[0]: r for r in results + (extra or [])}
        self.searches: list[Any] = []

    def results(self, search: Any, offset: int = 0) -> Any:
        self.searches.append(search)
        if search.id_list:
            return [self.by_id[i.rpartition("v")[0] if "v" in i else i] for i in search.id_list]
        return self.results_list[: search.max_results]


class FakePdfServer:
    """httpx transport serving fake PDFs; `fail` maps arxiv_id -> HTTP status to return instead."""

    def __init__(
        self,
        fail: dict[str, int] | None = None,
        body: bytes | None = None,
        bodies: dict[str, bytes] | None = None,
        fail_times: dict[str, int] | None = None,
    ) -> None:
        self.fail = fail or {}  # always answer with this status
        self.fail_times = dict(fail_times or {})  # answer 503 this many times, then succeed
        self.body = body
        self.bodies = bodies or {}
        self.hits: list[str] = []

    def handler(self, request: Any) -> Any:
        import httpx

        versioned = request.url.path.removeprefix("/pdf/")
        self.hits.append(versioned)
        arxiv_id = versioned.rpartition("v")[0]
        if arxiv_id in self.fail:
            return httpx.Response(self.fail[arxiv_id])
        if self.fail_times.get(arxiv_id, 0) > 0:
            self.fail_times[arxiv_id] -= 1
            return httpx.Response(503)
        body = self.bodies.get(arxiv_id) or self.body or f"%PDF-1.7 fake {versioned}".encode()
        return httpx.Response(200, content=body)

    def client(self) -> Any:
        import httpx

        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))


class InstantClock:
    """Fake clock + sleep for RateLimiter: sleeping advances time instead of waiting."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


# ---------- ingestion ----------
def make_paper_pdf(title: str, topic_word: str) -> bytes:
    """A 3-page PDF shaped like an arXiv paper, exercising every parse clean-up rule: running header,
    page numbers, a split "1" / "Introduction" heading, a hyphenated line break, a table caption,
    and a References section that must be cut."""
    import pymupdf

    pages = [
        [
            title,
            "Ada Lovelace and Alan Turing",
            "Abstract",
            f"We study {topic_word} coordination among language model agents in detail.",
            "1",
            "Introduction",
            "Multi-agent systems need orches-",
            f"tration. This paper studies {topic_word} patterns for agent teams at scale.",
        ],
        [
            "2",
            "Method",
            f"Our {topic_word} orchestrator assigns roles and routes messages between worker agents.",
            "Table 1: Accuracy by topology",
            "3",
            "GPT-4 85.2 90.1",
            "3",
            "Conclusion",
            f"The {topic_word} design improves task accuracy by twelve points over a single agent.",
        ],
        ["References", "[1] A. Author. Some cited paper about unrelated things. 2023."],
    ]
    doc = pymupdf.open()
    for i, lines in enumerate(pages, start=1):
        page = doc.new_page()
        page.insert_text((72, 40), "Preprint. Under review.", fontsize=8)
        page.insert_text((72, 90), "\n".join(lines), fontsize=10)
        page.insert_text((300, 800), str(i), fontsize=8)
    data = doc.tobytes()
    doc.close()
    return data


class CountingEmbedding:
    """Factory for a MockEmbedding that counts how many texts it embedded.

    The counter is a private attribute on purpose: IngestionCache keys include the embed model's
    fields (`to_dict()`), so a public counter would change the key and defeat the cache.
    """

    @staticmethod
    def make(dim: int = 8) -> Any:
        from llama_index.core.embeddings import MockEmbedding
        from pydantic import PrivateAttr

        class _Counting(MockEmbedding):
            _texts: int = PrivateAttr(default=0)

            @property
            def texts_embedded(self) -> int:
                return self._texts

            # Count only here: BaseEmbedding's batch method loops over this one.
            def _get_text_embedding(self, text: str) -> list[float]:
                self._texts += 1
                return super()._get_text_embedding(text)

        return _Counting(embed_dim=dim)
