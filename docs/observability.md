# Observability

Every run is traced. With the default `OTEL_EXPORTER=file`, spans go to `runs/traces/spans.jsonl`; with
`OTEL_EXPORTER=otlp` they also go to Phoenix (or any OTLP/HTTP backend).

```bash
uvx --from arize-phoenix phoenix serve          # once, in its own terminal: UI at http://localhost:6006
OTEL_EXPORTER=otlp uv run litreview review --yes
uv run python scripts/trace_summary.py          # the same trace as a tree in the terminal, no backend needed
```

What a review trace looks like: one `ReviewWorkflow.run` span; a span per step under it (attributes
`llamaindex.run_id`, `llamaindex.step.input_event`); retrieval, reranking and LLM spans under the steps
that made them; `CitationCheckWorkflow.run` nested under `check_citations`; and the custom
`quote_in_chunk` spans (`litreview/quotes.py`, `@dispatcher.span`) carrying a `CitationChecked` event
with the match score.

## The four captures (spec §15)

Paste a screenshot (Phoenix) or the `trace_summary.py` output under each.

### 1. Parallel research

`uv run litreview review --yes`, then `uv run python scripts/trace_summary.py`. Four
`ReviewWorkflow.research` spans start together (the `num_workers=4` limit); the script prints
`peak concurrency per step: ... research 4`.

_(capture)_

### 2. A retried step and 3. a catch_error recovery ($0)

`uv run litreview ingest --fail 2308.00352` (forces `fetch_pdf` to fail for that paper), then
`uv run python scripts/trace_summary.py --root Ingestion`. Four `IngestionWorkflow.fetch_pdf` spans for
that paper with status error (the retry policy), then one `IngestionWorkflow.on_fetch_failure` span
(the `@catch_error` handler), and the run still ends with `persist`.

_(capture)_

### 4. Where the money goes

`uv run litreview cost --by-step` after a review: calls, tokens and cost per workflow step (recorded
since M8; earlier rows show as "not recorded"), and how many calls were cut off at max_tokens.

_(table)_

## Notes (yours)

- Which step costs the most, and is that where you expected?
- How much of a review's wall time is retrieval + reranking vs LLM calls?
