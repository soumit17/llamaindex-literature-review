"""Writing a finished review to disk: review.md, refs.bib, citations.json and friends.

Shared by the explicit workflow (ReviewWorkflow.finalize) and the agentic one (the Reviewer's
finalize_review tool), so the M6 comparison measures orchestration, not two different renderers.
Deterministic: no LLM. Claim markers like [2.3] become numbered citations [n] (see bib.py).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Container
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from litreview.bib import Numbering, bibtex, reference_line
from litreview.config import get_settings
from litreview.corpus import PaperMeta
from litreview.events import ReviewReady
from litreview.models import CitationIssue, FindingRecord


@dataclass
class DraftSection:
    heading: str
    markdown: str  # with claim markers
    unknown_markers: int = 0


def slugify(question: str) -> str:
    words = re.findall(r"[a-z0-9]+", question.lower())[:8]
    digest = hashlib.sha1(question.encode()).hexdigest()[:6]
    return "-".join(words + [digest])


def out_dir(question: str) -> Path:
    return get_settings().p2_out_dir / slugify(question)


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    tmp.replace(path)


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def render_review(
    folder: Path,
    question: str,
    title: str,
    sections: list[DraftSection],
    findings: list[FindingRecord],
    papers: dict[str, PaperMeta],
    known_nodes: Container[str],
    log: list[str],
    remaining_issues: list[CitationIssue],
    citation_rounds: int,
    cost_usd: float,
) -> ReviewReady:
    findings = sorted(findings, key=lambda r: r.idx)
    numbering = Numbering({c.claim_id: c for r in findings for c in r.claims})
    body = [f"## {s.heading}\n\n{numbering.renumber(s.markdown)}" for s in sections]

    refs = sorted(numbering.refs.values(), key=lambda r: r.number)
    unknown_nodes = [n for r in refs for n in r.node_ids if n not in known_nodes]
    if unknown_nodes:  # can't happen: node ids come from retrieval. Fail loudly if it ever does.
        raise RuntimeError(f"citations point at chunks not in the index: {unknown_nodes[:3]}")
    failed = [r.sub_question for r in findings if not r.ok]
    gaps = [f"- {r.sub_question}: {r.gap}" for r in findings if r.ok and r.gap]

    n_papers = len({r.arxiv_id for r in refs})
    blocks = [  # one Markdown block each; joined with blank lines
        f"# {title}",
        f"> **Question:** {question}  \n> Generated {datetime.now(UTC):%Y-%m-%d} from "
        f"{plural(n_papers, 'paper')}, {plural(len(refs), 'cited passage')}.",
        *body,
    ]
    if failed or gaps:
        notes = [f"- Not covered (research failed): {q}" for q in failed] + gaps
        blocks += ["## Coverage notes", "\n".join(notes)]
    blocks += ["## References", "\n".join(reference_line(r, papers[r.arxiv_id]) + "  " for r in refs)]

    md_path, bib_path = folder / "review.md", folder / "refs.bib"
    atomic_write(md_path, "\n\n".join(blocks) + "\n")
    atomic_write(bib_path, bibtex([papers[a] for a in dict.fromkeys(r.arxiv_id for r in refs)]))
    atomic_write(folder / "citations.json", json.dumps(citations_json(refs, papers), indent=2) + "\n")
    atomic_write(folder / "log.txt", "\n".join(log) + "\n")
    issues = [i.model_dump() for i in remaining_issues]
    atomic_write(folder / "check_issues.json", json.dumps(issues, indent=2) + "\n")
    # The draft as written (claim markers, not numbers) and the findings it may cite: what
    # scripts/compare_workflows.py re-checks the same way for both workflows.
    draft = {"question": question, "title": title, "sections": [asdict(s) for s in sections]}
    atomic_write(folder / "draft.json", json.dumps(draft, indent=2) + "\n")
    atomic_write(folder / "findings.json", json.dumps([f.model_dump() for f in findings], indent=2) + "\n")

    return ReviewReady(
        markdown_path=str(md_path),
        bib_path=str(bib_path),
        n_citations=len(refs),
        unsupported_claims=len(remaining_issues),
        citation_rounds=citation_rounds,
        unknown_markers=numbering.unknown + sum(s.unknown_markers for s in sections),
        failed_subquestions=failed,
        cost_usd=round(cost_usd, 6),
    )


def citations_json(refs, papers: dict[str, PaperMeta]) -> list[dict]:
    return [
        {
            "n": r.number,
            "arxiv_id": r.arxiv_id,
            "page": r.page,
            "title": papers[r.arxiv_id].title,
            "claims": [
                {
                    "claim_id": c.claim_id,
                    "statement": c.statement,
                    "node_id": c.citation.node_id,
                    "quote": c.citation.quote,
                    "quote_verified": c.citation.quote_verified,
                }
                for c in r.claims
            ],
        }
        for r in refs
    ]
