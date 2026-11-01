# LitReview walkthrough: every scenario that was actually run

This branch (`runs-walkthrough`) is `main` plus the artifacts of the runs made while building P2:
reviews, logs, the cost ledger, a frozen human-in-the-loop run, the agents' conversations, crash-test
logs, server logs and traces. This document walks through each run end to end, using those files, so
that reading it explains every feature and flow as it really happened, including what went wrong.

`main` has the code only. To run anything yourself, start there (README quickstart).

**Contents**

1. [What is on this branch](#1-what-is-on-this-branch)
2. [Timeline of what was run](#2-timeline-of-what-was-run)
3. [Scenario A: building the corpus](#3-scenario-a-building-the-corpus)
4. [Scenario B: ingestion](#4-scenario-b-ingestion)
5. [Scenario C: ingestion killed mid-run, then resumed](#5-scenario-c-ingestion-killed-mid-run-then-resumed)
6. [Scenario D: the retrieval eval](#6-scenario-d-the-retrieval-eval)
7. [Scenario E: one review, end to end](#7-scenario-e-one-review-end-to-end)
8. [Scenario F: a review paused for a human, frozen on disk](#8-scenario-f-a-review-paused-for-a-human-frozen-on-disk)
9. [Scenario G: the same review by four agents](#9-scenario-g-the-same-review-by-four-agents)
10. [Scenario H: explicit workflow vs agents, head to head](#10-scenario-h-explicit-workflow-vs-agents-head-to-head)
11. [Scenario I: a server killed mid-run (store vs DBOS)](#11-scenario-i-a-server-killed-mid-run-store-vs-dbos)
12. [Scenario J: tracing a run](#12-scenario-j-tracing-a-run)
13. [Scenario K: where the money went](#13-scenario-k-where-the-money-went)
14. [What the runs revealed (and what was fixed)](#14-what-the-runs-revealed-and-what-was-fixed)
15. [Feature index: where each feature can be seen](#15-feature-index-where-each-feature-can-be-seen)
16. [Not run yet](#16-not-run-yet)

---

## 1. What is on this branch

| Path | What it is | Produced by |
|---|---|---|
| `out/<slug>/` | One folder per review: `review.md`, `refs.bib`, `citations.json`, `findings.json`, `draft.json`, `check_issues.json`, `log.txt`, `execution.md` | `litreview review`, `scripts/compare_workflows.py` |
| `out/<slug>/agent/` | The same files, written by the agent workflow | `litreview agent-review`, the comparison |
| `runs/costs.jsonl` | Every Anthropic call: time, model, tokens, cost (359 rows, $0.45) | the cost hook (`cost.py`) |
| `runs/ingest_execution.mermaid` | What the last ingestion actually executed | `litreview ingest` |
| `runs/pending/1101-075021-6130.json` | A review frozen while waiting for outline approval | `litreview review --detach` |
| `runs/crash-test/run1.log`, `run2.log` | Ingestion killed with SIGKILL, then restarted | `scripts/crash_ingest.py` |
| `runs/restart-demo/*/server.log` | HTTP server killed and restarted, with and without DBOS | `scripts/server_restart_demo.py` |
| `walkthrough/agent_sessions/*.md` | The agents' conversations, one file per run | exported from `runs/agent_memory.db` |
| `walkthrough/dev_runs/` | $0 runs made during development: two traces and the diversity retrieval eval | see Scenario D and J |
| `data/papers.json`, `data/summaries/` | Paper metadata and the 25 generated summaries | `fetch_corpus.py`, `litreview ingest` |
| `evals/reports/compare.json` | Per-run numbers of the explicit-vs-agentic comparison | `scripts/compare_workflows.py` |

**Left out on purpose**: the PDFs, parsed text, the vector index and the embedding cache (they contain
the papers' full text, which arXiv licences mostly don't allow redistributing), and the raw
`agent_memory.db` (the exported transcripts cut search results to 300 characters). Rebuild them from
the committed `data/corpus.lock.json` with `uv run litreview ingest`. `runs/workflows.db` is not here
because it is empty: the HTTP server never served a real review (Scenario I used a test workflow).

Times in logs and the ledger are UTC; file timestamps on your machine are UTC+5:30.

## 2. Timeline of what was run

Reconstructed from `runs/costs.jsonl` (calls grouped by bursts) and the run artifacts:

| When (UTC) | LLM calls | Cost | Run | Scenario |
|---|---|---|---|---|
| 10-30 05:12 | 1 | $0.0000 | `litreview smoke`: one Haiku call through the injected LLM | (M0) |
| 10-30 05:56 | 25 | $0.0212 | `litreview ingest`: 25 papers, one summary each | B |
| 10-31 05:53 | 80 | $0.0100 | question drafting + retrieval eval incl. the router configs | D |
| 11-01 04:25 | 23 | $0.0162 | first reviews of the default question | E |
| 11-01 07:00 | 26 | $0.0987 | `review --final` "centralized vs decentralized" (7 Sonnet calls) | E |
| 11-01 07:49 | 36 | $0.0319 | `review --detach` (frozen at the outline), then the crash test (25) | F, C |
| 11-01 08:36 - 08:50 | 34 | $0.0746 | `agent-review` runs: one complete, one cut short, one follow-up test | G |
| 11-01 08:51 | 134 | $0.1988 | `scripts/compare_workflows.py`: 3 questions x 2 repeats x 2 workflows | H |
| (dev, $0) | 0 | $0 | server restart demo, traced runs, diversity eval, DBOS crash harness | I, J, D |

## 3. Scenario A: building the corpus

**Ran**: `uv run python scripts/fetch_corpus.py`, picking 25 of the 40 search hits.

**Flow**: one arXiv search (query in `config/topic.json`) → you pick by number → `data/corpus.lock.json`
records each paper's id, version and the PDF's sha256 → PDFs downloaded one request every 3 s.

**Look at**:
- `data/corpus.lock.json` (on `main` too): the reproducible definition of the corpus. Downloads use the
  versioned URL (`/pdf/<id>v<n>`) and are checked against the hash.
- `data/papers.json`: title, authors, year, abstract per paper; later used for BibTeX and summaries.

**Features**: rate limiting shared by every request, on-disk caching, idempotent hashed downloads, atomic
file writes. Nothing here is a Workflow yet; the same `ArxivClient` later becomes a Resource (Scenario B).

## 4. Scenario B: ingestion

**Ran**: `uv run litreview ingest` (10-30 05:56, 25 Haiku calls, $0.021).

**Flow** (`src/litreview/workflows/ingestion.py`, diagram `docs/ingest_flow.md`):

```
IngestRequest ─load_lock─▶ 25 × PaperToFetch          fan-out: the step returns a list
  PaperToFetch ─fetch_pdf (2 workers, retried)─▶ PaperFetched
  PaperFetched ─parse_pdf (4 workers)─▶ PaperParsed
  PaperParsed ─index_paper (1 worker)─▶ PaperIndexed    split + embed locally, persist the index
  PaperIndexed ─summarize_paper (3 workers, retried)─▶ PaperSummarized    one Haiku call
25 × PaperSummarized ─persist─▶ IngestReport          fan-in: fires once, after all 25 branches
```

**Look at** `runs/ingest_execution.mermaid`: the execution drawing of the last ingest. Each of
`PaperToFetch`, `PaperFetched`, `PaperParsed`, `PaperIndexed`, `PaperSummarized` occurs 25 times, then
one `CollectionReleaseEvent` (the runtime releasing the 25-member list to `persist`) and one `IngestReport`.
No step in the code says "wait for 25": the list returned by `load_lock` opened a stream, and the runtime
tracked every branch of it.

**Results**: 803 chunks in the index; 25 summaries in `data/summaries/`. Open one, e.g.
`data/summaries/2308.00352.json`: the model, the number of input characters (abstract + introduction +
conclusion only, capped at ~18k characters to control cost), and the text.

**What went wrong (found later)**: 7 of the 25 summary calls hit the then 1,500-token output cap. Four
summaries are damaged: `2406.08979` is empty, `2405.14314`, `2406.20041` and `2608.08605` stop
mid-sentence. See section 14.

## 5. Scenario C: ingestion killed mid-run, then resumed

**Ran**: `uv run python scripts/crash_ingest.py` (11-01, 25 Haiku calls, $0.023). The script ingests into
an isolated copy (`runs/crash-test/`), kills the process with SIGKILL once 12 summaries exist, then runs
the same command again.

**Flow**: while ingestion streams, every time an `index_paper` or `summarize_paper` step finishes, the
checkpoint loop (`src/litreview/durability.py`) writes `handler.ctx.to_dict()` (events in flight + state
+ partial fan-in) to `runs/checkpoints/ingest.json`, at most every 2 s. The second run finds that file,
rebuilds the run with `Context.from_dict(...)` and continues with `workflow.run(ctx=...)`, without
sending a new start event.

**Look at**:
- `runs/crash-test/run1.log`: the first process; it ends abruptly (killed).
- `runs/crash-test/run2.log`: starts with `resuming from checkpoint .../runs/checkpoints/ingest.json`, then
  continues; the summaries it streamed are visible in the log.
- The arithmetic: `run1.log` shows 12 POSTs to the Anthropic API, `run2.log` 13, and the ledger has
  exactly 25 rows tagged `crash_test` (`grep -c crash_test runs/costs.jsonl`). One summary per paper:
  nothing was paid for twice.

**Why it worked** (each was a deliberate change, `docs/decisions.md` D10):
- completed steps are not re-run after a restore; steps that were running when the process died are
  re-run from the top (at-least-once), so every step is idempotent: a saved summary file skips the LLM
  call, a PDF with the right hash skips the download;
- chunk ids are deterministic (`<paper>#<segment>/<chunk>`), so re-indexing overwrites instead of
  duplicating;
- `index_paper` saves the index before it counts as done, with atomic file replacement, because a
  checkpoint holds events and state but not Resources (the index lives in a Resource).

M7 repeated this test on the DBOS runtime (no checkpoint code at all): killed at 9 of 25 papers, the
restart resumed the same run id and finished with 803 chunks and no duplicates (console output recorded
in `docs/decisions.md` D12).

## 6. Scenario D: the retrieval eval

**Ran**: `scripts/bootstrap_qa.py` (Haiku drafted 40 questions), `scripts/curate_qa.py` (you kept all
40, `data/qa/labeled.jsonl`), `python -m evals.retrieval --apply` (10-31, $0.01: the router configs made
one Haiku call per question), and `scripts/compare_subquestion.py`.

**Flow of one retrieval**: question → vector retriever (top 12 by embedding) or, with the router, an LLM
choice between vector and summary retrievers → cross-encoder reranker → top 5 chunks.

**Look at** `evals/reports/retrieval.md` (paper-level metrics over the 5 chunks `research` receives):

| config | hit@5 | MRR |
|---|---|---|
| rerank on, vector (chosen) | 0.90 | 0.86 |
| rerank on, router | 0.85 | 0.81 |
| rerank off, vector | 0.82 | 0.74 |
| rerank off, router | 0.75 | 0.72 |

Reranking helped most; the paid router made things worse, so `--apply` switched it off in
`config/retrieval.json`.

`walkthrough/dev_runs/retrieval_with_diversity.md` is the same eval after the M8 diversity cap (at most
2 of the 5 chunks per paper), run at $0 on a copy of the data: distinct papers in the top 5 went from
1.7 to 2.5 with hit@5 and MRR unchanged (0.90 / 0.86).

`evals/reports/subquestion.md` shows LlamaIndex's own `SubQuestionQueryEngine` answering 3 questions:
the built-in alternative to Workflow 2's explicit plan → research fan-out.

## 7. Scenario E: one review, end to end

The clearest run is the default question, written by Workflow 2 during the comparison (11-01 08:54):
`out/what-orchestration-patterns-do-llm-based-multi-agent-023f4b/`.

**Flow** (`src/litreview/workflows/review.py`; diagram `docs/review_flow.md`):

```
ReviewRequest ─scope─▶ QuestionScoped                     (vague → NeedsClarification → you)
  ─plan─▶ 5 × SubQuestion (ctx.send_event)
  ─research (4 workers)─▶ 5 × Finding
  ─gather_findings (ctx.collect_events)─▶ FindingsReady
  ─draft_outline─▶ OutlineApprovalRequired ··you··▶ OutlineDecision
  ─on_outline_decision─▶ 6 × WriteSection (a returned list)
  ─write_section (3 workers)─▶ 6 × SectionDraft ─assemble─▶ DraftAssembled
  ─check_citations (child workflow)─▶ CitationIssues ─revise─▶ flagged WriteSections → … (≤ 2 rounds)
  ─▶ ReadyToFinalize ─finalize─▶ ReviewReady + files
```

Follow it through the files:

**1. Plan** (`log.txt`, first line, 08:54:25): `5 sub-questions`. The sub-questions are in
`findings.json`, e.g. *"How do centralized orchestrator-worker designs and decentralized peer-to-peer
agent designs differ…"*.

**2. Research, four at a time** (`log.txt` 08:54:27): four `ResearchProgress` lines at the same second
(the `num_workers=4` limit), the fifth starts at 08:54:38 when a worker frees up. Each finishes with
"7-9 claims".

**3. Claims, not free text** (`findings.json`): each claim is one sentence tied to one chunk and a
verbatim quote that was checked against that chunk:

```json
{"claim_id": "1.1",
 "statement": "In the centralized orchestrator design, a single orchestrator selects which single agent to activate at each step, conditioned on the current global system state and task specification.",
 "citation": {"arxiv_id": "2505.19591", "node_id": "2505.19591#005/1", "page": 3,
              "quote": "the orchestrator selects a single agent at ∈A to activate, conditioned on the current global system st…",
              "quote_verified": true}}
```

The 5 findings hold 38 claims, but from only 2-3 papers each (this run predates the diversity cap).

**4. Outline approval** (`log.txt` 08:54:49): `outline attempt 1: waiting for approval`. The run paused
on an `InputRequiredEvent`; the comparison script's automatic responder sent `OutlineDecision(approve)`;
writing started the same second.

**5. Writing, three at a time**: three `WriteProgress` lines at 08:54:49, the next three at 08:54:56.

**6. The writer cites claims, never papers** (`draft.json`): *"A single orchestrator selects which one
agent to activate at each step, conditioned on the current global system state and task specification
[1.1]."* The writer only sees claim ids for its section; invented ids are stripped (`unknown_markers`).

**7. Citation check and revision** (`log.txt`): `round 1: 7 issue(s) in 51 sentences (30 judged)` →
flagged sections rewritten (08:55:13-25) → `round 2: 4 issue(s) in 39 sentences (24 judged)` → rewritten
again → a third check (its log line is missing, see section 14) left 3 issues, listed in
`check_issues.json`, e.g. a sentence with a number but no citation (`problem: no_citation`). The check is a
child workflow (`CitationCheckWorkflow`): cheap deterministic checks first, then Haiku judges the rest in
batches of 10. The loop is bounded: at most 2 revisions.

**8. Finalize** (`review.md`, `citations.json`, `refs.bib`): claim markers become numbers, one per
(paper, page), in order of first appearance: `[1.1]` → `[1]` = *Dang et al. (2025). Multi-Agent
Collaboration via Evolving Orchestration. arXiv:2505.19591, p. 3*. `citations.json` keeps the full trail
for every `[n]`: claim → chunk id → quote. No LLM writes a reference.

**9. What actually executed**: `litreview review` also saves `execution.md`, a drawing of the events a
run really produced. The one in this folder is from an earlier CLI run of the same question (07:50 UTC;
both runs write to the same folder, and the comparison script doesn't draw), so it shows the same flow,
not this run's exact counts.

**What went wrong**: the final draft's Conclusion is empty (0 words), and in two other Workflow 2 reviews
of the comparison most sections are empty. Cause: section writing hit the 1,500-token cap (section 14).

**A second review to compare**: `out/how-do-centralized-and-decentralized-orchestration-patterns-compare-11c0a0/`
was written with `--final` (sections by Sonnet: the 7 Sonnet calls at 07:04 in the ledger) and 3
sub-questions. Its sections all have text (Sonnet's cap was 3,000 tokens), but it cites only 2 papers:
3 sub-questions × research concentrated on few papers.

## 8. Scenario F: a review paused for a human, frozen on disk

**Ran**: `uv run litreview review --detach` (11-01 07:50:59). The run stopped at the outline, saved
itself and exited. It has not been approved since.

**Flow** (`src/litreview/hitl.py`, pattern B): the workflow emits `OutlineApprovalRequired` → the caller
snapshots `handler.ctx.to_dict()` to `runs/pending/<run_id>.json` → `handler.cancel_run()`. Later, in any
process, `litreview approve <run_id>` rebuilds the Context with `Context.from_dict`, restarts it with
`run(ctx=...)`, and sends the `OutlineDecision`.

**Look at** `runs/pending/1101-075021-6130.json`:
- `waiting_for`: the `OutlineApprovalRequired` event, with the proposed outline (*"Orchestration Patterns
  in LLM-Based Multi-Agent Systems: Control, Cost, and Robustness Trade-offs"*, attempt 1);
- `ctx.state`: the whole typed `ReviewState`: 5 findings with their claims, the outline,
  `outline_attempts: 1`, the progress log (11 lines);
- `ctx.streams`, `ctx.deliveries`, `ctx.workers`: the runtime's own bookkeeping, which is why the restored
  run knows exactly what is still pending. All of it is plain JSON: events and state were designed to be
  serializable, Resources (index, LLM) are rebuilt by their factories.

To continue it: `uv run litreview approve 1101-075021-6130` (or `--edit`, `--reject "feedback"`). It
was saved by M5-era code; if a later change made it incompatible, the restore fails with an error rather
than producing something wrong.

## 9. Scenario G: the same review by four agents

**Ran**: `uv run litreview agent-review` (11-01 08:36), a second `agent-review` (08:48), a follow-up
with `--session mytopic`, and 6 agent runs in the comparison.

**Flow** (`src/litreview/workflows/agent_review.py`, diagram `docs/agent_flow.md`): Planner → Researcher
→ Writer → Reviewer, each a `FunctionAgent` with its own tools, handing off with a `handoff` tool.
Retrieval, claim validation, the citation check and rendering are the same code as Workflow 2; what
differs is that the LLM decides which tool to call next and when to stop.

**The complete run**: `walkthrough/agent_sessions/1101-083611-5929.md`, output in
`out/what-orchestration-patterns-do-llm-based-multi-agent-023f4b/agent/`. Its tool sequence:

```
Planner:    record_subquestions, handoff→Researcher
Researcher: search_corpus ×3, record_finding ×2, search_corpus ×2, record_finding, … (5 findings), handoff→Writer
Writer:     get_findings, propose_outline ×3, write_section ×9, handoff→Reviewer
Reviewer:   check_citations, request_revision, handoff→Writer
Writer:     write_section, handoff→Reviewer
Reviewer:   check_citations, finalize_review → "done"
```

Worth reading in the transcript:
- **Self-correction through tool errors.** The first `propose_outline` call had no arguments
  (`missing 1 required positional argument: 'outline'`); the second used claim ids like `1.1` as finding
  ids (`Input should be a valid integer, got … 1.1`). Both errors went back to the model as the tool
  result; the third call was valid and approved. A tool error is just text to an agent.
- **Human approval inside a tool** (HITL pattern C): `propose_outline` calls `ctx.wait_for_event(...)`,
  which puts `OutlineApprovalRequired` on the stream and pauses the tool call until the answer arrives;
  the tool is then replayed from the top, so it writes nothing before the wait.
- **The revision loop is a conversation**, not a graph edge: Reviewer → `request_revision` → hands off
  to the Writer with what to fix → Writer rewrites → hands back.
- Result: 8 papers and 17 cited passages, no empty sections (the Writer passes prose as a tool argument),
  0 remaining issues.

**The runs that stopped early**: `1101-084828-49d3.md`, and five of the six comparison sessions
(`compare-*`). Each ends with an assistant turn that contains only a thinking block. That turn hit the
1,500-token cap while starting a large tool call; with no complete tool call in it, `AgentWorkflow`
treated it as the final answer and ended the run silently (section 14).

**The follow-up test**: `mytopic.md`. The question was "follow-up" with no topic, and the agents
refused to invent one: the Researcher handed back to the Planner (*"I still don't have a research
question… I'm handing this back to the Planner rather than continuing with the topic I invented"*),
which ended with an explanation. This led to the M7 change that makes the question the run's user message.

**The second complete run**: `compare-2-2.md` (communication topologies), output in
`out/what-communication-topologies-do-llm-agent-teams-use-4e1d88/agent/`: two rounds of revisions (four
sections, then one), 33 LLM calls, about 1M input tokens, because every agent turn resends the shared
conversation.

## 10. Scenario H: explicit workflow vs agents, head to head

**Ran**: `uv run python scripts/compare_workflows.py` (11-01 08:51, 134 calls, $0.20): 3 questions ×
2 repeats × both workflows, Haiku everywhere, outline auto-approved; every draft re-checked by the same
citation checker.

**Look at** `docs/explicit-vs-agentic.md` and `evals/reports/compare.json`:

| | explicit (Workflow 2) | agents (Workflow 3) |
|---|---|---|
| runs completed | 6 / 6 | 1 / 6 |
| cost per review | $0.0095 | $0.108 (the one complete run) |
| LLM calls per review | 11 | 33 |
| tokens per review | 31k | 976k |
| wall time | 86 s | 186 s |
| citation score (re-checked) | 96% | 100% |
| outline overlap between repeats | 9% | n/a |

How to read it: the agent failures are the truncation bug, not the agent design, so this table says more
about silent failure modes than about orchestration styles. Three things hold regardless: the explicit
workflow is ~10× cheaper per review (no resent conversation), its outlines differ almost completely
between runs of the same question (9% heading overlap), and the explicit reviews' citation score is
probably flattered by their empty sections (fewer sentences to get wrong). Re-run after the M7 fix for a fair
comparison.

## 11. Scenario I: a server killed mid-run (store vs DBOS)

**Ran**: `uv run python scripts/server_restart_demo.py` ($0: a 10-tick test workflow, no LLM), served
through `python -m llama_agents.server` with the SQLite store and with the DBOS runtime. For each, a run
is started over HTTP, the server is killed with SIGKILL after ~2 ticks and restarted either immediately
or 32 s after the run began.

**Look at** `runs/restart-demo/default/server.log` and `runs/restart-demo/dbos/server.log` (each holds the
last trial, the restart 32 s after the run began): two server starts each, the `POST /workflows/countdown/run-nowait`, the event streams, the final `GET /handlers/…`.
The DBOS log also shows DBOS initializing its SQLite system database and listening to the workflow's queue.

| | restarted immediately | restarted 32 s after the run began |
|---|---|---|
| SqliteWorkflowStore | handler stays `running`, nothing continues | resumes from persisted ticks, completes |
| DBOS runtime | resumes at once, completes | resumes, completes |

The store-backed server does resume runs on start, but skips handlers created less than 30 s earlier;
DBOS recovers every unfinished run it owns. (The spec expected "store: record survives, DBOS: run
resumes"; the real difference is narrower, D12.)

The HTTP flow with a real review (start → stream → `POST /events/{id}` with the approval → result) is
covered by `tests/test_server.py` over real HTTP with a scripted LLM, and `scripts/client_demo.py`, which
has not been run against the live server yet (section 16).

## 12. Scenario J: tracing a run

Tracing arrived in M8, after all the paid runs above, so these two traces come from $0 development runs:

- `walkthrough/dev_runs/trace_scripted_review.md` (rendered from `.jsonl`): a review with a scripted LLM
  on the 3-paper test corpus. One `ReviewWorkflow.run` span; one span per step under it; retrieval and
  LLM spans under `research`; `CitationCheckWorkflow.run` nested under `check_citations`; and the custom
  `quote_in_chunk` spans, each with a `CitationChecked` event. The footer lists how many `research` spans
  overlapped (the worker limit).
- `walkthrough/dev_runs/trace_ingest_forced_failure.md`: `litreview ingest --fail 2308.00352` on a copy of
  the real corpus. Four `fetch_pdf` spans with status ERROR for that paper at +6.0, +9.2, +16.0 and
  +28.1 s (the retry policy's exponential backoff), then `on_fetch_failure` (the `@catch_error` handler),
  then `persist` with the other 24 papers.

## 13. Scenario K: where the money went

`runs/costs.jsonl`: 359 calls, $0.45 of the $10 cap. 352 Haiku calls, 7 Sonnet calls (the `--final`
review). By run, see the timeline in section 2: the comparison is the biggest item (44%), then the
`--final` review (22%) and the agent runs (17%). The `step` column is empty for these rows because per-step
recording arrived in M8 (`litreview cost --by-step` will break new runs down by workflow step).

110 of the 359 calls produced exactly the 1,500-token cap. That count is what pointed to the truncation
problem.

## 14. What the runs revealed (and what was fixed)

The artifacts on this branch are the evidence for these findings; the fixes are on `main`.

| Finding | Evidence here | Fix on main |
|---|---|---|
| Haiku 5.5 thinks before answering, and thinking counts toward `max_tokens`. At 1,500 tokens many calls were cut off. | 110 ledger rows at exactly 1,500; in the topologies review the 7 section calls (09:03:45-09:04:00) are all at 1,500 | caps raised to 4,096 / 8,192; the ledger records `stop_reason`; a cut-off call now raises `OutputTruncated` instead of returning partial output (D12) |
| …which left Workflow 2 sections empty (most of the "thin reviews") | `draft.json`: orchestration 1/6 empty, who-acts-next 3/7, topologies 5/6 | same |
| …which ended agent runs silently (a cut-off tool call looks like a final answer) | `walkthrough/agent_sessions/compare-*.md`, last turn thinking-only | same |
| …and damaged 4 summaries | `data/summaries/2406.08979.json` empty, three cut mid-sentence | regenerate: delete the 4 files, `uv run litreview ingest` (~$0.002) |
| Research drew claims from only 2-3 papers per sub-question | `findings.json` | per-paper cap after reranking: papers@5 1.7 → 2.5 (D13) |
| The agent question was fixed at construction, so a follow-up had no question | `mytopic.md` | the question is now each run's user message (D12) |
| `log.txt` can miss the last `[check]` line | orchestration review: 3 check rounds by `check_issues.json`, 2 in the log | not fixed: progress events are logged by a separate step that can finish after `finalize` reads the log |

## 15. Feature index: where each feature can be seen

| Feature | Where on this branch |
|---|---|
| Fan-out by returning a list; list fan-in | `runs/ingest_execution.mermaid` (25 of each event, one `CollectionReleaseEvent`) |
| `num_workers` | `log.txt` of any review: 4 research / 3 write starts in the same second; trace footer |
| `ctx.send_event` + `ctx.collect_events` | Scenario E steps 1-3 |
| Branch (union return) and bounded loops | `log.txt` check rounds; Scenario E step 7 |
| Typed state | `runs/pending/…json` → `ctx.state` |
| Structured LLM output with validation | `findings.json` claims; the outline in the pending file |
| Retry policy, `@catch_error` | `walkthrough/dev_runs/trace_ingest_forced_failure.md` |
| HITL pattern A / B / C | auto-approval in `log.txt` / `runs/pending/` / `agent_sessions/1101-083611-5929.md` |
| Context snapshot and restore | `runs/pending/…json`; `runs/crash-test/run2.log` |
| Checkpoint loop (durability 1) | Scenario C |
| DBOS runtime (durability 2) | Scenario I, D12 |
| Child workflow | `[check]` lines in `log.txt`; trace nesting in Scenario J |
| Resources (LLM, index, query engine, arXiv client) | every run; never in the snapshot (Scenario F) |
| AgentWorkflow, handoffs, tools with Context, memory | `walkthrough/agent_sessions/` |
| WorkflowServer, SQLite store | Scenario I logs |
| Instrumentation: cost hook, OTel spans, custom span + event | `runs/costs.jsonl`; Scenario J |
| Retrieval: router, reranker, diversity, summary index | `evals/reports/retrieval.md`, `walkthrough/dev_runs/retrieval_with_diversity.md` |
| Deterministic citations and BibTeX | `citations.json`, `refs.bib` |

## 16. Not run yet

These exist on `main` but have no artifacts here yet (all need an API key; costs approximate):

- `uv run python scripts/compare_workflows.py` again, after the truncation fix (~$0.6-1)
- `uv run python -m evals.citations` and `uv run python -m evals.quality judge` (~$0.1), then
  `evals.quality sheet` / `agree` (your blind scores) and `uv run python -m evals.compare --save`
- `uv run litreview serve` + `uv run python scripts/client_demo.py` (~$0.01) and the debugger UI
  walkthrough in `docs/debugger.md`
- any run with tracing on, to get a trace of a real review (`uv run python scripts/trace_summary.py`)
- `uv run python scripts/crash_ingest.py --runtime dbos` (~$0.02)
