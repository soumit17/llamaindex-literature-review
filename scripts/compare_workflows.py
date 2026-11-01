"""M6 comparison (spec §8.3): explicit Workflow 2 vs agentic Workflow 3 on the same questions.

For every (workflow, question, repeat) it records cost, tokens and LLM calls (from the ledger), wall
time, coverage (papers and passages cited), and a citation score computed the same way for both: the
CitationCheckWorkflow re-checks each draft, and the score is the share of cited sentences with no
issue. Outlines of repeat 1 and 2 are compared for determinism. Orchestration size is counted from
the source. Results: docs/explicit-vs-agentic.md (with rows for your own notes) and
evals/reports/compare.json.

Both workflows run with the outline auto-approved and the dev model (Haiku) everywhere.

    uv run python scripts/compare_workflows.py                   # 3 questions x 2 repeats (~$0.5-1)
    uv run python scripts/compare_workflows.py --questions 1 --repeats 1   # a quick look (~$0.1)
"""

from __future__ import annotations

import ast
import asyncio
import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import typer
from rich.console import Console
from rich.prompt import Confirm
from workflows.resource import Resource, ResourceManager

from litreview.config import PROJECT_ROOT, get_settings
from litreview.events import ReviewReady, ReviewRequest
from litreview.hitl import auto_responder, drive
from litreview.render import out_dir
from litreview.resources import get_llm, get_storage, shared_resources
from litreview.workflows.agent_review import (
    agent_result,
    build_agent_review,
    production_deps,
    start_agent_review,
)
from litreview.workflows.citation_check import (
    CheckRequest,
    CitationCheckWorkflow,
    ClaimRef,
    SectionText,
    cited_ids,
    split_sentences,
)
from litreview.workflows.review import ReviewWorkflow

QUESTIONS = [
    "What orchestration patterns do LLM-based multi-agent systems use, and how do they trade off control, "
    "cost and robustness?",
    "How do multi-agent LLM systems decide which agent acts next, and what does each approach cost?",
    "What communication topologies do LLM agent teams use, and how does topology affect task performance?",
]
DOC = PROJECT_ROOT / "docs" / "explicit-vs-agentic.md"
COLUMNS = [
    "workflow",
    "runs ok",
    "cost / run",
    "tokens / run",
    "LLM calls / run",
    "wall time",
    "citation score",
    "papers / passages cited",
    "outline overlap (repeat 1 vs 2)",
    "orchestration LOC",
]
HEADER = "| " + " | ".join(COLUMNS) + " |\n" + "|---" * len(COLUMNS) + "|"
REPORT = PROJECT_ROOT / "evals" / "reports" / "compare.json"
console = Console()


@dataclass
class RunMetrics:
    workflow: str
    question: int
    repeat: int
    ok: bool
    seconds: float
    llm_calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: float
    papers: int
    passages: int
    cited_sentences: int
    sentences_with_issues: int
    outline: list[str]
    error: str | None = None

    @property
    def citation_score(self) -> float | None:
        if not self.cited_sentences:
            return None
        return 1 - self.sentences_with_issues / self.cited_sentences


def ledger_rows() -> list[dict]:
    path = get_settings().p2_runs_dir / "costs.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines() if line] if path.exists() else []


async def recheck(folder: Path, storage, judge) -> tuple[int, int]:
    """(cited sentences, cited sentences with an issue), by the same checker for both workflows."""
    draft = json.loads((folder / "draft.json").read_text())
    findings = json.loads((folder / "findings.json").read_text())
    claims = {
        c["claim_id"]: ClaimRef(node_id=c["citation"]["node_id"], quote=c["citation"]["quote"])
        for f in findings
        for c in f["claims"]
    }
    sections = [
        SectionText(section_idx=i, heading=s["heading"], markdown=s["markdown"])
        for i, s in enumerate(draft["sections"])
    ]
    manager = await shared_resources({get_storage: storage, get_llm: judge})
    report = await CitationCheckWorkflow(timeout=600, resource_manager=manager).run(
        start_event=CheckRequest(sections=sections, claims=claims)
    )
    cited = sum(1 for s in sections for sent in split_sentences(s.markdown) if cited_ids(sent))
    flagged = {(i.section_idx, i.claim) for i in report.issues if i.problem != "no_citation"}
    return cited, len(flagged)


def coverage(folder: Path) -> tuple[int, int]:
    refs = json.loads((folder / "citations.json").read_text())
    return len({r["arxiv_id"] for r in refs}), len(refs)


async def run_one(workflow: str, qi: int, repeat: int, storage, judge) -> RunMetrics:
    question = QUESTIONS[qi]
    before, started = len(ledger_rows()), time.monotonic()
    error = None
    folder = out_dir(question) / ("agent" if workflow == "agentic" else "")
    try:
        if workflow == "explicit":
            handler = ReviewWorkflow(timeout=3600).run(start_event=ReviewRequest(question=question))
            result = await drive(handler, auto_responder)
            assert isinstance(result, ReviewReady)  # auto_responder never detaches
            error = result.error
        else:
            handler = start_agent_review(
                build_agent_review(await production_deps(), question), f"compare-{qi}-{repeat}"
            )
            await drive(handler, auto_responder)
            if await agent_result(handler.ctx) is None:
                error = "agents stopped without finalize_review"
    except Exception as e:  # a failed run is a data point, not a reason to stop the comparison
        error = f"{type(e).__name__}: {e}"
    seconds = time.monotonic() - started
    rows = ledger_rows()[before:]
    metrics = RunMetrics(
        workflow=workflow,
        question=qi + 1,
        repeat=repeat,
        ok=error is None,
        seconds=round(seconds, 1),
        llm_calls=len(rows),
        input_tokens=sum(r["input_tokens"] for r in rows),
        output_tokens=sum(r["output_tokens"] for r in rows),
        cost_usd=round(sum(r["cost_usd"] for r in rows), 5),
        papers=0,
        passages=0,
        cited_sentences=0,
        sentences_with_issues=0,
        outline=[],
        error=error,
    )
    if error is None:
        metrics.papers, metrics.passages = coverage(folder)
        metrics.outline = [s["heading"] for s in json.loads((folder / "draft.json").read_text())["sections"]]
        metrics.cited_sentences, metrics.sentences_with_issues = await recheck(folder, storage, judge)
    return metrics


def code_lines(path: Path) -> int:
    """Lines of code without blank lines, comments and docstrings."""
    source = path.read_text()
    docstring_lines: set[int] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(
            node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
        ) and ast.get_docstring(node):
            first = node.body[0]
            docstring_lines.update(range(first.lineno, (first.end_lineno or first.lineno) + 1))
    return sum(
        1
        for n, line in enumerate(source.splitlines(), start=1)
        if line.strip() and not line.strip().startswith("#") and n not in docstring_lines
    )


def overlap(a: list[str], b: list[str]) -> float:
    norm = lambda hs: {re.sub(r"[^a-z ]", "", h.lower()).strip() for h in hs}  # noqa: E731
    sa, sb = norm(a), norm(b)
    return len(sa & sb) / len(sa | sb) if sa | sb else 1.0


def mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def fmt(x: float | None, spec: str) -> str:
    return "n/a" if x is None else format(x, spec)


def write_doc(runs: list[RunMetrics], n_questions: int, repeats: int) -> None:
    src = PROJECT_ROOT / "src" / "litreview" / "workflows"
    loc = {"explicit": code_lines(src / "review.py"), "agentic": code_lines(src / "agent_review.py")}
    rows = []
    for wf in ("explicit", "agentic"):
        ok = [r for r in runs if r.workflow == wf and r.ok]
        det = [
            overlap(a.outline, b.outline)
            for a in ok
            for b in ok
            if a.question == b.question and a.repeat == 1 and b.repeat == 2
        ]
        rows.append(
            f"| {wf} | {len(ok)}/{len([r for r in runs if r.workflow == wf])} "
            f"| ${fmt(mean([r.cost_usd for r in ok]), '.4f')} "
            f"| {fmt(mean([r.input_tokens + r.output_tokens for r in ok]), ',.0f')} "
            f"| {fmt(mean([r.llm_calls for r in ok]), '.0f')} "
            f"| {fmt(mean([r.seconds for r in ok]), '.0f')}s "
            f"| {fmt(mean([s for r in ok if (s := r.citation_score) is not None]), '.0%')} "
            f"| {fmt(mean([r.papers for r in ok]), '.1f')} / {fmt(mean([r.passages for r in ok]), '.1f')} "
            f"| {fmt(mean(det), '.0%') if det else 'n/a'} "
            f"| {loc[wf]} |"
        )
    per_run = [
        f"| {r.workflow} | Q{r.question} | {r.repeat} | {'ok' if r.ok else 'FAILED: ' + (r.error or '')[:60]}"
        " "
        f"| ${r.cost_usd:.4f} | {r.llm_calls} | {r.seconds:.0f}s | {fmt(r.citation_score, '.0%')} "
        f"| {r.papers}/{r.passages} |"
        for r in runs
    ]
    questions = "\n".join(f"{i}. {q}" for i, q in enumerate(QUESTIONS[:n_questions], start=1))
    DOC.write_text(
        f"""# Explicit (Workflow 2) vs agentic (Workflow 3)

Same corpus, retrieval, claim validation, citation checker and renderer; Haiku for every call; outline
auto-approved. {n_questions} question(s) x {repeats} repeat(s), generated by `scripts/compare_workflows.py`.

{questions}

{HEADER}
{chr(10).join(rows)}

- **citation score**: share of cited sentences the CitationCheckWorkflow finds no problem with, re-checked
  the same way for both drafts (deterministic checks + Haiku judge).
- **outline overlap**: Jaccard overlap of section headings between two runs of the same question
  (1.0 = identical outline): a rough determinism measure.
- **orchestration LOC**: code lines (no blanks, comments, docstrings) of `workflows/review.py` vs
  `workflows/agent_review.py`. Shared code (retrieval, check, render) is not counted for either.

## Per run

| workflow | question | repeat | status | cost | LLM calls | time | citation score | papers/passages |
|---|---|---|---|---|---|---|---|---|
{chr(10).join(per_run)}

## Your notes

- **Debuggability** (spec §8.3): when something went wrong, which was easier to diagnose, and why?
- Where did the agentic version spend its extra tokens? (Each agent turn resends the shared history.)
- Which would you ship, for what kind of task?
"""
    )
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps([{**asdict(r), "citation_score": r.citation_score} for r in runs], indent=2))


async def run(n_questions: int, repeats: int) -> None:
    manager = ResourceManager()
    storage = await manager.get(Resource(get_storage))
    judge = await manager.get(Resource(get_llm))
    runs: list[RunMetrics] = []
    for qi in range(n_questions):
        for repeat in range(1, repeats + 1):
            for wf in ("explicit", "agentic"):
                console.print(f"[cyan]{wf}[/] Q{qi + 1} repeat {repeat} ...")
                m = await run_one(wf, qi, repeat, storage, judge)
                runs.append(m)
                score = fmt(m.citation_score, ".0%")
                status = "ok" if m.ok else f"[red]failed[/]: {m.error}"
                console.print(
                    f"  {status}  ${m.cost_usd:.4f}  {m.llm_calls} calls  {m.seconds:.0f}s  citations {score}"
                )
                write_doc(runs, n_questions, repeats)  # keep partial results if a later run fails
    console.print(f"wrote {DOC} and {REPORT}")


def main(
    questions: int = typer.Option(3, help="How many of the 3 questions."),
    repeats: int = typer.Option(2, help="Runs per question and workflow (2 measures determinism)."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the cost confirmation."),
) -> None:
    if not get_settings().anthropic_api_key:
        raise typer.BadParameter("ANTHROPIC_API_KEY is not set")
    n = questions * repeats
    console.print(f"{n} explicit + {n} agentic runs: roughly ${0.04 * n:.2f}-${0.15 * n:.2f} on Haiku.")
    if not yes and not Confirm.ask("Go?", default=True):
        raise typer.Exit(1)
    asyncio.run(run(questions, repeats))


if __name__ == "__main__":
    typer.run(main)
