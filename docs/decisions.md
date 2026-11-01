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

## D9. M4 review workflow

Verified against the docs MCP (concurrent_execution: dynamic API) and the installed source.

- **One `Finding` type for success and failure.** `ctx.collect_events(ev, [T]*n)` counts *exact* types
  (`Counter(type(e))`); with separate `Finding` / `FindingFailed` the expected mix is unknown in
  advance, so the buffer could never complete. `Finding.record.error` marks a failure; the scoped
  `@catch_error(for_steps=["research"])` returns a `Finding` too. Same lesson as D7 from the other
  fan-in API.
- **Events sent with `ctx.send_event` are declared in the return annotation** (`plan -> SubQuestion |
  Progress | None`), per the docs: otherwise validation fails ("consumed but never produced") and
  drawings miss the edge.
- **`plan` takes `QuestionScoped | Clarified | ReplanRequested`.** The spec's separate `on_clarified`
  step and `plan(OutlineDecision)` would put two consumers on one event type; a union input on `plan`
  is the same graph with fewer steps. Reject -> `ReplanRequested` (bounded by `outline_attempts <= 3`;
  the 3rd rejection is overruled and logged).
- **HITL in M4 = the real mechanism with an automatic caller.** `draft_outline` returns
  `OutlineApprovalRequired`, `scope` may return `NeedsClarification`; `hitl.auto_responder` answers.
  M5 only changes the caller. `on_outline_decision` already handles approve / edit / reject.
- **Citations are claims, not free text.** `research` gets 5 excerpts and must return claims, each tied
  to one excerpt number + a verbatim quote; out-of-range excerpts are dropped, quotes are fuzzy-checked
  (rapidfuzz partial_ratio >= 85 -> `quote_verified`). The writer only sees claim ids (`[2.3]`) for its
  own section; invented ids are stripped and counted. `finalize` numbers `[n]` per (paper, page) by
  first appearance and fails loudly if any cited node isn't in the index. `citations.json` keeps the
  full trail: n -> claims -> node_id + quote.
- **Streaming cost gap (fixed).** On a streamed Anthropic call the last chunk's `raw` is the final stream
  event, with usage but no model or id, so the instrumentation handler skipped it: streamed tokens were
  unbilled and invisible to the budget guard. `BudgetedAnthropic.(a)stream_chat` now records usage when
  the stream ends. Test fakes Anthropic's own stream events through the real integration.
- **Retries.** `LLM_RETRY = Scaled(RetryAfterPolicy(retry_policy(...)))`: transient Anthropic errors plus
  structured-output failures (matched by LlamaIndex's error messages, not every `ValueError`). On a
  structured failure the step re-prompts with the error (`fix_note`, from `ctx.retry_info()`).
  `RetryAfterPolicy` is the §11 custom policy: honours `retry-after(-ms)`, capped at 60 s, and lets the
  composed fallback decide *whether* to retry.
- **Writer model.** `get_writer_llm` loads all of `llm.json` and picks `final` (Sonnet) when
  `P2_LLM_PROFILE=final` (`--final`): `ResourceConfig.path_selector` is fixed at decoration time.
- **`accept_event_subclasses`** on `log_progress`: steps send `ResearchProgress` / `WriteProgress`
  (subclasses of `Progress`); one step records all of them in `state.log` and re-streams them.
- **Drawing snapshot compares line sets**: the drawer emits subclass-routing edges in set order, so the
  review diagram's line order differs between processes; the edges don't.
- **Dry run on the real index** (scripted LLM, real embeddings + reranker, 4 sub-questions): 25.6 s,
  research peaked at exactly 4 concurrent workers, citations resolved to real papers/pages.

## D10. M5 HITL, citation check, durability level 1

Verified against the docs MCP (human_in_the_loop, durable_workflows) and the installed source.

- **Deterministic chunk ids** (`chunk_id`: `"<arxiv_id>#<segment>/<chunk>"`, passed as the splitter's
  `id_func`). LlamaIndex defaults to uuid4, so re-indexing a segment after a crash (at-least-once)
  would add a second copy under new ids. Catch found while designing: `IngestionCache` returns the
  *stored* output nodes on a hit, ids included, so an old cache silently brings uuid ids back. One-time
  migration `rm -rf data/cache/ingestion && litreview ingest --rebuild` (re-embeds ~5 min, $0);
  `Storage.ingest` refuses stale-cache nodes with that message, and so does the crash script. The
  summary-index manifest now includes a digest of the node ids, so it rebuilds after the migration.
- **`index_paper` persists before it counts as done.** A snapshot holds events and state, not Resources:
  an index that lived only in a killed process's memory would be gone while the checkpoint says "indexed".
  `Storage.persist` writes to `storage.tmp/` then `os.replace`s each file (no truncated JSON after
  kill -9), pipeline docstore last.
- **Checkpoint loop** (`durability.run_checkpointed`): snapshot on `StepStateChanged(NOT_RUNNING)` of
  `index_paper` / `summarize_paper`, throttled to 2 s, atomic write; if a checkpoint exists, resume with
  `Context.from_dict` + `run(ctx=...)` and no StartEvent; delete it on success. `--fresh` / `--rebuild`
  discard it. Verified with a kill -9 harness on a scratch copy of the real corpus (real embeddings,
  fake LLM): killed at 9/25 indexed; the restart indexed only the other 16; 803 chunks, 0 duplicates,
  `IngestReport.papers == 25` (the list fan-in completed across both processes).
- **Citation check = child workflow** (`CitationCheckWorkflow`), run with `await Child(...).run(...)`
  inside `check_citations`; the drawing utility finds it by scanning the step source and nests it.
  It gets the parent's loaded index and LLM via `shared_resources` (a pre-seeded `ResourceManager`;
  tests use the same function, `override_resources` is gone). Deterministic checks first (unknown
  claim/node, quote not in chunk, an unmarked sentence with a number), then Haiku judges only what
  passed, in batches of 10 (list fan-out/fan-in inside the child).
- **Only verified claims are citable.** The writer gets claims whose research quote was found in the
  chunk. Found when the revise-loop test never reached the LLM judge: an unverified quote fails the
  deterministic check every round, and no revision can fix it. Real runs had 42/42 verified.
- **Revise loop:** check -> revise (flagged sections only, with the draft and the notes) -> write ->
  assemble -> check, at most `MAX_REVISIONS = 2` (so <= 3 checks). `assemble` merges into
  `state.drafts`, because each revise list opens a new stream that only contains the flagged sections.
  `ReviewReady.unsupported_claims` = what the last check still flagged; details in `check_issues.json`.
- **HITL caller** (`hitl.py`): pattern A `interactive_responder` (approve / edit YAML in `$EDITOR` with
  re-edit on validation errors / reject with feedback; prompts run in a thread; the live view is paused
  meanwhile); pattern B `DETACH` -> `PendingStore` (`runs/pending/<run_id>.json` = `ctx.to_dict()` + the
  prompt event) -> `handler.cancel_run()`; `resume_pending` restores into a new workflow instance,
  `run(ctx=...)`, `send_event(answer)`. A later prompt detaches again under the same run id. The
  cross-process test restores in a real subprocess and gets a byte-identical review, with no scope /
  plan / research / outline calls after the restore.
- **Subprocess safety.** `tests/conftest.py` clears P2_* dirs at import time; anything a child process
  imports (`tests/review_env.py`, `tests/restore_child.py`) must not import it, and the child asserts
  it is inside a pytest temp dir.
- **Field named `items` on an Event** shadows `DictLikeModel.items()`; renamed (`JudgeBatch.entries`).

## D11. M6 AgentWorkflow variant

Verified against the docs MCP (agent human_in_the_loop, state) and the installed llama-index-core source
(multi_agent_workflow.py, base_agent.py, function_tool.py, state_store.py).

- **What is held equal for the comparison**: retrieval (same query engine), claim validation (the
  Researcher may only cite node ids returned by its own `search_corpus` calls, with a quote that is found
  in the chunk), the citation check (same child workflow), rendering (`render.py`, extracted from
  `ReviewWorkflow.finalize` so both write identical artifacts, plus `draft.json` / `findings.json` for
  re-checking). What differs is orchestration: the agents choose searches, outline, prose, revisions
  and when to stop.
- **Tools get dependencies by closure** (`AgentDeps` / `ReviewTools`), not Workflow Resources: the
  AgentWorkflow's steps are LlamaIndex's own, so there is no step signature to annotate.
  `production_deps()` resolves the same Resource factories through one ResourceManager.
- **No `from __future__ import annotations` in agent_review.py.** `FunctionTool` detects the Context
  parameter with `annotation == Context`; postponed annotations are strings, so tools were called
  without `ctx`, and the agent retried the failing tool until max_iterations. (Found by the first probe.)
- **max_iterations = 120** (default 20; a review is ~30 agent turns). Stored in the Context, so it
  survives a restore.
- **Shared data in `ctx.store["review"]`, not `["state"]`.** AgentWorkflow formats `state` into the first
  prompt; findings and sections are read through tools instead.
- **HITL pattern C**: `propose_outline` calls `ctx.wait_for_event(OutlineDecision,
  waiter_event=OutlineApprovalRequired(...), waiter_id=f"outline-{attempt}")`. The tool is *replayed* when
  the answer arrives, so it writes nothing before the wait. Same events and `hitl.drive` as Workflow 2,
  so `--detach`, `pending`, `approve` work for both (the pending file records which workflow).
- **Agent memory is outside the snapshot.** AgentWorkflow's `"memory"` key is on the state store's
  known-unserializable list: `ctx.to_dict()` skips it with a warning. Fix: `Memory` with a SQLite session
  (`runs/agent_memory.db`, `aiosqlite` already installed) and `attach_memory` after restore. Attaching
  it *before* `run(ctx=...)` does not work: a restored Context's pre-run staging store is re-serialized
  when the run starts, dropping it again; so `resume_pending(after_start=...)` sets it on the running
  Context before the answer is sent. Verified by restoring in a separate process: the run continues
  inside the paused `propose_outline` call, no re-planning, no re-search. The same session id across
  runs (`--session`) is how follow-up questions reuse the conversation (spec "Memory for the Planner";
  in AgentWorkflow the memory is shared by all agents).
- **Test LLM**: `PolicyLLM` (a `MockFunctionCallingLLM` with a response generator) decides each tool call
  from the conversation (agent name from the system prompt + tool results so far), so a restored run in a
  fresh process continues correctly. The citation judge gets its own ScriptedLLM (`AgentDeps.check_llm`).
- **Agent diagram** via `draw_agent_workflow_mermaid` (agents, tools, handoffs): `docs/agent_flow.md`.
- **Storage self-repair on load** (found by a flaky resume test). An interrupted run's leftover thread
  was still saving while the resumed run loaded: it read the *old* index files but the *new* pipeline
  docstore, so it treated a paper as already ingested and skipped it for good. Real-world equivalent:
  two `ingest` processes at once. `Storage` now forgets any document the pipeline docstore claims but
  whose first chunk isn't in the loaded index, so it is re-ingested (an overwrite, thanks to deterministic
  ids); saves take a process lock and a unique temp dir. Test builds that mixed state directly; the
  flaky test passed 15/15 afterwards.

## D12. M7 serving and durability level 2 (and an M6 fix found on the way)

- **max_tokens was silently breaking runs (M6 agents, and Workflow 2's retries).** In the comparison,
  5 of 6 agent runs ended early: each last turn had exactly 1,500 output tokens, our cap. Haiku 5.5 thinks
  before answering and thinking counts toward max_tokens, so a turn that started a large tool call
  (record_finding, propose_outline) was cut off; with no complete tool call, AgentWorkflow treats the
  turn as the final answer and ends the run. 125 ledger rows sat at the cap, so Workflow 2's structured
  outputs were being truncated and silently retried too. Fixes: caps raised (dev 4096, final 8192);
  the ledger records `stop_reason`; `BudgetedAnthropic` raises `OutputTruncated` (after billing) instead
  of returning a cut-off answer; not retried (same cap, same result).
- **`dbos` pinned to 2.31.1** (last 2.x). `llama-agents-dbos==0.7.0` (latest) requires `dbos>=2.18.0` with
  no upper bound; uv chose 3.4.0, where `Queue(...)` can no longer be constructed directly, so
  `runtime.launch()` fails. Same pattern as D5 (anthropic).
- **Retry policies pickle by name** (`retry.NamedPolicy`). The DBOS runtime pickles each run's
  configuration, retry policies included; `workflows`' composable conditions hold local lambdas, so no
  retried workflow could start under DBOS. `__reduce__` stores the policy's name; unpickling returns the
  same module-level object.
- **DBOS run identity**: a run id that already finished returns its stored result. `run_durable` keeps the
  id in `runs/dbos_ingest_run_id` from start to success: a restart after a crash reuses it (resume), the
  next ingest gets a new one. That file is the only durability code left for ingestion. The in-process
  stream replays every event from the start on resume (as documented).
  Verified: kill -9 at 9/25 indexed on a scratch copy of the corpus (real embeddings, fake LLM): the
  restart resumed the same run id, 25 papers, 803 chunks, 0 duplicates.
- **Server**: `build_server` registers review / ingest / agent_review with `additional_events=[OutlineDecision,
  Clarified]` (the human's answers aren't produced by any step, so the debugger's Send Event form needs
  them) and `idle_timeout=3600` (a run waiting for a human is released from memory after an hour and
  restored when the answer comes). `litreview serve` builds it async; `server_app.py` holds a module-level
  instance for `python -m llama_agents.server` (kept separate so importing `server.py` stays cheap).
- **Agent workflow takes the question as the user message** (was `initial_state`): the server registers
  one instance for all runs. Tools read it from `user_msg_str`, which AgentWorkflow stores verbatim.
- **agent_review is not served on DBOS.** Its memory sits under a Context key the state store refuses to
  serialize (D11), so a journal replay or an idle release would resume without it. The same caveat
  applies to the default server's idle release after `IDLE_TIMEOUT_S`.
- **"One reader per stream" (spec §2.2) no longer holds.** Events are persisted in the store and each
  reader follows its own cursor (`after_sequence`): two concurrent readers of one run see identical event
  lists, and a finished run's events can be read again. Tested over real HTTP.
- **Restart behaviour (spec §13.5) measured, `scripts/server_restart_demo.py`**, a 10-tick run, server
  killed with SIGKILL after ~2 ticks:

  | | restarted immediately | restarted 32 s after the run began |
  |---|---|---|
  | SqliteWorkflowStore (default runtime) | handler stays `running`, nothing continues | resumes from persisted ticks, completes |
  | DBOS runtime | resumes at once, completes | resumes, completes |

  The default server *does* resume on start (it replays persisted ticks), but skips handlers created
  less than 30 s before the restart (`RESUME_FRESH_HANDLER_GRACE`), presumably so a brand-new run isn't
  picked up twice. DBOS recovers every unfinished run it owns. The spec expected "store: handler survives;
  DBOS: run resumes"; the real difference is narrower.
- The demo's workflow lives in the package (`workflows/countdown.py`): DBOS pickles events, and pickle
  can't import a class from a file the server launcher loaded under an ad-hoc module name.
- The demo picks a free port: another local project was already listening on the first one tried.

## D13. M8 observability, diversity, evals

- **Tracing**: `llama-index-observability-otel` turns the instrumentation dispatcher into OTel spans:
  run -> step (with run id and input event) -> retrieval / rerank / LLM; child workflows nest under the
  calling step. Exporters: a JSON-lines file always (`runs/traces/spans.jsonl`, simple processor so
  nothing is lost on kill), plus OTLP/HTTP to Phoenix on request. New dependency (approved):
  `opentelemetry-exporter-otlp-proto-http`; Phoenix itself runs via `uvx`, outside the project.
- **Custom instrumentation**: `quotes.quote_in_chunk` (now the single quote check used by research, the
  citation check and the agents) has `@dispatcher.span` and emits a `CitationChecked` event.
- **Cost per step**: the ledger's `step` column is filled from the runtime's step context variable
  (`StepWorkerStateContextVar`, internal to llama-index-workflows; failures leave it empty).
  `litreview cost --by-step`.
- **Research diversity** (approved): the reranker now only re-orders all 12 candidates; a `Diversify`
  postprocessor always picks the final 5, at most `max_chunks_per_paper` (2) per paper, backfilling if
  fewer papers are available; the research prompt asks for claims across papers. Eval on 40 questions
  (scratch copy, $0): papers@5 1.7 -> 2.5, hit@5 0.90 -> 0.90, MRR 0.86 -> 0.86 (rerank on);
  without rerank hit@5 0.82 -> 0.85. Remaining limit: with 12 candidates, some questions only have 1-2
  papers to choose from (a larger `top_k` is the next knob).
- **Citation eval** uses its own strict prompt (`[EVAL-CITE]`), not the pipeline checker's, plus
  LlamaIndex `FaithfulnessEvaluator` on a 10-sentence sample, reporting agreement. Same model family as
  the writer, so expect some leniency: that is the point of your manual check and the second opinion.
- **Quality eval**: Sonnet rubric (coverage, structure, no_fabrication, hedging), one call per review;
  `sheet` / `agree` for blind human scoring.
- **Regression gate** (`evals/compare.py`): metrics on a 0-100 scale from the reports; fails if any drops
  more than 3 points under `evals/baseline.json` (unknown-node % is stored negated).
