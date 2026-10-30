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

    def __init__(self, fail: dict[str, int] | None = None, body: bytes | None = None) -> None:
        self.fail = fail or {}
        self.body = body
        self.hits: list[str] = []

    def handler(self, request: Any) -> Any:
        import httpx

        versioned = request.url.path.removeprefix("/pdf/")
        self.hits.append(versioned)
        arxiv_id = versioned.rpartition("v")[0]
        if arxiv_id in self.fail:
            return httpx.Response(self.fail[arxiv_id])
        return httpx.Response(200, content=self.body or f"%PDF-1.7 fake {versioned}".encode())

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
