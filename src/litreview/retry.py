"""Shared retry policies (spec §11), built from the composable `workflows.retry_policy` blocks.

Retries happen in the workflow runtime, not in client libraries: the Anthropic LLM is built with
max_retries=0 and the arXiv client has no retry loop, so every retry is visible to the step via
`ctx.retry_info()` and on the stream.
"""

from __future__ import annotations

import anthropic
import httpx
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

    This is a custom RetryPolicy: anything with this `next(...)` method works. M4 adds a second one.
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

# Anthropic: only transient errors. BudgetExceeded, auth and bad-request errors fail immediately.
LLM_RETRY = Scaled(
    retry_policy(
        retry=retry_if_exception_type(
            (
                anthropic.RateLimitError,
                anthropic.OverloadedError,
                anthropic.InternalServerError,
                anthropic.ServiceUnavailableError,
                anthropic.APIConnectionError,  # includes APITimeoutError
            )
        ),
        wait=wait_exponential_jitter(initial=2, max=30),
        stop=stop_after_attempt(4),
    )
)
