"""Workflow 3: the same review as four FunctionAgents that hand off to each other (spec §8).

    Planner ──handoff──▶ Researcher ──handoff──▶ Writer ──handoff──▶ Reviewer
       ▲                    │                     ▲                    │
       └──── re-scope ──────┘                     └──── revisions ─────┘

Workflow 2 (review.py) spells out every step and event; here the LLM decides which tool to call
next and when to hand off. Both run on the same engine: AgentWorkflow *is* a Workflow (its steps are
init_run -> setup_agent -> run_agent_step -> call_tool -> aggregate_tool_results, looping), so the
same streaming, Context serialization and HITL machinery apply.

What stays deterministic, on purpose, for a fair comparison: retrieval (the same query engine), claim
validation (node ids must come from a search the Researcher ran; quotes must be found in the chunk),
the citation check (the same child workflow), and rendering (render.py). What the agents decide:
the plan, which searches to run, the outline, the prose, when to revise and when to stop.

Tools get their dependencies by closure (`AgentDeps`), not Workflow Resources: an AgentWorkflow's
steps are LlamaIndex's, so there is no step signature to annotate. Shared state lives in the Context:
`ctx.store["state"]` (small; AgentWorkflow injects it into the first prompt) and `ctx.store["review"]`
(findings, outline, sections; read and written only by tools).
"""

# No `from __future__ import annotations` here: FunctionTool finds the Context parameter by comparing
# the annotation object with the Context class, and postponed (string) annotations never match, so
# tools would be called without ctx.
import asyncio
from dataclasses import dataclass
from typing import Any

from llama_index.core.agent.workflow import AgentWorkflow, BaseWorkflowAgent, FunctionAgent
from llama_index.core.llms import LLM
from llama_index.core.memory import Memory
from llama_index.core.query_engine import RetrieverQueryEngine
from llama_index.core.schema import QueryBundle
from llama_index.core.workflow import Context  # the same class as workflows.Context; tools need this name
from pydantic import BaseModel, ValidationError
from rapidfuzz import fuzz

from litreview.bib import strip_unknown_markers
from litreview.config import get_settings
from litreview.corpus import PaperMeta
from litreview.events import OutlineApprovalRequired, OutlineDecision
from litreview.models import Citation, CitationIssue, FindingClaim, FindingRecord, Outline
from litreview.render import DraftSection, out_dir, render_review
from litreview.resources import get_llm, get_storage, shared_resources
from litreview.retrieval.pipeline import Storage
from litreview.workflows.citation_check import CheckRequest, CitationCheckWorkflow, ClaimRef, SectionText

MAX_OUTLINE_ATTEMPTS = 3
MAX_CHECKS = 3  # same bound as Workflow 2: check, revise, check, revise, check
# AgentWorkflow stops a run after this many agent turns (default 20). A full review is ~30 turns
# (plan, 2 per sub-question, outline, 1 per section, checks, handoffs); this leaves room for revisions.
MAX_ITERATIONS = 120
KICKOFF = "Write the literature review for the research question in the current state."
EXCERPT_CHARS = 700  # per search hit shown to the Researcher (agents re-send their whole history)
QUOTE_MATCH_THRESHOLD = 85


class ClaimInput(BaseModel):
    statement: str
    node_id: str
    quote: str


@dataclass
class AgentDeps:
    engine: RetrieverQueryEngine
    storage: Storage
    llm: LLM  # Planner, Researcher, Reviewer and the citation check
    writer_llm: LLM  # Writer (Sonnet with --final)
    papers: dict[str, PaperMeta]
    summaries: dict[str, str]
    check_llm: LLM | None = None  # the citation check's judge; defaults to `llm`


def empty_review() -> dict[str, Any]:
    return {
        "sub_questions": [],
        "seen_nodes": [],  # node ids returned by search_corpus: the only ones a claim may cite
        "findings": {},  # str(idx) -> FindingRecord dump
        "outline": None,
        "outline_attempts": 0,
        "sections": {},  # str(section_idx) -> DraftSection fields
        "check_rounds": 0,
        "last_issues": [],
        "log": [],
        "result": None,  # ReviewReady dump, set by finalize_review
    }


async def _review(ctx: Context) -> dict[str, Any]:
    return await ctx.store.get("review", default=None) or empty_review()


class ReviewTools:
    """Every tool an agent can call. `ctx: Context` first = AgentWorkflow passes the run's Context."""

    def __init__(self, deps: AgentDeps) -> None:
        self.deps = deps

    async def _edit(self, ctx: Context, fn) -> Any:
        async with ctx.store.edit_state() as s:  # one lock for read-modify-write, like Workflow 2
            review = s.get("review") or empty_review()
            out = fn(review)
            s["review"] = review
        return out

    # ---------- Planner ----------
    async def record_subquestions(self, ctx: Context, sub_questions: list[str]) -> str:
        """Record 3-5 non-overlapping sub-questions that together answer the research question."""
        qs = [q.strip() for q in sub_questions if q.strip()][:6]

        def apply(r):
            r["sub_questions"], r["findings"] = qs, {}
            r["log"].append(f"plan: {len(qs)} sub-questions")

        await self._edit(ctx, apply)
        listing = "\n".join(f"{i}. {q}" for i, q in enumerate(qs, start=1))
        return f"Recorded:\n{listing}\nNow hand off to the Researcher."

    # ---------- Researcher ----------
    async def search_corpus(self, ctx: Context, query: str) -> str:
        """Search the paper corpus. Returns up to 5 passages, each with the node_id to cite it by."""
        nodes = await asyncio.to_thread(self.deps.engine.retrieve, QueryBundle(query))

        def apply(r):
            r["seen_nodes"] = sorted(set(r["seen_nodes"]) | {n.node.node_id for n in nodes})
            r["log"].append(f"search: {query!r} -> {len(nodes)} passages")

        await self._edit(ctx, apply)
        blocks = []
        for n in nodes:
            m = n.node.metadata
            title = self.deps.papers[m["arxiv_id"]].title if m.get("arxiv_id") in self.deps.papers else "?"
            text = n.node.get_content()[:EXCERPT_CHARS]
            blocks.append(f"node_id: {n.node.node_id}\n({title}, p. {m.get('page')})\n{text}")
        return "\n\n".join(blocks) or "No passages found."

    async def get_paper_summary(self, ctx: Context, arxiv_id: str) -> str:
        """A ~200-word summary of one paper (from ingestion), for orientation; not citable."""
        return self.deps.summaries.get(arxiv_id, f"No summary for {arxiv_id}.")

    async def record_finding(
        self, ctx: Context, sub_question_idx: int, claims: list[ClaimInput], gap: str | None = None
    ) -> str:
        """Record the answer to one sub-question (1-based) as claims. Each claim cites one node_id
        from your searches and quotes it verbatim (max 25 words). Say what is unanswered in `gap`."""
        review = await _review(ctx)
        if not 1 <= sub_question_idx <= len(review["sub_questions"]):
            return f"Error: sub_question_idx must be 1..{len(review['sub_questions'])}."
        seen, docstore = set(review["seen_nodes"]), self.deps.storage.index.docstore.docs
        accepted: list[FindingClaim] = []
        rejected: list[str] = []
        for raw in claims:
            try:
                c = ClaimInput.model_validate(raw)
            except ValidationError as e:
                rejected.append(f"malformed claim ({e.errors()[0]['msg']})")
                continue
            node = docstore.get(c.node_id) if c.node_id in seen else None
            if node is None:
                rejected.append(f"{c.node_id}: not a node_id from your searches")
                continue
            if fuzz.partial_ratio(c.quote.lower(), node.get_content().lower()) < QUOTE_MATCH_THRESHOLD:
                rejected.append(f"{c.node_id}: quote not found in that passage")
                continue
            accepted.append(
                FindingClaim(
                    claim_id=f"{sub_question_idx}.{len(accepted) + 1}",
                    statement=c.statement,
                    citation=Citation(
                        arxiv_id=node.metadata["arxiv_id"],
                        node_id=c.node_id,
                        page=node.metadata.get("page"),
                        quote=c.quote[:300],
                        quote_verified=True,
                    ),
                )
            )
        record = FindingRecord(
            idx=sub_question_idx,
            sub_question=review["sub_questions"][sub_question_idx - 1],
            claims=accepted,
            gap=gap,
        )

        def apply(r):
            r["findings"][str(sub_question_idx)] = record.model_dump()
            r["log"].append(f"finding {sub_question_idx}: {len(accepted)} claims, {len(rejected)} rejected")
            return [i for i in range(1, len(r["sub_questions"]) + 1) if str(i) not in r["findings"]]

        missing = await self._edit(ctx, apply)
        msg = f"Recorded {len(accepted)} claim(s) for sub-question {sub_question_idx}."
        if rejected:
            msg += " Rejected: " + "; ".join(rejected)
        msg += (
            f" Still to research: {missing}."
            if missing
            else " All sub-questions done: hand off to the Writer."
        )
        return msg

    # ---------- Writer ----------
    async def get_findings(self, ctx: Context) -> str:
        """All recorded claims, grouped by sub-question, each with the marker to cite it by, e.g. [2.3]."""
        review = await _review(ctx)
        blocks = []
        for key in sorted(review["findings"], key=int):
            f = FindingRecord.model_validate(review["findings"][key])
            lines = [f"Finding {f.idx}: {f.sub_question}"]
            lines += [
                f"  [{c.claim_id}] {c.statement} ({self.deps.papers[c.citation.arxiv_id].title})"
                for c in f.claims
            ]
            if f.gap:
                lines.append(f"  gap: {f.gap}")
            blocks.append("\n".join(lines))
        return "\n\n".join(blocks) or "No findings recorded yet."

    async def propose_outline(self, ctx: Context, outline: Outline) -> str:
        """Propose the review's outline (4-7 sections incl. introduction and conclusion; finding_ids per
        section). A human approves, edits or rejects it; this call waits for that answer."""
        try:
            proposed = Outline.model_validate(outline)
        except ValidationError as e:
            return f"Invalid outline: {e}"
        review = await _review(ctx)
        attempt = review["outline_attempts"] + 1
        # HITL pattern C. wait_for_event emits the waiter event to the caller's stream and pauses this
        # tool call. When the answer arrives, the runtime *replays this step from the top*, so nothing
        # above this line may change state; all writes come after.
        decision = await ctx.wait_for_event(
            OutlineDecision,
            waiter_event=OutlineApprovalRequired(outline=proposed, attempt=attempt),
            waiter_id=f"outline-{attempt}",
        )
        overruled = decision.action == "reject" and attempt >= MAX_OUTLINE_ATTEMPTS
        if decision.action == "reject" and not overruled:
            await self._edit(ctx, lambda r: r.update(outline_attempts=attempt))
            return f"Rejected by the reader: {decision.feedback}. Propose a revised outline."
        chosen = (
            decision.edited_outline if decision.action == "edit" and decision.edited_outline else proposed
        )

        def apply(r):
            r.update(outline=chosen.model_dump(), outline_attempts=attempt, sections={})
            r["log"].append(f"outline attempt {attempt}: {decision.action}")

        await self._edit(ctx, apply)
        sections = "\n".join(f"{i}. {s.heading}" for i, s in enumerate(chosen.sections))
        note = " (third rejection overruled)" if overruled else ""
        return (
            f"Outline {decision.action}d{note}. Write every section with write_section, by index:\n"
            f"{sections}\nThen hand off to the Reviewer."
        )

    async def write_section(self, ctx: Context, section_idx: int, markdown: str) -> str:
        """Save (or replace) one section's text: Markdown prose, no heading. Every factual sentence ends
        with claim markers from get_findings, e.g. [2.3]; invented markers are removed."""
        review = await _review(ctx)
        if review["outline"] is None:
            return "Error: no approved outline yet; call propose_outline first."
        outline = Outline.model_validate(review["outline"])
        if not 0 <= section_idx < len(outline.sections):
            return f"Error: section_idx must be 0..{len(outline.sections) - 1}."
        known = {c["claim_id"] for f in review["findings"].values() for c in f["claims"]}
        text, unknown = strip_unknown_markers(markdown.strip(), known)

        def apply(r):
            r["sections"][str(section_idx)] = {
                "heading": outline.sections[section_idx].heading,
                "markdown": text,
                "unknown_markers": unknown,
            }
            r["log"].append(f"section {section_idx}: {len(text.split())} words, {unknown} invented markers")
            return [i for i in range(len(outline.sections)) if str(i) not in r["sections"]]

        missing = await self._edit(ctx, apply)
        removed = f" Removed {unknown} marker(s) that match no claim." if unknown else ""
        tail = (
            f" Sections still missing: {missing}."
            if missing
            else " All sections written: hand off to the Reviewer."
        )
        return f"Saved section {section_idx}.{removed}{tail}"

    # ---------- Reviewer ----------
    async def check_citations(self, ctx: Context) -> str:
        """Check every cited sentence against its passage (deterministic checks + a judge model)."""
        review = await _review(ctx)
        outline = Outline.model_validate(review["outline"]) if review["outline"] else None
        if outline is None or len(review["sections"]) < len(outline.sections):
            return "Not all sections are written yet; hand off to the Writer."
        if review["check_rounds"] >= MAX_CHECKS:
            return "Check limit reached. Call finalize_review now."
        claims = {
            c["claim_id"]: ClaimRef(node_id=c["citation"]["node_id"], quote=c["citation"]["quote"])
            for f in review["findings"].values()
            for c in f["claims"]
        }
        sections = [
            SectionText(section_idx=int(k), heading=v["heading"], markdown=v["markdown"])
            for k, v in sorted(review["sections"].items(), key=lambda kv: int(kv[0]))
        ]
        judge = self.deps.check_llm or self.deps.llm
        manager = await shared_resources({get_storage: self.deps.storage, get_llm: judge})
        report = await CitationCheckWorkflow(timeout=600, resource_manager=manager).run(
            start_event=CheckRequest(sections=sections, claims=claims)
        )

        def apply(r):
            r["check_rounds"] += 1
            r["last_issues"] = [i.model_dump() for i in report.issues]
            r["log"].append(f"check {r['check_rounds']}: {len(report.issues)} issues")
            return r["check_rounds"]

        rounds = await self._edit(ctx, apply)
        if not report.issues:
            return "No citation issues. Call finalize_review."
        listing = "\n".join(
            f"- section {i.section_idx}: {i.problem}: {i.claim} ({i.suggested_fix})" for i in report.issues
        )
        if rounds >= MAX_CHECKS:
            last = "that was the last check"
            return f"{len(report.issues)} issue(s) remain; {last}:\n{listing}\nCall finalize_review."
        return (
            f"{len(report.issues)} issue(s):\n{listing}\nCall request_revision for each flagged section, "
            "then hand off to the Writer listing what to fix."
        )

    async def request_revision(self, ctx: Context, section_idx: int, reason: str) -> str:
        """Ask the Writer to fix one section; give the flagged sentence and the problem as `reason`."""
        await self._edit(ctx, lambda r: r["log"].append(f"revision requested for {section_idx}: {reason}"))
        return f"Noted for section {section_idx}. When done, hand off to the Writer with the list."

    async def finalize_review(self, ctx: Context) -> str:
        """Write review.md, refs.bib and citations.json. Call once, at the end."""
        review = await _review(ctx)
        state = await ctx.store.get("state")
        if review["outline"] is None or not review["sections"]:
            return "Nothing to finalize yet."
        outline = Outline.model_validate(review["outline"])
        sections = [DraftSection(**review["sections"][k]) for k in sorted(review["sections"], key=int)]
        result = render_review(
            out_dir(state["question"]) / "agent",
            state["question"],
            outline.title,
            sections,
            [FindingRecord.model_validate(f) for f in review["findings"].values()],
            self.deps.papers,
            self.deps.storage.index.docstore.docs,
            review["log"],
            [CitationIssue.model_validate(i) for i in review["last_issues"]],
            review["check_rounds"],
            0.0,  # the caller measures cost from the ledger
        )
        await self._edit(ctx, lambda r: r.update(result=result.model_dump()))
        return f"Review written to {result.markdown_path}. You are done: reply with a one-line summary."


PLANNER = """You are the Planner of a literature-review team. The research question and audience are
in the current state. Break the question into 3-5 non-overlapping sub-questions answerable from a
corpus of ML papers on multi-agent LLM orchestration (prefer comparative / mechanism questions),
record them with record_subquestions, then hand off to the Researcher. If the Researcher hands back
because sub-questions can't be answered, record better ones."""

RESEARCHER = """You are the Researcher. For each recorded sub-question, in order: run 1-2 search_corpus
queries (get_paper_summary is optional, for orientation), then call record_finding with up to 6 claims.
Each claim is one factual sentence supported by one passage: give that passage's node_id and a short
verbatim quote from it. Never cite anything you did not get from search_corpus. Prefer claims from
different papers. When every sub-question has a finding, hand off to the Writer. If sub-questions
cannot be answered from the corpus, hand off to the Planner and say why."""

WRITER = """You are the Writer. Call get_findings, then propose_outline (4-7 sections, introduction
first, conclusion last, finding_ids per body section); it waits for a human decision. If rejected,
propose a revised outline. Once approved, write every section with write_section (index from 0):
about {words} words each, synthesizing across claims, every factual sentence ending with markers from
get_findings like [2.3] or [1.1, 3.2], never invented markers, no heading line. Then hand off to the
Reviewer. If the Reviewer hands back with revisions, rewrite only those sections, then hand off again."""

REVIEWER = """You are the Reviewer. Call check_citations. If it reports issues and allows another round,
call request_revision for each flagged section and hand off to the Writer, listing the sentences to
fix. Otherwise call finalize_review, then reply with a one-line summary."""


def build_agent_review(
    deps: AgentDeps, question: str, audience: str = "ML engineers", target_words: int = 1500
):
    tools = ReviewTools(deps)
    words = max(120, target_words // 6)
    agents: list[BaseWorkflowAgent] = [
        FunctionAgent(
            name="Planner",
            description="Breaks the research question into sub-questions.",
            system_prompt=PLANNER,
            tools=[tools.record_subquestions],
            llm=deps.llm,
            can_handoff_to=["Researcher"],
        ),
        FunctionAgent(
            name="Researcher",
            description="Searches the corpus and records grounded claims per sub-question.",
            system_prompt=RESEARCHER,
            tools=[tools.search_corpus, tools.get_paper_summary, tools.record_finding],
            llm=deps.llm,
            can_handoff_to=["Planner", "Writer"],
        ),
        FunctionAgent(
            name="Writer",
            description="Outlines (with human approval) and writes the review from recorded claims.",
            system_prompt=WRITER.format(words=words),
            tools=[tools.get_findings, tools.propose_outline, tools.write_section],
            llm=deps.writer_llm,
            can_handoff_to=["Reviewer"],
        ),
        FunctionAgent(
            name="Reviewer",
            description="Checks citations, requests revisions, and finalizes the review.",
            system_prompt=REVIEWER,
            tools=[tools.check_citations, tools.request_revision, tools.finalize_review],
            llm=deps.llm,
            can_handoff_to=["Writer"],
        ),
    ]
    return AgentWorkflow(
        agents=agents,
        root_agent="Planner",
        initial_state={"question": question, "audience": audience},
        timeout=3600,
    )


def agent_memory(session_id: str) -> Memory:
    """The agents' shared conversation, kept in SQLite under `session_id` (runs/agent_memory.db).

    It has to live outside the Context: AgentWorkflow's "memory" key is on the state store's
    known-unserializable list, so `ctx.to_dict()` skips it ("set it manually after deserialization").
    A detached run re-attaches it with `attach_memory`; a follow-up question with the same session id
    starts with the earlier conversation in context.
    """
    db = get_settings().p2_runs_dir / "agent_memory.db"
    db.parent.mkdir(parents=True, exist_ok=True)
    return Memory.from_defaults(
        session_id=session_id,
        token_limit=200_000,  # keep the whole run; Haiku's window is far larger
        async_database_uri=f"sqlite+aiosqlite:///{db}",
    )


async def attach_memory(ctx: Context, session_id: str) -> None:
    await ctx.store.set("memory", agent_memory(session_id))


def start_agent_review(workflow: AgentWorkflow, session_id: str):
    """Start a run. max_iterations is stored in the Context, so a restored run keeps it."""
    return workflow.run(user_msg=KICKOFF, max_iterations=MAX_ITERATIONS, memory=agent_memory(session_id))


async def production_deps() -> AgentDeps:
    """The same Resources Workflow 2 uses, resolved once through one ResourceManager (so the query
    engine and the storage share one loaded index)."""
    from workflows.resource import Resource, ResourceManager

    from litreview.resources import get_papers, get_query_engine, get_writer_llm
    from litreview.retrieval.summaries import load_all_summaries

    manager = ResourceManager()
    return AgentDeps(
        engine=await manager.get(Resource(get_query_engine)),
        storage=await manager.get(Resource(get_storage)),
        llm=await manager.get(Resource(get_llm)),
        writer_llm=await manager.get(Resource(get_writer_llm)),
        papers=await manager.get(Resource(get_papers)),
        summaries=load_all_summaries(get_settings().p2_data_dir / "summaries"),
    )


async def agent_result(ctx: Context) -> dict[str, Any] | None:
    """The ReviewReady written by finalize_review, if the agents got that far."""
    return (await _review(ctx))["result"]
