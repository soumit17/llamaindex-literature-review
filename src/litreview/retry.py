"""Shared retry policies (spec §11), built from the composable `workflows.retry_policy` blocks.

Retries happen in the workflow runtime, not in client libraries: the Anthropic LLM is built with
max_retries=0 and the arXiv client has no retry loop, so every retry is visible to the step via
`ctx.retry_info()` and on the stream.
"""

from __future__ import annotations

from typing import Any

import anthropic
import httpx
from pydantic import ValidationError
from workflows import Context
from workflows.retry_policy import (
    RetryPolicy,
    retry_if_exception_message,
    retry_if_exception_type,
    retry_policy,
    stop_after_attempt,
    stop_before_delay,
    wait_exponential_jitter,
)

from litreview.config import get_settings


class Scaled:
    """Multiplies another policy's delays by P2_RETRY_TIME_SCALE (1.0 normally; tests use 0).

    A custom RetryPolicy: anything with this `next(...)` method works (see also RetryAfterPolicy).
    """

    def __init__(self, inner: RetryPolicy) -> None:
        self.inner = inner

    def next(
        self, elapsed_time: float, attempts: int, error: Exception, *, seed: int | None = None
    ) -> float | None:
        delay = self.inner.next(elapsed_time, attempts, error, seed=seed)
        return None if delay is None else delay * get_settings().p2_retry_time_scale


# arXiv: network errors, rate limiting / unavailability, and the "PDF is being generated" HTML page.
# Not retried: hash mismatch (a real change) or a 404.
FETCH_RETRY = Scaled(
    retry_policy(
        retry=retry_if_exception_type((httpx.TransportError, ConnectionError, TimeoutError))
        | retry_if_exception_message(match=r"429|503|rate|not a PDF"),
        wait=wait_exponential_jitter(initial=3, max=60),
        stop=stop_after_attempt(4) | stop_before_delay(120),
    )
)


class RetryAfterPolicy:
    """Waits as long as the server asked (the `retry-after` header on a 429/529), capped at
    `max_wait`. Whether to retry at all, and the wait when there is no header, come from `fallback`.

    Compare with the composable built-ins: they decide from the exception type/message and elapsed
    time only, so they can't read a value the server sent along with the error.
    """

    def __init__(self, fallback: RetryPolicy, max_wait: float = 60.0) -> None:
        self.fallback = fallback
        self.max_wait = max_wait

    def next(
        self, elapsed_time: float, attempts: int, error: Exception, *, seed: int | None = None
    ) -> float | None:
        delay = self.fallback.next(elapsed_time, attempts, error, seed=seed)
        if delay is None:
            return None
        asked = retry_after_seconds(error)
        return min(asked, self.max_wait) if asked is not None else delay


def retry_after_seconds(error: Exception) -> float | None:
    headers: Any = getattr(getattr(error, "response", None), "headers", None) or {}
    for name, scale in (("retry-after-ms", 0.001), ("retry-after", 1.0)):
        value = headers.get(name)
        if value is None:
            continue
        try:
            return float(value) * scale
        except ValueError:  # an HTTP date instead of seconds: let the fallback decide
            return None
    return None


TRANSIENT_ANTHROPIC = (
    anthropic.RateLimitError,
    anthropic.OverloadedError,
    anthropic.InternalServerError,
    anthropic.ServiceUnavailableError,
    anthropic.APIConnectionError,  # includes APITimeoutError
)
# How LlamaIndex reports a structured output that didn't validate (function calling or text parsing).
STRUCTURED_FAILURE = (
    r"Structured output extraction failed|did not return any tool calls|Expected at least one tool call"
)

# Anthropic: transient errors, plus structured outputs that didn't validate (the step re-prompts
# with the error, see `fix_note`). BudgetExceeded, auth and bad-request errors fail immediately.
LLM_RETRY = Scaled(
    RetryAfterPolicy(
        retry_policy(
            retry=retry_if_exception_type((*TRANSIENT_ANTHROPIC, ValidationError))
            | retry_if_exception_message(match=STRUCTURED_FAILURE),
            wait=wait_exponential_jitter(initial=2, max=30),
            stop=stop_after_attempt(4),
        )
    )
)


def fix_note(ctx: Context[Any]) -> str:
    """Text to append to a prompt when the previous attempt's structured output was rejected."""
    error = ctx.retry_info().last_exception
    if error is None or isinstance(error, TRANSIENT_ANTHROPIC):
        return ""
    return (
        f"\n\nYour previous answer was rejected: {str(error)[:500]}\n"
        "Return output that matches the required schema exactly."
    )
