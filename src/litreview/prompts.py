"""Prompts for the review workflow (spec §7.5). The [TAG] at the start of each is how tests' ScriptedLLM
picks a canned reply; the model ignores it."""

from __future__ import annotations

from llama_index.core.schema import NodeWithScore

from litreview.models import FindingRecord, Outline

SCOPE = """[SCOPE]
A user wants a short literature review, written from a corpus of ~25 ML papers on: {topic}.
Their question: "{question}"

Is the question specific enough to research as asked? A question is too vague if it has no clear
subject (e.g. "tell me about AI") or could mean several unrelated things. Questions about patterns,
trade-offs or comparisons within the corpus topic are fine. If too vague, suggest 2-3 sharper versions."""

PLAN = """[PLAN]
Research question: "{question}"
Corpus: ~25 machine-learning papers on {topic}. Audience: {audience}.

Decompose the question into {n_min}-{n_max} non-overlapping sub-questions that can be answered from
the papers. Give each a one-line rationale. Prefer comparative and mechanism questions ("how does X
decide...", "what trade-off...") over definitional ones ("what is X")."""

REPLAN_FEEDBACK = """

A previous plan led to an outline the reader rejected, with this feedback:
{feedback}
Plan differently so the review addresses it."""

RESEARCH = """[RESEARCH]
Sub-question: "{question}"

Excerpts from research papers:

{excerpts}

Answer the sub-question using ONLY these excerpts, as separate claims. Each claim is one factual
sentence supported by exactly one excerpt: give that excerpt's number and a short quote copied
word for word from it. Do not use outside knowledge. If the excerpts don't answer part of the
question, say what is missing in `gap`. At most 8 claims, about 180 words in total."""

OUTLINE = """[OUTLINE]
You are outlining a literature review for {audience}.
Question: "{question}"

Findings from research (each claim is grounded in a paper):

{findings}

Propose a title and 4-7 sections, starting with an introduction and ending with a conclusion. For
each section give 2-4 points and the ids of the findings it draws on (introduction and conclusion
may have none). Group findings by theme rather than one section per finding."""

WRITE = """[WRITE]
Write the section "{heading}" of a literature review titled "{title}", for {audience}.
It should cover: {points}

Use ONLY these claims, each a statement from a paper with its marker:

{claims}

Rules:
- Every factual sentence ends with the marker(s) of the claims it relies on, e.g. "... [2.1]" or
  "... [1.3, 2.2]". Use only markers from the list above; never invent one.
- Synthesize and compare across claims rather than listing them. Hedge where the claims do.
- About {words} words of Markdown prose. No heading line (it is added for you), no reference list."""


REVISE = """[REVISE]
Revise the section "{heading}" of a literature review titled "{title}", for {audience}.
A citation check flagged these sentences:

{notes}

Current draft:
{previous}

Claims you may cite, each with its marker:

{claims}

Fix every flagged sentence: re-cite it to a claim that really supports it, weaken it to what the
claim says, or remove it. Keep the rest of the draft as it is. Every factual sentence ends with
marker(s) from the list; never invent one. Return only the revised section text, no heading."""


def format_excerpts(nodes: list[NodeWithScore], titles: dict[str, str]) -> str:
    parts = []
    for i, n in enumerate(nodes, start=1):
        m = n.node.metadata
        source = f"{titles.get(m.get('arxiv_id', ''), m.get('arxiv_id', '?'))}, p. {m.get('page', '?')}"
        parts.append(f"[E{i}] ({source})\n{n.node.get_content()}")
    return "\n\n".join(parts)


def format_findings(findings: list[FindingRecord]) -> str:
    blocks = []
    for f in findings:
        if not f.ok or not f.claims:
            continue
        claims = "\n".join(f"  - {c.statement}" for c in f.claims)
        blocks.append(f"Finding {f.idx}: {f.sub_question}\n{claims}")
    return "\n\n".join(blocks)


def format_claims(findings: list[FindingRecord], titles: dict[str, str]) -> str:
    return "\n".join(
        f"[{c.claim_id}] {c.statement} ({titles.get(c.citation.arxiv_id, c.citation.arxiv_id)})"
        for f in findings
        for c in f.claims
    )


def outline_as_text(outline: Outline) -> str:
    lines = [outline.title]
    for i, s in enumerate(outline.sections, start=1):
        ids = f" (findings {', '.join(map(str, s.finding_ids))})" if s.finding_ids else ""
        lines.append(f"{i}. {s.heading}{ids}")
    return "\n".join(lines)
