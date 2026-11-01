# P2 learning journal

Your words, not Claude's (spec §23). Under each question: pointers to evidence from this build (files,
decisions, numbers) to argue from, then your answer.

## 1. Events + listeners vs an explicit graph: what got easier, and what got harder to reason about?

Evidence: no graph is written anywhere; `uv run litreview draw` derives it from step signatures
(`docs/review_flow.md`). Sent events must be declared in return annotations or validation fails (D9).
Subclass routing edges drawn in set order (D9). `CitationCheckWorkflow` nested by scanning step source (D10).

_Your answer:_

## 2. `send_event` + `collect_events` vs returning `list[Event]` + list fan-in: when would you pick each?

Evidence: `plan` / `gather_findings` vs `on_outline_decision` / `assemble` in `workflows/review.py`.
`collect_events` counts exact types, so success and failure share one `Finding` type (D9); list fan-in
joins a stream and needs no count, but a `catch_error` handler can't add a different type to it (D7);
each `revise` list opens a new stream, so `assemble` merges into state (D10).

_Your answer:_

## 3. What belongs in state, on events, and in Resources? One example of each from your code.

Evidence: `ReviewState` (`state.py`), events carry ids not text (`events.py` docstring), Resources hold
index / LLM / clients (`resources.py`). AgentWorkflow's memory is in the Context but not serializable (D11).

_Your answer:_

## 4. Which HITL pattern (A, B or C) would you ship in a web app, and why?

Evidence: A `interactive_responder`, B `--detach` + `approve` (restore in a new process, byte-identical
review), C `propose_outline` with `wait_for_event` (replays the tool; nothing written before the wait).
Over HTTP the answer is just `POST /events/{handler_id}` (tests/test_server.py).

_Your answer:_

## 5. What did "at-least-once resume" force you to change in your steps?

Evidence: deterministic chunk ids (uuid4 would duplicate on re-index), persist the index before a step
counts as done, atomic file writes, summary files as the idempotency key (D10); a race found by a flaky
test led to self-repairing storage (D11 note). Crash tests: 25 calls for 25 papers, 803 chunks, 0 dups.

_Your answer:_

## 6. Checkpoint loop vs DBOS runtime: what did you gain, and what did you give up?

Evidence: `run_checkpointed` (~40 lines) vs `run_durable` (a run-id file). DBOS needed: a `dbos` version
pin, retry policies that pickle by name, importable event classes, explicit durable workflow names (D12).
Restart table in D12: DBOS resumes immediately, the store-backed server only after its 30 s grace.

_Your answer:_

## 7. `@catch_error` vs letting the run fail: where is graceful degradation wrong?

Evidence: `on_fetch_failure` (ingest continues with 24 papers), `on_research_failed` (review notes the
gap), wildcard `on_any_failure` (partial.md). `OutputTruncated` deliberately not retried (D12).

_Your answer:_

## 8. Explicit Workflow 2 vs AgentWorkflow 3: cost, quality, determinism, debuggability. Which would you ship?

Evidence: `docs/explicit-vs-agentic.md` (re-run after the max_tokens fix). Before the fix: explicit
$0.0095 / 11 calls per review, agents $0.11 / 33 calls / ~1M tokens per successful run; the agents'
failures were silent (a truncated tool call looks like a final answer, D12).

_Your answer:_

## 9. Which retrieval change moved hit-rate most: splitter, rerank or router?

Evidence: `evals/reports/retrieval.md`: rerank 0.82 -> 0.90; router 0.90 -> 0.85 (worse, and paid);
the per-paper cap changed papers@5 1.7 -> 2.5 at the same hit-rate (D13).

_Your answer:_

## 10. How often did the citation judge disagree with you? What does that say about LLM-as-judge?

Evidence: `evals/reports/citations.md` (judge vs FaithfulnessEvaluator disagreements listed);
`uv run python -m evals.quality agree` (your blind scores vs Sonnet).

_Your answer:_

## 11. The cost per review, and where most tokens went.

Evidence: `uv run litreview cost --by-step` (step column recorded since M8); README Results.

_Your answer:_

## 12. Compared with P1 (Pydantic AI): typed state, DI (Resources vs deps) and HITL.

Evidence: P1 `notes/p1-journal.md` (P1 also hit thinking + max_tokens truncation). Here: `Context[State]`
+ `edit_state`, `Resource` / `ResourceConfig` with chaining and caching per workflow instance (D2),
three HITL patterns.

_Your answer:_
