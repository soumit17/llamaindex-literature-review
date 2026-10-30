# LitReview (P2): LlamaIndex Workflows

Turns a research question into a cited mini literature review over ~25 arXiv papers.
Full spec: [p2-llamaindex-workflows-literature-review.md](p2-llamaindex-workflows-literature-review.md).
Version pins and every deviation from the spec: [docs/decisions.md](docs/decisions.md).

**Status:** M0 (scaffold and Workflows fundamentals) done.

## Setup

```bash
uv sync                      # creates .venv (Python 3.12) from uv.lock
cp .env.example .env         # then put your ANTHROPIC_API_KEY in .env
uv run pytest                # $0: network is blocked, no model calls
```

## M0: run it yourself

| Command | Cost | What to look at |
|---|---|---|
| `uv run litreview hello Ada` | $0 | The `Progress` events streamed by the loop, then the custom stop event |
| `uv run litreview hello Ada --debug-steps` | $0 | Internal `StepStateChanged` events: each step going `running` → `not_running`, and which event it consumed and produced |
| `uv run litreview hello ""` | $0 | The branch: `start` returns `Greeted` directly and `tick` never runs |
| `uv run litreview tiny` | $0 | The same engine with steps written as plain functions |
| `uv run litreview draw` | $0 | Writes `docs/hello_flow.html` (open it in a browser) and `docs/hello_flow.md` |
| `uv run litreview smoke` | ~$0.0001 | One live Haiku call through the injected LLM Resource |
| `uv run litreview cost` | $0 | Spend so far from `runs/costs.jsonl` |

## How a Workflows run flows

There is no graph definition anywhere. Each `@step` declares the event type it accepts (its
parameter annotation) and what it can emit (its return annotation). At run time:

1. `wf.run(start_event=Greet(...))` puts the start event on the queue.
2. The runtime finds the step whose input type matches **exactly** (`start` takes `Greet`) and runs it.
3. Whatever it returns becomes the next event. `Tick` routes to `tick`; `Greeted` is a `StopEvent`, so the run ends.
4. **Branch:** return a different event type (`start -> Tick | Greeted`).
   **Loop:** a step returns the type it consumes (`tick: Tick -> Tick | Done`).
   **Parallelism:** return a `list[Event]` (from M2 on).
5. Side-channel progress goes to `ctx.write_event_to_stream(...)`; the caller reads `handler.stream_events()`.
6. Shared run data lives in typed state (`Context[HelloState]`), changed atomically under `async with ctx.store.edit_state()`.
7. Heavy objects (LLM clients, indexes) are **Resources**: declared as `Annotated[T, Resource(factory)]` on a
   step parameter and injected by the framework, never stored on events or in state.

`litreview draw` turns those type annotations into the diagram, which is the easiest way to see it.

## Where each M0 concept lives

| Concept | Code |
|---|---|
| Custom StartEvent / StopEvent, branch, loop, streaming, typed state, `edit_state` | [src/litreview/workflows/hello.py](src/litreview/workflows/hello.py) |
| Unbound-function workflow | [src/litreview/workflows/tiny_unbound.py](src/litreview/workflows/tiny_unbound.py) |
| Resource injection into a step | [src/litreview/workflows/smoke.py](src/litreview/workflows/smoke.py) |
| Chained Resource + `ResourceConfig` (JSON → Pydantic) | `get_llm` in [src/litreview/resources.py](src/litreview/resources.py) |
| Cost ledger (instrumentation handler) and budget guard | [src/litreview/cost.py](src/litreview/cost.py) |
| Caller side: `stream_events(expose_internal=...)` | `_run_streaming` in [src/litreview/cli.py](src/litreview/cli.py) |
| `WorkflowTestRunner`, overriding Resources with fakes | [tests/](tests/), `override_resources` in [tests/conftest.py](tests/conftest.py) |
| Drawing | `draw` in [src/litreview/cli.py](src/litreview/cli.py), output in [docs/](docs/) |

## M1: build the corpus

```bash
uv run python scripts/fetch_corpus.py                 # search, pick ~25 from the list, download
uv run python scripts/fetch_corpus.py                 # again: expect "network requests: 0"
uv run python scripts/fetch_corpus.py --repick        # change your pick (search is cached: 0 requests)
```

What happens, in order:

1. **Search** (`config/topic.json` query, 40 hits) plus the ★ suggestions, one request each.
   Both are cached in `data/cache/arxiv/`, so later runs never search again.
2. **You pick** with ranges like `1-20,23,41-44`.
3. **Lock**: `data/corpus.lock.json` records each paper's id, version and (after download) sha256.
   Commit it: it is the reproducible definition of the corpus. `data/papers.json` (metadata for
   BibTeX) is git-ignored and rebuilt from the lock with one request on a fresh clone.
4. **Download** `https://arxiv.org/pdf/<id>v<version>` into `data/pdfs/`, one request every 3 s.
   A file whose hash matches the lock is kept, a damaged one is fetched again, an HTML
   "PDF being generated" page is rejected. Ctrl-C is safe: files are written to a temp name and renamed.

| Piece | Where |
|---|---|
| Rate limiter shared by every request | `RateLimiter` in [corpus.py](src/litreview/corpus.py) |
| Disk cache, idempotent hashed download | `ArxivClient` in [corpus.py](src/litreview/corpus.py) |
| Lock + metadata files | `CorpusLock`, `PaperMeta` in [corpus.py](src/litreview/corpus.py) |
| Resource that M2 will inject | `get_arxiv_client` in [resources.py](src/litreview/resources.py) |
| Interactive pick | [scripts/fetch_corpus.py](scripts/fetch_corpus.py) |

## M2: ingestion workflow

```bash
uv run litreview ingest --limit 2         # try 2 papers first (~1 min, ~$0.002)
uv run litreview ingest                   # all 25: ~5 min (CPU embedding), ~$0.02 of Haiku
uv run litreview ingest                   # again: ~5 s, 0 new chunks, $0
uv run litreview ingest --fail 2308.00352 # watch retries, then catch_error recovery (~30 s of backoff)
uv run litreview ingest --debug-steps     # see every step start/finish and its worker id
uv run litreview draw                     # docs/ingest_flow.md (+ .html): the graph from the types
uv run python scripts/splitter_experiment.py --only sentence-1024   # optional, $0, feeds M3
```

The first run downloads the embedding model (65 MB) into `.cache/fastembed`.

How events flow (no graph is written anywhere; it comes from the step signatures):

```
IngestRequest ─load_lock─▶ list[PaperToFetch]       fan-out: one branch per paper
  PaperToFetch ─fetch_pdf (2 workers, retried)─▶ PaperFetched        ─┐ failure after 4 attempts:
  PaperFetched ─parse_pdf (4 workers)─▶ PaperParsed                   │ on_fetch_failure records it,
  PaperParsed ─index_paper (1 worker)─▶ PaperIndexed                  │ the branch ends
  PaperIndexed ─summarize_paper (3 workers, retried)─▶ PaperSummarized
list[PaperSummarized] ─persist─▶ IngestReport       fan-in: fires once every branch has finished
```

| Concept | Where |
|---|---|
| Fan-out by returning a list | `load_lock` in [ingestion.py](src/litreview/workflows/ingestion.py) |
| List fan-in (stream join, no counting) | `persist` |
| `num_workers` and why each value | decorator comments on each step |
| Composable `retry_policy`, `ctx.retry_info()` | [retry.py](src/litreview/retry.py), `fetch_pdf` |
| Custom `RetryPolicy` (`Scaled`) | [retry.py](src/litreview/retry.py) |
| `@catch_error(for_steps=...)` returning `None` | `on_fetch_failure` |
| Typed state + `edit_state` under parallel workers | [state.py](src/litreview/state.py), every step |
| Resources: cached, chained, `ResourceConfig` with `path_selector` | `get_storage` in [resources.py](src/litreview/resources.py) |
| IngestionPipeline (docstore dedupe, cache) -> VectorStoreIndex | [pipeline.py](src/litreview/retrieval/pipeline.py) |
| PDF clean-up and section tagging | [parsing.py](src/litreview/retrieval/parsing.py) |
| Capped summary input (abstract + intro + conclusion) | [summaries.py](src/litreview/retrieval/summaries.py) |
| Execution drawing of the last run | `runs/ingest_execution.mermaid` |

On disk: `data/parsed/<id>.jsonl` (segments), `data/storage/` (index), `data/summaries/<id>.json`,
`data/cache/ingestion/` (embedding cache, survives `--rebuild`).
