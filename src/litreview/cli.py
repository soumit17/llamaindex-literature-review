"""`litreview` command line. M0: hello, tiny, smoke, draw, cost. M2: ingest. M4: review.
M5: pending, approve. M6: agent-review."""

from __future__ import annotations

import asyncio
import contextlib
import json
from pathlib import Path

import typer
from rich.console import Console
from workflows import Workflow
from workflows.events import StepStateChanged

from litreview.config import PROJECT_ROOT, get_settings

app = typer.Typer(no_args_is_help=True, add_completion=False)
console = Console()


def _short(event_name: str) -> str:
    """StepStateChanged reports names as "Tick" or "<class 'pkg.mod.Tick'>"; keep just "Tick"."""
    return event_name.rsplit(".", 1)[-1].rstrip("'>")


async def _run_streaming(wf: Workflow, start_event, debug_steps: bool):
    """Run a workflow and print every streamed event. This is the caller side of streaming:
    steps call `ctx.write_event_to_stream(...)`, the caller iterates `handler.stream_events()`."""
    handler = wf.run(start_event=start_event)
    async for ev in handler.stream_events(expose_internal=debug_steps):
        if isinstance(ev, StepStateChanged):
            # Internal events: lets you *see* each step start/finish and which worker ran it.
            out = f" -> {_short(ev.output_event_name)}" if ev.output_event_name else ""
            console.print(
                f"  [dim]{ev.name:<8} {ev.step_state.value:<12} in={_short(ev.input_event_name)}{out}[/dim]"
            )
        else:
            console.print(f"  [cyan]stream[/cyan] {type(ev).__name__}: {ev.model_dump()}")
    return await handler


@app.command()
def hello(
    name: str = typer.Argument("world"),
    rounds: int = typer.Option(3, help="How many times the tick step loops."),
    debug_steps: bool = typer.Option(
        False, "--debug-steps", help="Also show internal StepStateChanged events."
    ),
) -> None:
    """Run the M0 hello workflow (branch, loop, streaming, typed state). Free: no LLM."""
    from litreview.workflows.hello import Greet, HelloWorkflow

    result = asyncio.run(
        _run_streaming(HelloWorkflow(timeout=30), Greet(name=name, rounds=rounds), debug_steps)
    )
    console.print(f"[green]result[/green] {result!r}")


@app.command()
def tiny(text: str = typer.Argument("hello workflows")) -> None:
    """Run the unbound-function workflow. Free: no LLM."""
    from litreview.workflows.tiny_unbound import Shout, TinyWorkflow

    async def go() -> str:
        return await TinyWorkflow(timeout=30).run(start_event=Shout(text=text))

    console.print(asyncio.run(go()))


@app.command()
def smoke(prompt: str = typer.Option(None, help="Override the question sent to Haiku.")) -> None:
    """ONE live Haiku call through the Resource-injected LLM. Costs roughly $0.0001."""
    from litreview.resources import get_cost_tracker
    from litreview.workflows.smoke import Ask, SmokeWorkflow

    if not get_settings().anthropic_api_key:
        raise typer.BadParameter("ANTHROPIC_API_KEY is not set; put it in .env")
    tracker = get_cost_tracker()
    before = tracker.spent_usd
    start = Ask(prompt=prompt) if prompt else Ask()

    async def go() -> str:
        return await SmokeWorkflow(timeout=60).run(start_event=start)

    console.print(f"[green]Haiku says:[/green] {asyncio.run(go())}")
    # The workflow built its own tracker via the Resource; re-read the ledger for the true total.
    after = get_cost_tracker().spent_usd
    console.print(
        f"[yellow]this call:[/yellow] ${after - before:.6f}   [yellow]P2 total:[/yellow] ${after:.6f}"
    )


@app.command()
def draw(out_dir: Path = typer.Option(PROJECT_ROOT / "docs")) -> None:
    """Write 'all possible flows' diagrams (interactive HTML + Mermaid) for every workflow so far."""
    from llama_index.utils.workflow import draw_all_possible_flows, draw_all_possible_flows_mermaid

    from litreview.workflows.hello import HelloWorkflow
    from litreview.workflows.tiny_unbound import TinyWorkflow

    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    from litreview.workflows.ingestion import IngestionWorkflow
    from litreview.workflows.review import ReviewWorkflow

    flows = [
        ("hello", HelloWorkflow),
        ("tiny", TinyWorkflow),
        ("ingest", IngestionWorkflow),
        ("review", ReviewWorkflow),
    ]
    for name, wf in flows:
        html = out_dir / f"{name}_flow.html"
        # pyvis copies its JS helpers into ./lib and the HTML references them relatively,
        # so render from inside out_dir to keep lib/ next to the HTML.
        with contextlib.chdir(out_dir):
            draw_all_possible_flows(wf, filename=str(html))
        mermaid = draw_all_possible_flows_mermaid(wf, filename=str(out_dir / f"{name}_flow.mermaid"))
        (out_dir / f"{name}_flow.md").write_text(
            f"# {name} workflow: all possible flows\n\n```mermaid\n{mermaid}\n```\n"
        )
        (out_dir / f"{name}_flow.mermaid").unlink(missing_ok=True)
        console.print(f"wrote {html} and {name}_flow.md")

    # Workflow 3: agents, their tools and who may hand off to whom (placeholder deps: drawing only).
    from llama_index.core.llms import MockLLM
    from llama_index.utils.workflow import draw_agent_workflow_mermaid

    from litreview.workflows.agent_review import AgentDeps, build_agent_review

    deps = AgentDeps(engine=None, storage=None, llm=MockLLM(), writer_llm=MockLLM(), papers={}, summaries={})  # type: ignore[arg-type]
    mermaid = draw_agent_workflow_mermaid(
        build_agent_review(deps, "drawing"), filename=str(out_dir / "agent_flow.mermaid")
    )
    (out_dir / "agent_flow.md").write_text(
        f"# agent workflow: agents, tools, handoffs\n\n```mermaid\n{mermaid}\n```\n"
    )
    (out_dir / "agent_flow.mermaid").unlink(missing_ok=True)
    console.print("wrote agent_flow.md")


@app.command()
def ingest(
    limit: int = typer.Option(None, help="Only the first N papers in the lock file."),
    rebuild: bool = typer.Option(False, help="Re-parse and re-index (summaries and embeddings stay cached)."),
    fail: list[str] = typer.Option(
        [], "--fail", help="Demo: make fetch_pdf fail for this arxiv id (watch retries + catch_error)."
    ),
    debug_steps: bool = typer.Option(False, "--debug-steps", help="Show StepStateChanged events."),
    fresh: bool = typer.Option(False, "--fresh", help="Ignore a checkpoint left by an interrupted run."),
) -> None:
    """Run the ingestion workflow: fetch -> parse -> index -> summarize. Summaries cost ~$0.001/paper.

    Checkpointed: if a run is killed, the next `litreview ingest` resumes where it stopped."""
    from llama_index.utils.workflow import draw_most_recent_execution_mermaid
    from rich.progress import BarColumn, MofNCompleteColumn, Progress, TaskID, TextColumn, TimeElapsedColumn

    from litreview.corpus import CorpusLock, CorpusPaths
    from litreview.durability import run_checkpointed
    from litreview.events import IngestProgress, IngestReport, IngestRequest
    from litreview.resources import get_cost_tracker
    from litreview.workflows.ingestion import IngestionWorkflow

    s = get_settings()
    paths = CorpusPaths(s.p2_data_dir)
    lock = CorpusLock.load(paths.lock)
    if lock is None:
        raise typer.BadParameter(f"{paths.lock} not found; run scripts/fetch_corpus.py first")
    todo = [p for p in lock.papers[:limit] if not (paths.root / "summaries" / f"{p.arxiv_id}.json").exists()]
    if todo and not s.anthropic_api_key:
        raise typer.BadParameter(f"{len(todo)} papers need a summary but ANTHROPIC_API_KEY is not set")
    spent_before = get_cost_tracker().spent_usd
    marks = {"retry": "[yellow]retry[/]", "failed": "[red]FAILED[/]"}

    checkpoint = s.p2_runs_dir / "checkpoints" / "ingest.json"
    if (fresh or rebuild) and checkpoint.exists():
        checkpoint.unlink()
        console.print("[yellow]discarded the previous run's checkpoint[/]")

    async def go() -> IngestReport:
        columns = (TextColumn("{task.description:<10}"), BarColumn(), MofNCompleteColumn())
        with Progress(*columns, TimeElapsedColumn(), console=console) as progress:
            bars: dict[str, TaskID] = {
                stage: progress.add_task(stage, total=None)
                for stage in ("fetch", "parse", "index", "summarize")
            }
            handlers = []

            def on_event(ev) -> None:
                if isinstance(ev, IngestProgress):
                    if ev.status in marks:
                        progress.console.print(f"  {marks[ev.status]} {ev.arxiv_id}: {ev.message}")
                    elif ev.stage == "start":
                        for bar in bars.values():
                            progress.update(bar, total=ev.total)
                    else:
                        progress.update(bars[ev.stage], completed=ev.done, total=ev.total)
                elif isinstance(ev, StepStateChanged):
                    progress.console.print(
                        f"  [dim]{ev.name:<16} {ev.step_state.value:<12} worker={ev.worker_id}[/dim]"
                    )

            # The checkpoint loop (durability.py): snapshot after index/summarize steps, at most every
            # 2 s; if a checkpoint exists, resume from it instead of starting over.
            report = await run_checkpointed(
                IngestionWorkflow(timeout=3600),
                IngestRequest(limit=limit, rebuild=rebuild, fail_ids=fail),
                checkpoint,
                steps={"index_paper", "summarize_paper"},
                on_event=on_event,
                on_resume=lambda: progress.console.print(
                    f"[yellow]resuming from checkpoint[/] {checkpoint} (flags of the new command are ignored)"
                ),
                on_start=handlers.append,
                expose_internal=debug_steps,
            )
        out = s.p2_runs_dir / "ingest_execution.mermaid"
        out.parent.mkdir(parents=True, exist_ok=True)
        draw_most_recent_execution_mermaid(handlers[0], filename=str(out))
        return report

    report = asyncio.run(go())
    spent = get_cost_tracker().spent_usd
    console.print(
        f"\n[green]ingested[/] {report.papers} papers   [green]chunks[/] {report.nodes} "
        f"(+{report.new_nodes} new)   [green]summaries generated[/] {report.summaries_generated}"
        f"   [yellow]cost[/] ${spent - spent_before:.4f} (P2 total ${spent:.4f})"
    )
    if report.failed:
        console.print(f"[red]failed:[/] {', '.join(report.failed)}  (re-run to retry them)")
    console.print(f"[dim]execution diagram: {s.p2_runs_dir / 'ingest_execution.mermaid'}[/]")


class _ReviewUI:
    """What `review` and `approve` share: the live view, event printing, and the responder (which
    pauses the live view while a human answers)."""

    def __init__(self, mode: str, as_json: bool, quiet: bool, debug_steps: bool) -> None:
        from litreview.review_view import ReviewView

        self.mode, self.as_json, self.quiet, self.debug_steps = mode, as_json, quiet, debug_steps
        self.view = ReviewView(get_settings().p2_runs_dir / "costs.jsonl")
        self.live = None
        self.handlers: list = []

    def on_event(self, ev) -> None:
        if self.as_json:
            print(json.dumps({"type": type(ev).__name__, **ev.model_dump(mode="json")}), flush=True)
            return
        self.view.update(ev)
        if isinstance(ev, StepStateChanged) and not self.quiet:
            out = f" -> {_short(ev.output_event_name)}" if ev.output_event_name else ""
            console.print(
                f"  [dim]{ev.name:<20} {ev.step_state.value:<12} worker={ev.worker_id}"
                f" in={_short(ev.input_event_name)}{out}[/dim]"
            )

    def responder(self):
        from litreview.hitl import auto_responder, detach_responder, interactive_responder

        base = {"auto": auto_responder, "detach": detach_responder, "ask": interactive_responder(console)}[
            self.mode
        ]

        async def respond(ev):
            if self.live is not None:
                self.live.stop()  # give the terminal to the prompt
            try:
                return await base(ev)
            finally:
                if self.live is not None:
                    self.live.start()

        return respond

    async def run(self, start):
        """`start(respond, on_event)` drives the run; wrapped in the live view unless --json/--quiet."""
        from rich.live import Live

        if self.as_json or self.quiet:
            return await start(self.responder(), self.on_event)
        with Live(self.view, console=console, refresh_per_second=8) as live:
            self.live = live
            return await start(self.responder(), self.on_event)

    def finish(self, result) -> None:
        from llama_index.utils.workflow import draw_most_recent_execution_mermaid

        from litreview.events import OutlineApprovalRequired
        from litreview.hitl import Detached, show_outline

        if isinstance(result, Detached):
            if isinstance(result.waiting_for, OutlineApprovalRequired):
                show_outline(console, result.waiting_for)
            console.print(
                f"\n[yellow]detached[/] run [bold]{result.run_id}[/] is waiting for "
                f"{type(result.waiting_for).__name__}; snapshot: {result.path}\n"
                f"continue with: uv run litreview approve {result.run_id} "
                "[--edit | --reject TEXT | --answer TEXT]"
            )
            return
        folder = Path(result.markdown_path).parent
        if self.handlers:
            mermaid = draw_most_recent_execution_mermaid(
                self.handlers[-1], filename=str(folder / "execution.mermaid")
            )
            (folder / "execution.md").write_text(f"# Execution of this run\n\n```mermaid\n{mermaid}\n```\n")
            (folder / "execution.mermaid").unlink(missing_ok=True)
        if self.as_json:
            return
        if self.quiet:
            print(result.markdown_path)
            print(result.bib_path)
            return
        if result.error:
            console.print(f"[red]run failed, partial output written:[/] {result.error}")
        console.print(
            f"\n[green]review[/] {result.markdown_path}\n[green]bibtex[/] {result.bib_path}\n"
            f"[green]citations[/] {result.n_citations}   [yellow]sentences still flagged[/] "
            f"{result.unsupported_claims} after {result.citation_rounds} check(s)   "
            f"[yellow]invented markers removed[/] {result.unknown_markers}\n"
            f"[yellow]cost[/] ${result.cost_usd:.4f}"
        )
        if result.failed_subquestions:
            console.print(f"[red]research failed for:[/] {'; '.join(result.failed_subquestions)}")


def _preflight(final: bool):
    import os

    if final:  # read by get_writer_llm when the Resource is first resolved
        os.environ["P2_LLM_PROFILE"] = "final"
        get_settings.cache_clear()
    s = get_settings()
    if not s.anthropic_api_key:
        raise typer.BadParameter("ANTHROPIC_API_KEY is not set; put it in .env")
    if not (s.p2_data_dir / "storage" / "docstore.json").exists():
        raise typer.BadParameter("no index yet; run `uv run litreview ingest` first")
    return s


def _pending_store():
    from litreview.hitl import PendingStore

    return PendingStore(get_settings().p2_runs_dir / "pending")


@app.command()
def review(
    question: str = typer.Argument(None, help="Research question (default: topic.json default_question)."),
    max_subquestions: int = typer.Option(5, "--max-subquestions", help="3-6; fewer is cheaper."),
    target_words: int = typer.Option(1500, "--target-words"),
    final: bool = typer.Option(False, "--final", help="Write sections with Sonnet instead of Haiku (~10x)."),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Approve the outline (and clarifications) automatically."
    ),
    detach: bool = typer.Option(
        False, "--detach", help="Save the run at the outline and exit; see `approve`."
    ),
    debug_steps: bool = typer.Option(
        False, "--debug-steps", help="Show StepStateChanged (watch num_workers)."
    ),
    as_json: bool = typer.Option(
        False, "--json", help="Print every streamed event as NDJSON (implies --yes)."
    ),
    quiet: bool = typer.Option(False, "--quiet", help="Print only the output paths (implies --yes)."),
) -> None:
    """Write a cited literature review: plan -> research -> outline (you approve) -> write -> check."""
    from litreview.config import CONFIG_DIR
    from litreview.corpus import Topic
    from litreview.events import ReviewRequest
    from litreview.hitl import drive, new_run_id
    from litreview.workflows.review import ReviewWorkflow

    _preflight(final)
    question = question or Topic.load(CONFIG_DIR / "topic.json").default_question
    request = ReviewRequest(question=question, max_subquestions=max_subquestions, target_words=target_words)
    mode = "detach" if detach else "auto" if (yes or as_json or quiet) else "ask"
    ui = _ReviewUI(mode, as_json, quiet, debug_steps)
    run_id = new_run_id()

    async def start(respond, on_event):
        handler = ReviewWorkflow(timeout=3600).run(start_event=request)
        ui.handlers.append(handler)
        return await drive(handler, respond, on_event, debug_steps, (_pending_store(), run_id, question))

    ui.finish(asyncio.run(ui.run(start)))


@app.command()
def pending() -> None:
    """List detached review runs waiting for an answer."""
    from rich.table import Table

    from litreview.events import OutlineApprovalRequired

    runs = _pending_store().list()
    if not runs:
        console.print("no pending runs")
        return
    table = Table()
    for col in ("run id", "created", "waiting for", "question"):
        table.add_column(col)
    for r in runs:
        what = (
            f"outline approval (attempt {r.waiting_for.attempt})"
            if isinstance(r.waiting_for, OutlineApprovalRequired)
            else "clarification"
        )
        table.add_row(r.run_id, r.created, what, r.question)
    console.print(table)


@app.command()
def approve(
    run_id: str = typer.Argument(..., help="From `litreview pending`."),
    edit: bool = typer.Option(False, "--edit", help="Edit the outline in $EDITOR before approving."),
    reject: str = typer.Option(None, "--reject", help="Reject the outline with this feedback (re-plans)."),
    answer: str = typer.Option(None, "--answer", help="For a clarification: the refined question."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Answer any later prompt automatically."),
    interactive: bool = typer.Option(False, "--interactive", help="Answer later prompts here, not detached."),
    final: bool = typer.Option(False, "--final", help="Write sections with Sonnet."),
    debug_steps: bool = typer.Option(False, "--debug-steps"),
) -> None:
    """Continue a detached run in this process: restore its snapshot and send your decision."""
    import yaml
    from pydantic import ValidationError

    from litreview.events import Clarified, OutlineApprovalRequired, OutlineDecision
    from litreview.hitl import edit_in_editor, outline_to_yaml, resume_pending
    from litreview.models import Outline
    from litreview.workflows.review import ReviewWorkflow

    _preflight(final)
    store = _pending_store()
    pending_run = store.load(run_id)
    waiting = pending_run.waiting_for
    if isinstance(waiting, OutlineApprovalRequired):
        if reject:
            decision = OutlineDecision(action="reject", feedback=reject)
        elif edit:
            try:
                edited = Outline.model_validate(
                    yaml.safe_load(edit_in_editor(outline_to_yaml(waiting.outline)))
                )
            except (ValidationError, yaml.YAMLError, TypeError) as e:
                raise typer.BadParameter(f"edited outline doesn't validate: {e}") from e
            decision = OutlineDecision(action="edit", edited_outline=edited)
        else:
            decision = OutlineDecision(action="approve")
    else:
        decision = Clarified(refined_question=answer or (waiting.suggestions or [waiting.question])[0])
    mode = "auto" if yes else "ask" if interactive else "detach"
    console.print(
        f"restoring {run_id} ({pending_run.workflow}) and sending: "
        f"{type(decision).__name__}({decision.model_dump(exclude_none=True)})"
    )
    if pending_run.workflow == "agent_review":
        from functools import partial

        from litreview.workflows.agent_review import attach_memory, build_agent_review, production_deps

        agent_ui = _AgentUI(mode, debug_steps)
        session = (pending_run.extra or {}).get("session", run_id)

        async def start_agents():
            wf = build_agent_review(await production_deps(), pending_run.question)
            result = await resume_pending(
                store,
                run_id,
                wf,
                decision,
                agent_ui.responder(),
                agent_ui.on_event,
                debug_steps,
                on_start=agent_ui.handlers.append,
                after_start=partial(attach_memory, session_id=session),  # the conversation lives in SQLite
            )
            return await agent_ui.collect(result)

        agent_ui.finish(asyncio.run(start_agents()))
        return
    ui = _ReviewUI(mode, False, False, debug_steps)

    async def start(respond, on_event):
        return await resume_pending(
            store,
            run_id,
            ReviewWorkflow(timeout=3600),
            decision,
            respond,
            on_event,
            debug_steps,
            on_start=ui.handlers.append,
        )

    ui.finish(asyncio.run(ui.run(start)))


class _AgentUI:
    """Terminal trace for the agent workflow: who is acting, which tool it calls, what came back."""

    def __init__(self, mode: str, debug_steps: bool) -> None:
        from litreview.review_view import ledger_spent

        self.mode, self.debug_steps = mode, debug_steps
        self.ledger = get_settings().p2_runs_dir / "costs.jsonl"
        self.cost_at_start = ledger_spent(self.ledger)
        self.handlers: list = []
        self.current = ""

    def on_event(self, ev) -> None:
        from llama_index.core.agent.workflow import AgentInput, ToolCall, ToolCallResult

        if isinstance(ev, AgentInput) and ev.current_agent_name != self.current:
            self.current = ev.current_agent_name
            console.rule(f"[bold]{self.current}")
        elif isinstance(ev, ToolCall) and not isinstance(ev, ToolCallResult):
            args = json.dumps(ev.tool_kwargs, default=str)
            console.print(f"  [cyan]→ {ev.tool_name}[/]({args[:160]}{'…' if len(args) > 160 else ''})")
        elif isinstance(ev, ToolCallResult):
            first = str(ev.tool_output.content).strip().splitlines()[:1]
            style = "red" if ev.tool_output.is_error else "dim"
            console.print(f"    [{style}]← {(first[0] if first else '')[:160]}[/]")
        elif isinstance(ev, StepStateChanged) and self.debug_steps:
            console.print(f"  [dim]{ev.name:<24} {ev.step_state.value}[/dim]")

    def responder(self):
        from litreview.hitl import auto_responder, detach_responder, interactive_responder

        return {"auto": auto_responder, "detach": detach_responder, "ask": interactive_responder(console)}[
            self.mode
        ]

    async def collect(self, result):
        """Read the review the agents wrote, while the run's event loop is still alive."""
        from litreview.hitl import Detached
        from litreview.workflows.agent_review import agent_result

        if isinstance(result, Detached) or not self.handlers:
            return result, None
        return result, await agent_result(self.handlers[-1].ctx)

    def finish(self, outcome) -> None:
        from litreview.hitl import Detached
        from litreview.review_view import ledger_spent

        result, review = outcome
        spent = ledger_spent(self.ledger) - self.cost_at_start
        if isinstance(result, Detached):
            console.print(
                f"\n[yellow]detached[/] agent run [bold]{result.run_id}[/] waits for the outline decision "
                f"(cost so far ${spent:.4f}).\ncontinue with: uv run litreview approve {result.run_id} "
                "[--edit | --reject TEXT]"
            )
            return
        console.print(f"\n[green]agents said:[/] {result}")
        if review is None:
            console.print("[red]the agents stopped without calling finalize_review: no review written[/]")
        else:
            console.print(
                f"[green]review[/] {review['markdown_path']}\n[green]citations[/] {review['n_citations']}   "
                f"[yellow]sentences still flagged[/] {review['unsupported_claims']} after "
                f"{review['citation_rounds']} check(s)"
            )
        console.print(f"[yellow]cost[/] ${spent:.4f}")


@app.command("agent-review")
def agent_review(
    question: str = typer.Argument(None, help="Research question (default: topic.json default_question)."),
    session: str = typer.Option(None, help="Memory session: reuse it for follow-up questions."),
    final: bool = typer.Option(False, "--final", help="The Writer agent uses Sonnet."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Approve the outline automatically."),
    detach: bool = typer.Option(
        False, "--detach", help="Save the run at the outline and exit; see `approve`."
    ),
    debug_steps: bool = typer.Option(False, "--debug-steps", help="Show the AgentWorkflow's own steps."),
) -> None:
    """Workflow 3: the same review by four agents (Planner, Researcher, Writer, Reviewer) handing off."""
    from litreview.config import CONFIG_DIR
    from litreview.corpus import Topic
    from litreview.hitl import PendingStore, drive, new_run_id
    from litreview.workflows.agent_review import build_agent_review, production_deps, start_agent_review

    _preflight(final)
    question = question or Topic.load(CONFIG_DIR / "topic.json").default_question
    run_id = new_run_id()
    session = session or run_id
    ui = _AgentUI("detach" if detach else "auto" if yes else "ask", debug_steps)
    store = PendingStore(
        get_settings().p2_runs_dir / "pending", workflow="agent_review", extra={"session": session}
    )

    async def go():
        handler = start_agent_review(build_agent_review(await production_deps(), question), session)
        ui.handlers.append(handler)
        # expose_internal: AgentWorkflow streams AgentInput/ToolCall/... as normal events already.
        result = await drive(handler, ui.responder(), ui.on_event, debug_steps, (store, run_id, question))
        return await ui.collect(result)

    console.print(f"[dim]run {run_id}, memory session {session!r}[/]")
    ui.finish(asyncio.run(go()))


@app.command()
def cost() -> None:
    """Show P2 spend so far from runs/costs.jsonl."""
    ledger = get_settings().p2_runs_dir / "costs.jsonl"
    rows = [json.loads(line) for line in ledger.read_text().splitlines()] if ledger.exists() else []
    total = sum(r["cost_usd"] for r in rows)
    console.print(f"{len(rows)} calls, ${total:.6f} of ${get_settings().p2_spend_cap_usd:.2f} cap")


if __name__ == "__main__":
    app()
