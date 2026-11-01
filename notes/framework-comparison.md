# Framework comparison: the P2 column

Same rows as `../p1_pydantic_ai_invoices/notes/framework-comparison.md`; copy your P2 ratings into that
shared table when done. Rate 1-5 and write one sentence; the evidence column is facts from this build.

| Dimension | P2 LlamaIndex Workflows (your rating + sentence) | Evidence from this build |
|---|---|---|
| Typed structured output (unions, validation, retries) | | `astructured_predict` everywhere; failures re-prompted via `retry_info` (D9) |
| Tools and toolsets; extension points (capabilities, hooks) | | FunctionAgent tools with `ctx: Context`; instrumentation dispatcher for cost + spans |
| Orchestration (graphs, fan-out/join, branching) | | Graph from step types; two fan-in APIs with different rules (D7, D9) |
| Human-in-the-loop (pause, persist, resume, edit args) | | Three patterns; restore in a new process; `POST /events` over HTTP |
| Durability (crash recovery, replay, idempotency) | | Checkpoint loop vs DBOS; at-least-once forced 4 code changes (D10, D12) |
| Multi-agent and MCP | | AgentWorkflow handoffs; memory not serializable (D11) |
| Cost control (caching, limits, spend tracking) | | Own ledger + budget guard; streamed-call cost gap found (D9) |
| Observability (traces, usage, cache health) | | OTel spans per run / step / LLM call out of the box (D13) |
| Testing without a model ($0 tests, fakes) | | `WorkflowTestRunner`, ScriptedLLM, PolicyLLM; 131 tests, $0 |
| Evals (offline, agentic, LLM-judge, online) | | Retrieval / citation / quality evals + regression gate (all built by hand) |
| API stability and docs (what moved between versions) | | Spec written for Workflows 1.x, 2.26 installed (D2); dbos 3.x break (D12) |
| Lines of code / time to build | | `workflows/review.py` 434 code lines, `agent_review.py` 365 |
| Would use in production for… | | |
| Biggest surprise | | |
