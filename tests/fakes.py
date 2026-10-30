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
