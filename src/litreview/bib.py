"""Citations, references and BibTeX (spec §7.4). Deterministic: no LLM touches references.

The writer cites *claims* it was given, as markers like [2.3] (finding 2, claim 3). Here those
markers become numbered citations [n], one number per (paper, page), in order of first appearance.
Every number therefore traces back to real chunks: `citations.json` lists, for each [n], the
claims, their node ids and supporting quotes. Markers that match no claim are removed and counted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from litreview.corpus import PaperMeta
from litreview.models import FindingClaim

MARKER_RE = re.compile(r"\[\s*(\d+\.\d+(?:\s*[,;]\s*\d+\.\d+)*)\s*\]")


@dataclass
class Reference:
    number: int
    arxiv_id: str
    page: int | None
    claims: list[FindingClaim] = field(default_factory=list)

    @property
    def node_ids(self) -> list[str]:
        return sorted({c.citation.node_id for c in self.claims})


@dataclass
class Numbering:
    """Assigns [n] to (paper, page) keys as markers are met, across all sections."""

    claims: dict[str, FindingClaim]
    refs: dict[tuple[str, int | None], Reference] = field(default_factory=dict)
    unknown: int = 0

    def renumber(self, markdown: str) -> str:
        def replace(match: re.Match[str]) -> str:
            numbers: list[int] = []
            for claim_id in re.split(r"\s*[,;]\s*", match.group(1)):
                claim = self.claims.get(claim_id)
                if claim is None:
                    self.unknown += 1
                    continue
                key = (claim.citation.arxiv_id, claim.citation.page)
                ref = self.refs.get(key)
                if ref is None:
                    ref = self.refs[key] = Reference(len(self.refs) + 1, *key)
                if claim not in ref.claims:
                    ref.claims.append(claim)
                numbers.append(ref.number)
            return f"[{', '.join(str(n) for n in sorted(set(numbers)))}]" if numbers else ""

        return re.sub(r" +([.,;:])", r"\1", MARKER_RE.sub(replace, markdown))


def strip_unknown_markers(markdown: str, known: set[str]) -> tuple[str, int]:
    """Drop claim ids the writer invented; return the cleaned text and how many were dropped."""
    dropped = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal dropped
        ids = re.split(r"\s*[,;]\s*", match.group(1))
        keep = [i for i in ids if i in known]
        dropped += len(ids) - len(keep)
        return f"[{', '.join(keep)}]" if keep else ""

    return MARKER_RE.sub(replace, markdown), dropped


def used_claim_ids(markdown: str) -> set[str]:
    return {i for m in MARKER_RE.finditer(markdown) for i in re.split(r"\s*[,;]\s*", m.group(1))}


def author_list(authors: list[str]) -> str:
    surnames = [a.split()[-1] for a in authors]
    if len(surnames) <= 2:
        return " and ".join(surnames)
    return f"{surnames[0]} et al."


def reference_line(ref: Reference, paper: PaperMeta) -> str:
    page = f", p. {ref.page}" if ref.page else ""
    who = author_list(paper.authors)
    return f"[{ref.number}] {who} ({paper.year}). {paper.title}. arXiv:{paper.arxiv_id}{page}"


def bibtex_key(paper: PaperMeta, taken: set[str]) -> str:
    surname = re.sub(r"[^a-z]", "", paper.authors[0].split()[-1].lower()) if paper.authors else "anon"
    word = next((w for w in re.findall(r"[a-z]+", paper.title.lower()) if len(w) > 3), "paper")
    key = base = f"{surname}{paper.year}{word}"
    suffix = ord("a")
    while key in taken:
        key = f"{base}{chr(suffix)}"
        suffix += 1
    taken.add(key)
    return key


def _escape(text: str) -> str:
    return re.sub(r"([&%$#_{}])", r"\\\1", text)


def bibtex(papers: list[PaperMeta]) -> str:
    taken: set[str] = set()
    entries = []
    for p in papers:
        entries.append(
            f"@misc{{{bibtex_key(p, taken)},\n"
            f"  title = {{{{{_escape(p.title)}}}}},\n"
            f"  author = {{{' and '.join(_escape(a) for a in p.authors)}}},\n"
            f"  year = {{{p.year}}},\n"
            f"  eprint = {{{p.arxiv_id}}},\n"
            f"  archivePrefix = {{arXiv}},\n"
            f"  primaryClass = {{{p.primary_category}}},\n"
            f"  url = {{{p.abs_url}}}\n"
            "}"
        )
    return "\n\n".join(entries) + "\n"
