# Decisions log

## D1. Pinned versions (M0, 2026-10-30)

Python 3.12.15 (via `uv python pin`; the system Python 3.14 is too new for some ML wheels).
Exact pins live in `pyproject.toml` (`uv add --bounds exact`); `uv.lock` pins the whole tree.

| Package | Version | Used from |
|---|---|---|
| llama-index-workflows | 2.26.1 | M0 |
| llama-agents-server | 0.8.0 | M7 |
| llama-agents-dbos | 0.7.0 | M7 |
| llama-index-utils-workflow | 0.11.0 | M0 (drawing) |
| llama-index-core | 0.14.25 | M0 |
| llama-index-llms-anthropic | 0.12.3 | M0 |
| llama-index-embeddings-fastembed | 0.7.0 | M2 |
| llama-index-readers-file / pymupdf | 0.7.0 / 2.0 | M2 |
| llama-index-observability-otel / opentelemetry-sdk | 0.7.0 / 1.45.2 | M8 |
| arxiv | 4.0.2 | M1 |

**Deferred:** `sentence-transformers` (reranker). On Linux it pulls CUDA PyTorch (several GB).
Decide in M3: CPU-only torch index, or fastembed's ONNX cross-encoder for the same model.

## D2. The spec was written against Workflows 1.x; installed is 2.26.1

Verified against the installed source (no docs MCP was available in the first session):

| Spec says | Reality in 2.26.1 |
|---|---|
| `ctx.retry_info()` (fields unspecified) | `RetryInfo(retry_number, elapsed_seconds, last_exception, last_failed_at)`; `retry_number` is 0 on the first attempt |
| List fan-in "fires once all expected events arrived; check how the count is determined" | Stream-based: a step returning `list[E]` opens a stream; a `list[X]` parameter fires when every work item descended from that stream is done. No count. `Annotated[list[X], Collect(Take(n))]` fires early on the n-th. |
| `ctx.send_event` + list fan-in | `send_event` **cannot** add members to an open stream (ignored with a warning, or an error if targeted). Matters for the M5 revise loop. |
| `@catch_error` | `catch_error(for_steps=[...], max_recoveries=1)`; receives `StepFailedEvent(step_name, input_event, exception, attempts, elapsed_seconds, failed_at)` |
| `await handler` result | A custom StopEvent subclass is returned **as the instance**; a plain `StopEvent` returns `.result` |
| Resources "cached per run" | `cache=True` caches on the Workflow instance's `ResourceManager`, so across runs of the same instance |
| Overriding Resources in tests: "verify the cleanest way" | Pre-seed a `ResourceManager` under the factory's `__qualname__` and pass `Workflow(resource_manager=...)` (see `tests/conftest.py::override_resources`) |
| `num_workers` default | 4 |
| Mixing `llama_index.core.workflow` and `workflows` | Same objects (`llama_index.core.workflow.Workflow is workflows.Workflow`), so mixing is harmless |

Probe used to verify (fan-out over a 3-step chain, retry, catch_error sentinel, list fan-in, chained
ResourceConfig resource): one throwaway script, results recorded here.

## D3. Cost tracking

- Recording: a LlamaIndex instrumentation event handler on `LLMChatEndEvent` reads `raw.usage`, so
  every Anthropic call anywhere is counted. Ledger: `runs/costs.jsonl`, same row shape as P1.
- Guard: the instrumentation dispatcher **swallows handler exceptions**, so the cap can't be enforced
  there. `BudgetedAnthropic` (a thin `Anthropic` subclass) calls `CostTracker.check()` before each request.
- Prices: `config/prices.json`, copied from Anthropic's pricing page on 2026-10-30
  (Haiku 5.5 <=100k-token tier: $0.10 in / $0.50 out per MTok; Sonnet 5.5: $2 / $10). No `genai-prices`
  dependency (outside §19.2).
- Replayed responses (at-least-once resume) are deduped by Anthropic response id.

## D4. Model IDs

`claude-haiku-5-5` (dev) and `claude-sonnet-5-5` (final). Both are known to
llama-index-llms-anthropic 0.12.3 (context window lookup works).
