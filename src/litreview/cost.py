"""Append-only cost ledger and the $10 budget guard.

Every Anthropic response becomes one JSON line in `runs/costs.jsonl` (same shape as P1's ledger).
Recording happens in a LlamaIndex *instrumentation* event handler, so any LLM call anywhere
(a workflow step, a query engine, an agent) is counted without the caller doing anything.

The guard cannot live in that handler: the instrumentation dispatcher swallows handler
exceptions. So `BudgetedAnthropic` (resources.py) calls `CostTracker.check()` before each request.
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from llama_index.core.instrumentation.event_handlers import BaseEventHandler
from llama_index.core.instrumentation.events import BaseEvent
from llama_index.core.instrumentation.events.llm import LLMChatEndEvent
from llama_index_instrumentation import get_dispatcher

from litreview.config import CONFIG_DIR

PROJECT = "p2"


class BudgetExceeded(RuntimeError):
    """Raised before an LLM call once cumulative spend has reached the cap. Never retried."""


def load_prices(path: Path = CONFIG_DIR / "prices.json") -> dict[str, dict[str, float]]:
    return {k: v for k, v in json.loads(path.read_text()).items() if not k.startswith("_")}


def _get(obj: Any, key: str) -> Any:
    """Anthropic usage arrives as an SDK object (non-streaming) or a dict (streaming)."""
    return obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)


class CostTracker:
    """Owns the ledger file. One per process: the handler that feeds it is registered globally."""

    def __init__(self, ledger: Path, cap_usd: float, prices: dict[str, dict[str, float]]) -> None:
        self.ledger = ledger
        self.cap_usd = cap_usd
        self.prices = prices
        self._lock = threading.Lock()
        self._seen: set[str] = set()
        self._spent = 0.0
        if ledger.exists():
            for line in ledger.read_text().splitlines():
                row = json.loads(line)
                self._spent += row["cost_usd"]
                if row.get("response_id"):
                    self._seen.add(row["response_id"])

    @property
    def spent_usd(self) -> float:
        return self._spent

    def check(self) -> None:
        if self._spent >= self.cap_usd:
            raise BudgetExceeded(f"spent ${self._spent:.4f} of ${self.cap_usd:.2f} cap")

    def price(self, model: str, usage: Any) -> float:
        # The API may echo a dated snapshot id (claude-haiku-5-5-2026...), so match on prefix.
        key = next((k for k in self.prices if model == k or model.startswith(k + "-")), None)
        if key is None:
            raise KeyError(f"no price for {model!r} in config/prices.json")
        p = self.prices[key]
        tokens = {
            "input": _get(usage, "input_tokens") or 0,
            "cache_write": _get(usage, "cache_creation_input_tokens") or 0,
            "cache_read": _get(usage, "cache_read_input_tokens") or 0,
            "output": _get(usage, "output_tokens") or 0,
        }
        return sum(tokens[k] * p[k] for k in tokens) / 1_000_000

    def record(self, model: str, usage: Any, response_id: str | None, step: str | None = None) -> float:
        # A resumed run is at-least-once: a replayed response keeps its id, so skip it.
        if response_id and response_id in self._seen:
            return 0.0
        cost = self.price(model, usage)
        row = {
            "ts": datetime.now(UTC).isoformat(),
            "project": PROJECT,
            "model": model,
            "step": step,
            "input_tokens": _get(usage, "input_tokens") or 0,
            "output_tokens": _get(usage, "output_tokens") or 0,
            "cost_usd": round(cost, 6),
            "response_id": response_id,
        }
        with self._lock:
            self.ledger.parent.mkdir(parents=True, exist_ok=True)
            with self.ledger.open("a") as f:
                f.write(json.dumps(row) + "\n")
            self._spent += cost
            if response_id:
                self._seen.add(response_id)
        return cost


class CostEventHandler(BaseEventHandler):
    """Instrumentation hook: turns each finished Anthropic chat into a ledger row."""

    tracker: Any

    @classmethod
    def class_name(cls) -> str:
        return "CostEventHandler"

    def handle(self, event: BaseEvent, **kwargs: Any) -> None:
        if not isinstance(event, LLMChatEndEvent) or event.response is None:
            return
        raw = event.response.raw or {}
        usage, model = _get(raw, "usage"), _get(raw, "model")
        # No model: a MockLLM, or the last chunk of a stream (BudgetedAnthropic records those itself).
        if usage is None or model is None:
            return
        self.tracker.record(model, usage, _get(raw, "id"))


_handler: CostEventHandler | None = None


def install(tracker: CostTracker) -> None:
    """Point the (single, global) instrumentation handler at `tracker`."""
    global _handler
    if _handler is None:
        _handler = CostEventHandler(tracker=tracker)
        get_dispatcher().add_event_handler(_handler)
    else:
        _handler.tracker = tracker
