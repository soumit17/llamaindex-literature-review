"""Workflow 2: literature review (spec §7). Question -> sub-questions -> findings -> outline -> sections.

Event flow (no graph is written down; it follows from the step signatures):

    ReviewRequest ─scope─▶ QuestionScoped                     branch: specific enough
                       └─▶ NeedsClarification ··caller··▶ Clarified      branch: too vague (HITL)
    QuestionScoped | Clarified | ReplanRequested ─plan─▶ SubQuestion ×N   fan-out via ctx.send_event
    SubQuestion ─research (4 workers)─▶ Finding               failure -> on_research_failed -> Finding(error)
    Finding ×N ─gather_findings─▶ FindingsReady               fan-in via ctx.collect_events
    FindingsReady ─draft_outline─▶ OutlineApprovalRequired ··caller··▶ OutlineDecision   (HITL)
    OutlineDecision ─on_outline_decision─▶ list[WriteSection]  fan-out by returning a list
                                       └─▶ ReplanRequested     reject: loop back to plan (<= 3 outlines)
    WriteSection ─write_section (3 workers)─▶ SectionDraft    tokens streamed as SectionToken
    list[SectionDraft] ─assemble─▶ DraftAssembled             fan-in by list parameter
    DraftAssembled ─check_citations─▶ ReadyToFinalize         runs CitationCheckWorkflow (child)
                                 └─▶ CitationIssues ─revise─▶ list[WriteSection]  loop, <= 2 rounds
    ReadyToFinalize ─finalize─▶ ReviewReady                   review.md, refs.bib, citations.json
    Progress subclasses ─log_progress─▶ (state.log + stream)  accept_event_subclasses=True
    any other step failing ─on_any_failure─▶ ReviewReady(error) wildcard @catch_error: partial output

The "··caller··▶" hops are human-in-the-loop: the workflow emits an InputRequiredEvent on the stream
and waits; whoever runs it sends the HumanResponseEvent back (litreview.hitl). In M4 the CLI answers
automatically; M5 makes it interactive.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Annotated

from llama_index.core.llms import LLM, ChatMessage
from llama_index.core.query_engine import RetrieverQueryEngine
from llama_index.core.schema import QueryBundle
from rapidfuzz import fuzz
from workflows import Context, Workflow, catch_error, step
from workflows.events import StepFailedEvent
from workflows.resource import Resource

from litreview import prompts
from litreview.bib import strip_unknown_markers
from litreview.corpus import PaperMeta, Topic
from litreview.cost import CostTracker
from litreview.events import (
    CitationIssues,
    Clarified,
    DraftAssembled,
    Finding,
    FindingsReady,
    NeedsClarification,
    OutlineApprovalRequired,
    OutlineDecision,
    Progress,
    QuestionScoped,
    ReadyToFinalize,
    ReplanRequested,
    ResearchProgress,
    ReviewReady,
    ReviewRequest,
    SectionDraft,
    SectionToken,
    SubQuestion,
    WriteProgress,
    WriteSection,
)
from litreview.models import (
    Citation,
    FindingClaim,
    FindingRecord,
    Outline,
    ResearchAnswer,
    ScopeVerdict,
    SubQuestionPlan,
)
from litreview.render import DraftSection, atomic_write, out_dir, render_review
from litreview.resources import (
    get_cost_tracker,
    get_llm,
    get_papers,
    get_query_engine,
    get_storage,
    get_topic,
    get_writer_llm,
    shared_resources,
)
from litreview.retrieval.pipeline import Storage
from litreview.retry import LLM_RETRY, fix_note
from litreview.state import ReviewState, SectionDraftRecord
from litreview.workflows.citation_check import CheckRequest, CitationCheckWorkflow, ClaimRef, SectionText

MAX_OUTLINE_ATTEMPTS = 3
MAX_REVISIONS = 2  # citation check -> revise loop: at most 2 revise rounds, so at most 3 checks
QUOTE_MATCH_THRESHOLD = 85  # rapidfuzz partial_ratio, 0-100


class ReviewWorkflow(Workflow):
    # ---------- scope: a branch ----------
    @step(retry_policy=LLM_RETRY)
    async def scope(
        self,
        ctx: Context[ReviewState],
        ev: ReviewRequest,
        llm: Annotated[LLM, Resource(get_llm)],
        topic: Annotated[Topic, Resource(get_topic)],
        tracker: Annotated[CostTracker, Resource(get_cost_tracker)],
    ) -> QuestionScoped | NeedsClarification:
        # Two return types = two edges in the graph; the value returned picks the branch.
        async with ctx.store.edit_state() as state:
            state.question = ev.question
            state.audience, state.target_words = ev.audience, ev.target_words
            state.max_subquestions = ev.max_subquestions
            state.cost_at_start = tracker.spent_usd
        verdict = await llm.astructured_predict(
            ScopeVerdict, _prompt(prompts.SCOPE + fix_note(ctx)), topic=topic.topic, question=ev.question
        )
        if verdict.specific:
            return QuestionScoped(question=ev.question)
        return NeedsClarification(
            question=ev.question, reason=verdict.reason, suggestions=verdict.suggestions
        )

    # ---------- plan: fan-out with send_event ----------
    # The return annotation lists SubQuestion and Progress although the step returns None: that is
    # how validation and drawings learn about events a step emits with ctx.send_event.
    @step(retry_policy=LLM_RETRY)
    async def plan(
        self,
        ctx: Context[ReviewState],
        ev: QuestionScoped | Clarified | ReplanRequested,
        llm: Annotated[LLM, Resource(get_llm)],
        topic: Annotated[Topic, Resource(get_topic)],
    ) -> SubQuestion | Progress | None:
        state = await ctx.store.get_state()
        if isinstance(ev, Clarified):
            question = ev.refined_question
        elif isinstance(ev, QuestionScoped):
            question = ev.question
        else:
            question = state.question
        template = prompts.PLAN
        if state.replan_feedback:
            template += prompts.REPLAN_FEEDBACK.format(
                feedback="\n".join(f"- {f}" for f in state.replan_feedback)
            )
        result = await llm.astructured_predict(
            SubQuestionPlan,
            _prompt(template + fix_note(ctx)),
            question=question,
            topic=topic.topic,
            audience=state.audience,
            n_min=min(3, state.max_subquestions),
            n_max=state.max_subquestions,
        )
        planned = result.sub_questions[: state.max_subquestions]
        if not planned:
            raise ValueError("Structured output extraction failed: the plan has no sub-questions")
        async with ctx.store.edit_state() as s:  # before any send: gather_findings reads this count
            s.question = question
            s.sub_questions = [p.text for p in planned]
            s.expected_findings = len(planned)
            s.findings = {}
        ctx.send_event(Progress(stage="plan", message=f"{len(planned)} sub-questions. {result.scope_note}"))
        for i, p in enumerate(planned, start=1):
            ctx.send_event(SubQuestion(idx=i, text=p.text, rationale=p.rationale))
        return None

    # ---------- research: parallel workers ----------
    # num_workers=4: four sub-questions retrieve + answer at once. The query engine Resource is cached
    # on the workflow, so the index and reranker are loaded once and shared by all four.
    @step(num_workers=4, retry_policy=LLM_RETRY)
    async def research(
        self,
        ctx: Context[ReviewState],
        ev: SubQuestion,
        engine: Annotated[RetrieverQueryEngine, Resource(get_query_engine)],
        llm: Annotated[LLM, Resource(get_llm)],
        papers: Annotated[dict[str, PaperMeta], Resource(get_papers)],
    ) -> Finding | ResearchProgress:
        retry = ctx.retry_info()
        status = "retry" if retry.last_exception else "researching"
        ctx.send_event(ResearchProgress(stage="research", idx=ev.idx, status=status, message=ev.text))
        nodes = await asyncio.to_thread(engine.retrieve, QueryBundle(ev.text))  # embed + rerank: CPU
        titles = {k: p.title for k, p in papers.items()}
        answer = await llm.astructured_predict(
            ResearchAnswer,
            _prompt(prompts.RESEARCH + fix_note(ctx)),
            question=ev.text,
            excerpts=prompts.format_excerpts(nodes, titles),
        )
        claims = []
        for c in answer.claims:
            if not 1 <= c.excerpt <= len(nodes):  # the model may only cite excerpts it was shown
                continue
            node = nodes[c.excerpt - 1].node
            quote = c.quote.strip()[:300]
            verified = fuzz.partial_ratio(quote.lower(), node.get_content().lower()) >= QUOTE_MATCH_THRESHOLD
            claims.append(
                FindingClaim(
                    claim_id=f"{ev.idx}.{len(claims) + 1}",
                    statement=c.statement.strip(),
                    citation=Citation(
                        arxiv_id=node.metadata["arxiv_id"],
                        node_id=node.node_id,
                        page=node.metadata.get("page"),
                        quote=quote,
                        quote_verified=verified,
                    ),
                )
            )
        ctx.send_event(
            ResearchProgress(stage="research", idx=ev.idx, status="done", message=f"{len(claims)} claims")
        )
        return Finding(record=FindingRecord(idx=ev.idx, sub_question=ev.text, claims=claims, gap=answer.gap))

    # Once research's retries are exhausted: stand in a failed Finding so gather_findings still gets
    # its N events, and the review goes on without that sub-question (reported at the end).
    @catch_error(for_steps=["research"])
    async def on_research_failed(
        self, ctx: Context[ReviewState], ev: StepFailedEvent
    ) -> Finding | ResearchProgress:
        sub = ev.input_event
        error = f"{type(ev.exception).__name__}: {ev.exception}"
        ctx.send_event(ResearchProgress(stage="research", idx=sub.idx, status="failed", message=error[:200]))
        return Finding(record=FindingRecord(idx=sub.idx, sub_question=sub.text, error=error))

    # ---------- gather: fan-in with collect_events ----------
    # num_workers=1 so every Finding lands in the same collect buffer, one at a time.
    @step(num_workers=1)
    async def gather_findings(self, ctx: Context[ReviewState], ev: Finding) -> FindingsReady | None:
        state = await ctx.store.get_state()
        # Returns None (and this step run ends) until all N Findings have arrived. N came from `plan`:
        # unlike list fan-in, collect_events needs to be told how many to wait for.
        findings = ctx.collect_events(ev, [Finding] * state.expected_findings)
        if findings is None:
            return None
        records = [f.record for f in findings if isinstance(f, Finding)]
        async with ctx.store.edit_state() as s:
            s.findings = {r.idx: r for r in records}
        ok = [r for r in records if r.ok and r.claims]
        if not ok:
            raise RuntimeError("every sub-question failed or found nothing; no review to write")
        return FindingsReady(n_ok=len(ok), n_failed=len(records) - len(ok))

    @step(retry_policy=LLM_RETRY)
    async def draft_outline(
        self, ctx: Context[ReviewState], ev: FindingsReady, llm: Annotated[LLM, Resource(get_llm)]
    ) -> OutlineApprovalRequired | Progress:
        state = await ctx.store.get_state()
        records = sorted(state.findings.values(), key=lambda r: r.idx)
        outline = await llm.astructured_predict(
            Outline,
            _prompt(prompts.OUTLINE + fix_note(ctx)),
            audience=state.audience,
            question=state.question,
            findings=prompts.format_findings(records),
        )
        usable = {r.idx for r in records if r.ok and r.claims}
        for section in outline.sections:  # only findings that exist and succeeded
            section.finding_ids = [i for i in section.finding_ids if i in usable]
        async with ctx.store.edit_state() as s:
            s.outline = outline
            s.outline_attempts += 1
            attempt = s.outline_attempts
        ctx.send_event(Progress(stage="outline", message=f"outline attempt {attempt}: waiting for approval"))
        # An InputRequiredEvent goes to the caller's stream; the run waits for an OutlineDecision.
        return OutlineApprovalRequired(outline=outline, attempt=attempt)

    @step
    async def on_outline_decision(
        self, ctx: Context[ReviewState], ev: OutlineDecision
    ) -> list[WriteSection] | ReplanRequested | Progress:
        state = await ctx.store.get_state()
        if ev.action == "reject":
            if state.outline_attempts < MAX_OUTLINE_ATTEMPTS:
                async with ctx.store.edit_state() as s:
                    s.replan_feedback.append(ev.feedback or "Take a different angle.")
                return ReplanRequested(feedback=ev.feedback or "")  # loop: back to `plan`
            ctx.send_event(
                Progress(stage="outline", message=f"{MAX_OUTLINE_ATTEMPTS} outlines rejected; using the last")
            )
        outline = ev.edited_outline if ev.action == "edit" and ev.edited_outline else state.outline
        assert outline is not None
        async with ctx.store.edit_state() as s:
            s.outline = outline
            s.expected_sections = len(outline.sections)
        # Returning a list fans out, and opens the stream that `assemble` joins.
        return [
            WriteSection(section_idx=i, heading=sec.heading, points=sec.points, finding_ids=sec.finding_ids)
            for i, sec in enumerate(outline.sections)
        ]

    # ---------- write: parallel workers, streamed tokens ----------
    @step(num_workers=3, retry_policy=LLM_RETRY)
    async def write_section(
        self,
        ctx: Context[ReviewState],
        ev: WriteSection,
        llm: Annotated[LLM, Resource(get_writer_llm)],
        papers: Annotated[dict[str, PaperMeta], Resource(get_papers)],
    ) -> SectionDraft | WriteProgress:
        state = await ctx.store.get_state()
        assert state.outline is not None
        retrying = ctx.retry_info().last_exception is not None
        ctx.send_event(
            WriteProgress(
                stage="write",
                section_idx=ev.section_idx,
                status="retry" if retrying else "writing",
                message=ev.heading,
            )
        )
        records = _section_findings(state, ev.finding_ids)
        known = {c.claim_id for r in records for c in r.claims}
        words = max(120, state.target_words // max(1, state.expected_sections))
        claims_text = prompts.format_claims(records, {k: p.title for k, p in papers.items()})
        if ev.previous_markdown is not None:  # a revision requested by the citation check
            prompt = prompts.REVISE.format(
                heading=ev.heading,
                title=state.outline.title,
                audience=state.audience,
                notes="\n".join(f"- {n}" for n in ev.revision_notes),
                previous=ev.previous_markdown,
                claims=claims_text,
            )
        else:
            prompt = prompts.WRITE.format(
                heading=ev.heading,
                title=state.outline.title,
                audience=state.audience,
                points="; ".join(ev.points),
                claims=claims_text,
                words=words,
            )
        text = ""
        if retrying:  # tokens from the failed attempt are already on screen
            ctx.write_event_to_stream(SectionToken(section_idx=ev.section_idx, delta="", restart=True))
        async for chunk in await llm.astream_chat([ChatMessage(role="user", content=prompt)]):
            if chunk.delta:
                text += chunk.delta
                ctx.write_event_to_stream(SectionToken(section_idx=ev.section_idx, delta=chunk.delta))
        markdown, unknown = strip_unknown_markers(text.strip(), known)
        ctx.send_event(
            WriteProgress(stage="write", section_idx=ev.section_idx, status="done", message=ev.heading)
        )
        return SectionDraft(
            section_idx=ev.section_idx, heading=ev.heading, markdown=markdown, unknown_markers=unknown
        )

    @step
    async def assemble(self, ctx: Context[ReviewState], drafts: list[SectionDraft]) -> DraftAssembled:
        # List fan-in: fires once per batch of WriteSections, i.e. after on_outline_decision's list
        # (all sections) and again after each revise list (only the flagged ones). New drafts replace
        # old ones in state, so the assembled draft is always complete.
        async with ctx.store.edit_state() as s:
            for d in drafts:
                s.drafts[d.section_idx] = SectionDraftRecord(
                    heading=d.heading, markdown=d.markdown, unknown_markers=d.unknown_markers
                )
            outline, current = s.outline, dict(s.drafts)
        assert outline is not None
        return DraftAssembled(
            title=outline.title,
            sections=[
                SectionDraft(
                    section_idx=i, heading=d.heading, markdown=d.markdown, unknown_markers=d.unknown_markers
                )
                for i, d in sorted(current.items())
            ],
        )

    # ---------- citation check: a child workflow, then maybe a revise loop ----------
    @step
    async def check_citations(
        self,
        ctx: Context[ReviewState],
        ev: DraftAssembled,
        storage: Annotated[Storage, Resource(get_storage)],
        llm: Annotated[LLM, Resource(get_llm)],
    ) -> CitationIssues | ReadyToFinalize | Progress:
        state = await ctx.store.get_state()
        claims = {
            c.claim_id: ClaimRef(node_id=c.citation.node_id, quote=c.citation.quote)
            for r in state.findings.values()
            for c in r.claims
        }
        # The child gets the index and LLM this run already loaded, not fresh copies.
        manager = await shared_resources({get_storage: storage, get_llm: llm})
        report = await CitationCheckWorkflow(timeout=600, resource_manager=manager).run(
            start_event=CheckRequest(
                sections=[
                    SectionText(section_idx=d.section_idx, heading=d.heading, markdown=d.markdown)
                    for d in ev.sections
                ],
                claims=claims,
            )
        )
        async with ctx.store.edit_state() as s:
            s.citation_rounds += 1
            rounds, revisions = s.citation_rounds, s.revisions
        ctx.send_event(
            Progress(
                stage="check",
                message=f"round {rounds}: {len(report.issues)} issue(s) in {report.n_sentences} sentences "
                f"({report.n_judged} judged)",
            )
        )
        if report.issues and revisions < MAX_REVISIONS:
            return CitationIssues(issues=report.issues, round=rounds)  # loop: revise -> write -> assemble
        return ReadyToFinalize(title=ev.title, sections=ev.sections, remaining_issues=report.issues)

    @step
    async def revise(self, ctx: Context[ReviewState], ev: CitationIssues) -> list[WriteSection]:
        async with ctx.store.edit_state() as s:
            s.revisions += 1
            outline, drafts = s.outline, dict(s.drafts)
        assert outline is not None
        flagged: dict[int, list[str]] = {}
        for issue in ev.issues:
            note = f'{issue.problem}: "{issue.claim}"' + (
                f" ({issue.suggested_fix})" if issue.suggested_fix else ""
            )
            flagged.setdefault(issue.section_idx, []).append(note)
        return [  # only the flagged sections are rewritten
            WriteSection(
                section_idx=i,
                heading=outline.sections[i].heading,
                points=outline.sections[i].points,
                finding_ids=outline.sections[i].finding_ids,
                previous_markdown=drafts[i].markdown,
                revision_notes=notes,
            )
            for i, notes in sorted(flagged.items())
        ]

    # ---------- finalize: deterministic ----------
    @step
    async def finalize(
        self,
        ctx: Context[ReviewState],
        ev: ReadyToFinalize,
        papers: Annotated[dict[str, PaperMeta], Resource(get_papers)],
        storage: Annotated[Storage, Resource(get_storage)],
        tracker: Annotated[CostTracker, Resource(get_cost_tracker)],
    ) -> ReviewReady:
        state = await ctx.store.get_state()
        return render_review(
            out_dir(state.question),
            state.question,
            ev.title,
            [DraftSection(d.heading, d.markdown, d.unknown_markers) for d in ev.sections],
            list(state.findings.values()),
            papers,
            storage.index.docstore.docs,
            state.log,
            ev.remaining_issues,
            state.citation_rounds,
            tracker.spent_usd - state.cost_at_start,
        )

    # ---------- cross-cutting ----------
    # Routing is by exact type unless a step opts in: this one takes Progress *and* its subclasses.
    @step(num_workers=1, accept_event_subclasses=True)
    async def log_progress(self, ctx: Context[ReviewState], ev: Progress) -> None:
        async with ctx.store.edit_state() as s:
            s.log.append(f"{datetime.now(UTC):%H:%M:%S} [{ev.stage}] {type(ev).__name__}: {ev.message}")
        ctx.write_event_to_stream(ev)

    # Wildcard (no for_steps): any step other than research that exhausts its retries ends up here.
    # Graceful degradation: write what exists and stop, rather than lose the whole run.
    @catch_error
    async def on_any_failure(self, ctx: Context[ReviewState], ev: StepFailedEvent) -> ReviewReady:
        state = await ctx.store.get_state()
        cause = f"{type(ev.exception).__name__}: {ev.exception}"
        error = f"{ev.step_name} failed after {ev.attempts} attempt(s): {cause}"
        lines = [f"# Partial review: {state.question}", "", f"**Run failed.** {error}", ""]
        for r in sorted(state.findings.values(), key=lambda r: r.idx):
            lines.append(f"## {r.idx}. {r.sub_question}")
            lines += [
                f"- {c.statement} (arXiv:{c.citation.arxiv_id}, p. {c.citation.page})" for c in r.claims
            ]
            lines.append(f"- research failed: {r.error}" if r.error else "")
        path = out_dir(state.question or "failed-run") / "partial.md"
        atomic_write(path, "\n".join(lines) + "\n")
        return ReviewReady(
            markdown_path=str(path),
            bib_path="",
            n_citations=0,
            unsupported_claims=0,
            unknown_markers=0,
            failed_subquestions=[r.sub_question for r in state.findings.values() if not r.ok],
            cost_usd=0.0,
            error=error,
        )


def _prompt(template: str):
    from llama_index.core.prompts import PromptTemplate

    return PromptTemplate(template)


def _section_findings(state: ReviewState, finding_ids: list[int]) -> list[FindingRecord]:
    """The claims a section may cite: only those whose quote was found in the chunk during research.
    An unverified claim stays in the findings (and the log) but is never offered to the writer."""
    usable = []
    for r in sorted(state.findings.values(), key=lambda r: r.idx):
        verified = [c for c in r.claims if c.citation.quote_verified]
        if r.ok and verified:
            usable.append(r.model_copy(update={"claims": verified}))
    if finding_ids:
        return [r for r in usable if r.idx in finding_ids]
    # Introduction / conclusion: a few claims from every finding, to frame without repeating.
    return [r.model_copy(update={"claims": r.claims[:3]}) for r in usable]
