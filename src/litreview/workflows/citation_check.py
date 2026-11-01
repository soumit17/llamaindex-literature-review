"""CitationCheckWorkflow: the child workflow that checks a drafted review's citations (spec §7.3).

    CheckRequest ─split_and_check─▶ list[JudgeBatch]   deterministic checks, then batches of <= 10
                               └──▶ CitationReport      (nothing left for the LLM to judge)
    JudgeBatch ─judge (2 workers)─▶ BatchJudged         Haiku: does this chunk support this sentence?
    list[BatchJudged] ─finish─▶ CitationReport          deterministic + judged issues

A child workflow is just a Workflow another step awaits. It has its own Context and state, can be
tested alone, and shows up nested in the parent's drawing. ReviewWorkflow passes it the parent's
already-loaded index and LLM through a pre-seeded ResourceManager, so nothing is loaded twice.
"""

from __future__ import annotations

import re
from typing import Annotated, Literal

from llama_index.core.llms import LLM
from llama_index.core.prompts import PromptTemplate
from pydantic import BaseModel, Field
from workflows import Context, Workflow, step
from workflows.events import Event, StartEvent, StopEvent
from workflows.resource import Resource

from litreview.bib import MARKER_RE
from litreview.models import CitationIssue
from litreview.quotes import quote_in_chunk
from litreview.resources import get_llm, get_storage
from litreview.retrieval.pipeline import Storage
from litreview.retry import LLM_RETRY, fix_note

BATCH_SIZE = 10
CHUNK_CHARS = 1200  # of each cited chunk shown to the judge
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z(])")
FACTUAL_RE = re.compile(r"\d")  # a number with no marker is a factual claim with no source

JUDGE = """[CHECK]
For each numbered item, decide whether the SOURCE text supports the SENTENCE.
- supported: the source states it, or it follows directly.
- partial: the source supports part of it; the rest is a reasonable paraphrase or hedge.
- unsupported: the source does not say this, says something different, or the sentence overstates it.

{items}"""


class SectionText(BaseModel):
    section_idx: int
    heading: str
    markdown: str  # with claim markers like [2.3]


class ClaimRef(BaseModel):
    node_id: str
    quote: str


class JudgeItem(BaseModel):
    section_idx: int
    sentence: str
    sources: list[str]


class Verdict(BaseModel):
    item: int = Field(description="The item number.")
    verdict: Literal["supported", "partial", "unsupported"]
    reason: str = Field(description="One short sentence.")


class Verdicts(BaseModel):
    verdicts: list[Verdict]


class CheckState(BaseModel):
    deterministic: list[CitationIssue] = []
    n_sentences: int = 0
    n_judged: int = 0


class CheckRequest(StartEvent):
    sections: list[SectionText]
    claims: dict[str, ClaimRef]  # every claim the writer could cite: id -> chunk + quote


class JudgeBatch(Event):
    entries: list[JudgeItem]  # not "items": Event is dict-like and already has .items()


class BatchJudged(Event):
    issues: list[CitationIssue]


class CitationReport(StopEvent):
    issues: list[CitationIssue]
    n_sentences: int
    n_judged: int


def split_sentences(markdown: str) -> list[str]:
    return [s.strip() for p in markdown.split("\n") for s in SENTENCE_RE.split(p) if s.strip()]


def cited_ids(sentence: str) -> list[str]:
    return [i for m in MARKER_RE.finditer(sentence) for i in re.split(r"\s*[,;]\s*", m.group(1))]


class CitationCheckWorkflow(Workflow):
    @step
    async def split_and_check(
        self,
        ctx: Context[CheckState],
        ev: CheckRequest,
        storage: Annotated[Storage, Resource(get_storage)],
    ) -> list[JudgeBatch] | CitationReport:
        docstore = storage.index.docstore.docs
        issues: list[CitationIssue] = []
        to_judge: list[JudgeItem] = []
        n_sentences = 0
        for section in ev.sections:
            for sentence in split_sentences(section.markdown):
                n_sentences += 1
                ids = cited_ids(sentence)
                plain = MARKER_RE.sub("", sentence).strip()
                if not ids:
                    if FACTUAL_RE.search(plain):
                        issues.append(
                            CitationIssue(
                                section_idx=section.section_idx,
                                claim=plain,
                                problem="no_citation",
                                suggested_fix="cite the claim this number comes from, or remove the number",
                            )
                        )
                    continue
                sources, ok = [], True
                for claim_id in ids:
                    ref = ev.claims.get(claim_id)
                    node = docstore.get(ref.node_id) if ref else None
                    if ref is None or node is None:  # cheap, certain checks first
                        issues.append(
                            CitationIssue(
                                section_idx=section.section_idx, claim=plain, problem="unknown_node"
                            )
                        )
                        ok = False
                        break
                    text = node.get_content()
                    if not quote_in_chunk(ref.quote, text, ref.node_id):
                        issues.append(
                            CitationIssue(
                                section_idx=section.section_idx,
                                claim=plain,
                                problem="citation_not_supporting",
                                suggested_fix=f"the quote for [{claim_id}] is not in the cited passage",
                            )
                        )
                        ok = False
                        break
                    sources.append(text[:CHUNK_CHARS])
                if ok:  # only sentences that pass the deterministic checks cost an LLM call
                    to_judge.append(
                        JudgeItem(section_idx=section.section_idx, sentence=plain, sources=sources)
                    )
        async with ctx.store.edit_state() as s:
            s.deterministic, s.n_sentences, s.n_judged = issues, n_sentences, len(to_judge)
        if not to_judge:
            return CitationReport(issues=issues, n_sentences=n_sentences, n_judged=0)
        return [JudgeBatch(entries=to_judge[i : i + BATCH_SIZE]) for i in range(0, len(to_judge), BATCH_SIZE)]

    @step(num_workers=2, retry_policy=LLM_RETRY)
    async def judge(
        self, ctx: Context[CheckState], ev: JudgeBatch, llm: Annotated[LLM, Resource(get_llm)]
    ) -> BatchJudged:
        items = "\n\n".join(
            f"Item {i}\nSENTENCE: {it.sentence}\nSOURCE: " + "\n---\n".join(it.sources)
            for i, it in enumerate(ev.entries, start=1)
        )
        result = await llm.astructured_predict(Verdicts, PromptTemplate(JUDGE + fix_note(ctx)), items=items)
        issues = []
        for v in result.verdicts:
            if v.verdict == "unsupported" and 1 <= v.item <= len(ev.entries):
                it = ev.entries[v.item - 1]
                issues.append(
                    CitationIssue(
                        section_idx=it.section_idx,
                        claim=it.sentence,
                        problem="citation_not_supporting",
                        suggested_fix=v.reason,
                    )
                )
        return BatchJudged(issues=issues)

    @step
    async def finish(self, ctx: Context[CheckState], judged: list[BatchJudged]) -> CitationReport:
        state = await ctx.store.get_state()
        issues = state.deterministic + [i for b in judged for i in b.issues]
        return CitationReport(issues=issues, n_sentences=state.n_sentences, n_judged=state.n_judged)
