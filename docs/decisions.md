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
| anthropic (SDK) | 1.17.0 | M0, see D5 |

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

## D5. `anthropic` SDK pinned to 1.17.0 (not 2.x)

`llama-index-llms-anthropic==0.12.3` requires `anthropic>=0.75.0` with no upper bound, so uv
resolved `anthropic==2.3.0`. In 2.x `anthropic.types.MessageParam` became a `Union` of user /
assistant / system params, and the integration still calls `MessageParam(role=..., content=...)`,
so every chat fails with `TypeError: Cannot instantiate typing.Union` before any request is sent.

Fix: pin `anthropic==1.17.0` (last 1.x, `MessageParam` is still a TypedDict) as a direct dependency.
Revisit when a `llama-index-llms-anthropic` release supports 2.x.

Guard: `tests/test_anthropic_integration.py` runs the real integration code with only
`messages.create` faked. Mock LLMs skip request building, which is why the original tests missed this.
Verified that it fails on 2.3.0 (`uv run --with anthropic==2.3.0 pytest tests/test_anthropic_integration.py`).

## D6. M1 corpus acquisition

- **Query** (`config/topic.json`): title terms + categories cs.MA/cs.AI/cs.CL. A first, abstract-only
  query returned mostly applications (trading, medical, network slicing); the title-anchored one returns
  surveys and orchestration papers. Tried both live on 2026-10-30, one request each.
- **Suggested ids**: AutoGen 2308.08155, CAMEL 2303.17760, ChatDev 2307.07924, survey 2402.01680. The
  query misses them; they appear starred in the checklist and the developer decides.
- **arxiv 4.0.2 has no `Result.download_pdf`**, and its own 3 s throttle covers only its API calls on
  one `arxiv.Client`. So `ArxivClient` puts one async `RateLimiter` in front of every request
  (search, id lookup, PDF) and downloads PDFs with `httpx` (declared directly; it was already installed,
  and §19.2 lists it). `page_size` = results wanted, so a search is exactly one HTTP request.
- **Versioned downloads** (`/pdf/<id>v<n>`) and a sha256 per paper in the lock make the corpus
  reproducible; a hash mismatch on re-download is an error rather than a silent change.
- **No retries in M1.** A failed download is reported and the next run retries it. M2 moves fetching into
  the ingestion workflow, where `retry_policy` + `@catch_error` handle it (spec rule 4: don't hand-roll).
- **Async client** because M2 calls it from `num_workers=2` workflow steps; the blocking `arxiv`
  library call runs in `asyncio.to_thread`.

## D7. M2 ingestion workflow

Verified against the LlamaIndex docs MCP (concurrent_execution, retry_steps) and the installed source.

- **Fan-in when a paper fails (§6.2's open question).** In Workflows 2.x a `list[E]` parameter joins the
  *stream* opened by the step that returned a list; the runtime tracks every branch, so no count is
  needed. A `@catch_error` handler can **not** feed a different event type into that join: the
  validator rejects it ("no returned-list producer creates a stream for those event types"); it only
  counts the fan-out path, not recovery handlers. Options tried in a probe: (a) return the normal
  event type with a failure flag (works), (b) return `None` so the branch is dropped (works; the join
  fires with the survivors, even with `[]`). **Chosen: (b).** `persist` only ever sees real
  `PaperSummarized` events; failures live in `IngestState.failed` and on the stream.
- **`index_paper` has `num_workers=1`** (spec: 2). The docstore, vector store and index are shared
  in-memory objects that aren't safe for concurrent writers, and fastembed's ONNX session already uses
  every core. Embedding runs in `asyncio.to_thread` so fetches and LLM calls continue meanwhile.
- **Pipeline → index.** `UPSERTS` needs a vector store attached to the pipeline, but `SimpleVectorStore`
  doesn't store text. So the pipeline only dedupes + splits + embeds (`DUPLICATES_ONLY`, set
  explicitly), and its new nodes go into a `VectorStoreIndex` via `insert_nodes` (no re-embedding:
  nodes already carry embeddings). Changed parse output is handled by `--rebuild`, not upserts.
- **Embedding cache outside storage.** `data/cache/ingestion/` survives `--rebuild`: a rebuild re-splits
  but does not re-embed. Note: the cache key includes the embed model's serialized fields, so changing
  any embed setting re-embeds everything.
- **Retries belong to the workflow.** `Anthropic(max_retries=0)` (the SDK default is 10, invisible), and
  the arXiv client has no retry loop. `FETCH_RETRY` / `LLM_RETRY` in `retry.py`; anthropic 1.17's
  `RetryableError` is a middleware marker, so transient types are listed explicitly.
  `Scaled` (a custom `RetryPolicy`) multiplies delays by `P2_RETRY_TIME_SCALE` (tests: 0).
- **NLTK data.** nltk 3.10 refuses data dirs writable by group/other; with umask 0002 the copy bundled in
  `.venv` is rejected and `SentenceSplitter` fails. `ensure_nltk_data` copies it to `.cache/nltk_data`
  without group/other write and sets `NLTK_DATA`. No network.
- **New dependency: `fastembed==0.9.1`.** `llama-index-embeddings-fastembed` doesn't install the engine it
  wraps. Pulls `onnxruntime`, not torch. The model (`Qdrant/bge-small-en-v1.5-onnx-Q`, 65 MB) downloads
  once into `.cache/fastembed`.
- **Parsing.** PyMuPDF splits a heading's number and title into two lines; they're rejoined before
  heading detection. Guards against false headings: captions/numeric titles, numbering style
  (roman vs arabic), section sequence, and "Introduction" always resets the count (affiliation
  superscripts like "1 University of X"). On the 25-paper corpus: references cut 25/25,
  introduction 25/25, conclusion 22/25, method 20/25.
- **Measured on the real corpus** (fake LLM, real embeddings): 25 papers -> 803 chunks; first ingest
  ~290 s, CPU-bound on embedding (~0.2 s per chunk; batch size and thread count made no difference);
  no-op re-run 5.4 s.
- **Splitter experiment** builds one index per variant for M3. Segments (page x section) cap chunk
  size, so "512" gives a median ~190 tokens and 1024 changes little; semantic is ~10x slower to build.

## D8. M3 retrieval layer

- **Reranker: fastembed ONNX** (developer's choice over sentence-transformers + CPU torch).
  `FastEmbedRerank` is a ~30-line `BaseNodePostprocessor` around fastembed's `TextCrossEncoder` with
  `Xenova/ms-marco-MiniLM-L-6-v2`, the spec's model as ONNX (80 MB). No official LlamaIndex
  integration exists. ~1.8 s per question (12 pairs) on CPU once warm.
- **DocumentSummaryIndex without regenerating summaries.** The index asks its `response_synthesizer`
  for each document's summary; `StoredSummarySynthesizer` returns the saved text, so building costs $0
  and takes ~5 s. It groups chunks by `ref_doc_id`, but ingestion's chunks point at page segments, so
  the summary index holds copies regrouped by paper, in its own persist dir (`data/storage/summary/`,
  not the shared StorageContext the spec suggests: a shared docstore would overwrite the vector index
  nodes' source). Node ids are identical in both, so a cited `node_id` means the same chunk.
  Built at the end of every ingest; a manifest skips the rebuild when papers and chunk count match.
- **Router at retriever level.** `RouterRetriever` + `LLMSingleSelector` (one Haiku call per question)
  rather than `RouterQueryEngine`, which would also synthesize an answer: spec §9.3 says `research` takes
  nodes and makes its own constrained LLM call. Everything is wrapped in a `RetrieverQueryEngine`
  because its `.retrieve()` applies node postprocessors (the reranker) without synthesis.
- **No `Settings` defaults.** LlamaIndex falls back to `Settings.llm` / `Settings.embed_model` (OpenAI)
  whenever one is omitted, including inside `BaseSynthesizer`, `DocumentSummaryIndex` and its
  retriever. Every object gets them explicitly; synthesizers that never call an LLM get `MockLLM()`.
  Same family: `SubQuestionQueryEngine.from_defaults` raises ImportError unless given a
  `question_gen`, so the comparison script passes `LLMQuestionGenerator` (provider-neutral).
- **Metrics.** Paper level over the 5 chunks `research` will receive: LlamaIndex `HitRate` and `MRR`
  with arXiv ids as the ids (papers deduplicated in chunk order). Not `RetrieverEvaluator`, which
  compares node ids, while the labels are papers.
- **Question drafting** uses `llm.astructured_predict(QABatch, ...)` (Anthropic tool calling), 5 batches
  of 5 papers, 5 specific + 3 cross-paper questions per batch; the prompt forbids naming systems or
  authors (otherwise retrieval is trivial); ids not in the batch are dropped.
- **`resolve(factory)`** builds a Resource outside a workflow through the same factories and chaining,
  so scripts and evals construct the LLM, index and reranker exactly as steps do.
