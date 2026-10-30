"""PDF -> cleaned, section-tagged segments (spec §4.2).

Pages come from LlamaIndex's `PyMuPDFReader` (one Document per page). Then, per paper:
1. drop boilerplate: lines repeated at the top/bottom of many pages (running headers/footers),
   bare page numbers, and the arXiv side stamp;
2. walk the lines, tracking the current section from headings ("1 Introduction", "ABSTRACT",
   "5 Conclusion and Future Work"), and stop at "References" / "Bibliography";
3. cut into segments, one per (page, section heading), de-hyphenate and unwrap lines.

Each segment keeps `page`, `section` (a canonical label) and `heading` (the raw heading), so a
citation can say "p. 4, §3 Method". The heuristics are deliberately simple; parse quality is
measured indirectly by retrieval hit-rate in M3.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

from llama_index.readers.file import PyMuPDFReader

REFERENCES_RE = re.compile(r"^(?:(?:\d{1,2}|[IVX]{1,4})\.?\s*)?(references|bibliography)$", re.I)
ARXIV_STAMP_RE = re.compile(r"^arXiv:\d{4}\.\d{4,5}(v\d+)?\b")
PAGE_NUMBER_RE = re.compile(r"^(?:page\s*)?\d{1,3}(?:\s*(?:/|of)\s*\d{1,3})?$", re.I)
NUMBERED_HEADING_RE = re.compile(
    r"^(?P<num>\d{1,2}(?:\.\d{1,2})?|[IVX]{1,4})\.?\s+(?P<title>[A-Z][A-Za-z0-9 ,:&/()'’?\-–]{2,80})$"
)
BARE_NUMBER_RE = re.compile(r"^(?:\d{1,2}(?:\.\d{1,2})?|[IVX]{1,4})\.?$")
SECTION_LABELS: list[tuple[str, re.Pattern[str]]] = [
    (label, re.compile(pattern, re.I))
    for label, pattern in [
        ("abstract", r"^abstract\b"),
        ("introduction", r"\bintroduction\b"),
        ("related_work", r"related work|background|preliminar|literature"),
        ("conclusion", r"conclu|concluding|closing remarks"),
        ("discussion", r"discussion|limitation|future work|broader impact|ethic"),
        ("experiments", r"experiment|evaluation|setup|benchmark|case stud"),
        ("results", r"\bresults?\b|analysis|findings"),
        ("method", r"method|approach|framework|architecture|design|system|model|formulation"),
        ("appendix", r"appendix|supplementa"),
    ]
]
ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10}
MIN_SEGMENT_CHARS = 40


@dataclass
class Segment:
    text: str
    page: int  # 1-based
    section: str  # canonical label: front, abstract, introduction, ..., body
    heading: str  # raw heading text ("" before the first heading)


@dataclass
class ParsedPaper:
    segments: list[Segment]
    n_pages: int
    references_cut_at_page: int | None

    @property
    def n_chars(self) -> int:
        return sum(len(s.text) for s in self.segments)


def label_for(title: str) -> str:
    return next((label for label, rx in SECTION_LABELS if rx.search(title)), "body")


def _norm(line: str) -> str:
    return re.sub(r"\d+", "#", line.strip().lower())


def boilerplate_lines(pages: list[list[str]]) -> set[str]:
    """Normalized lines that appear near the top/bottom of many pages: running headers/footers."""
    if len(pages) < 3:
        return set()
    counts: Counter[str] = Counter()
    for lines in pages:
        edge = [ln for ln in lines if ln.strip()]
        counts.update({_norm(ln) for ln in edge[:3] + edge[-3:]})
    threshold = max(3, int(0.3 * len(pages)))
    return {line for line, n in counts.items() if n >= threshold and line}


def merge_split_headings(lines: list[str]) -> list[str]:
    """PyMuPDF often emits a heading's number and title as two lines ("3" / "METHOD"); rejoin them."""
    out: list[str] = []
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
        if BARE_NUMBER_RE.match(s) and nxt[:1].isupper():
            out.append(f"{s.rstrip('.')} {nxt}")
            i += 2
        else:
            out.append(lines[i])
            i += 1
    return out


CAPTION_RE = re.compile(r"^(table|figure|fig\.|algorithm|listing|eq\.|equation|prompt)\b", re.I)


@dataclass
class Headings:
    """Decides which lines are section headings. Keeps the numbering context across pages."""

    last_top: int = 0  # number of the current top-level section
    style: str | None = None  # "arabic" or "roman", fixed by the first accepted section

    def match(self, line: str) -> tuple[str, int | None] | None:
        """(heading, number) for a top-level section, (heading, None) for a subsection or an
        unnumbered heading, None for ordinary text."""
        s = line.strip()
        if not 3 <= len(s) <= 90 or s.endswith((".", ",", ";")) or len(s.split()) > 12:
            return None
        m = NUMBERED_HEADING_RE.match(s)
        if m:
            return self._numbered(s, m.group("num"), m.group("title"))
        # Unnumbered: only a short, well-known heading line ("Abstract", "CONCLUSIONS").
        words = s.split()
        if (
            label_for(s) in ("abstract", "introduction", "conclusion", "related_work", "appendix")
            and len(words) <= 5
            and (s.isupper() or words[0].istitle())
        ):
            return s, None
        return None

    def _numbered(self, s: str, raw: str, title: str) -> tuple[str, int | None] | None:
        letters = sum(c.isalpha() for c in title)
        if CAPTION_RE.match(title) or letters < 0.6 * len(title.replace(" ", "")):
            return None  # "5 Table 1: ...", "3 GPT-4 85.2 / 90.1"
        if "." in raw:  # subsection "3.2": must belong to the current section, no "5.00"
            top, sub = raw.split(".")
            ok = int(top) == self.last_top and not (len(sub) > 1 and sub.startswith("0"))
            return (s, None) if ok else None
        style = "roman" if raw in ROMAN else "arabic"
        num = ROMAN.get(raw) if style == "roman" else int(raw) if raw.isdigit() else None
        if num is None or (self.style is not None and style != self.style):
            return None  # e.g. "3 Role Agents" (a diagram label) in a paper numbered I, II, III
        known = label_for(title) != "body"
        if label_for(title) == "introduction":
            ok = num <= 2  # always section 1 (or 2): resets a count spoiled by "1 University of X"
        elif known:
            ok = self.last_top <= num <= self.last_top + 2  # may reuse a number a false positive took
        else:
            ok = self.last_top < num <= self.last_top + 2  # next section only: skips table rows
        if not ok:
            return None
        self.last_top, self.style = num, style
        return s, num


def _clean(lines: list[str]) -> str:
    text = "\n".join(lines)
    text = re.sub(r"(?<=[a-z])-\n(?=[a-z])", "", text)  # de-hyphenate "orches-\ntration"
    return re.sub(r"\s*\n\s*", " ", text).strip()  # unwrap lines


def _flush(segments: list[Segment], buf: list[str], page: int, section: str, heading: str) -> None:
    text = _clean(buf)
    if len(text) >= MIN_SEGMENT_CHARS:
        segments.append(Segment(text, page, section, heading))
    buf.clear()


def parse_pages(page_texts: list[str]) -> ParsedPaper:
    pages = [merge_split_headings(text.splitlines()) for text in page_texts]
    boiler = boilerplate_lines(pages)
    segments: list[Segment] = []
    headings = Headings()
    section, heading = "front", ""
    refs_page: int | None = None

    for page_no, lines in enumerate(pages, start=1):
        buf: list[str] = []
        for line in lines:
            s = line.strip()
            if not s or _norm(s) in boiler or PAGE_NUMBER_RE.match(s) or ARXIV_STAMP_RE.match(s):
                continue
            if REFERENCES_RE.match(s):
                refs_page = page_no
                break
            found = headings.match(s)
            if found:
                _flush(segments, buf, page_no, section, heading)  # text so far belongs to the old heading
                heading, num = found
                if num is not None:
                    section = label_for(NUMBERED_HEADING_RE.sub(r"\g<title>", heading))
                elif label_for(heading) != "body":
                    section = label_for(heading)
                continue
            buf.append(line)
        _flush(segments, buf, page_no, section, heading)
        if refs_page is not None:
            break
    return ParsedPaper(segments, len(pages), refs_page)


def parse_pdf(path: Path) -> ParsedPaper:
    docs = PyMuPDFReader().load_data(file_path=path, metadata=True)
    return parse_pages([d.text for d in docs])


def write_jsonl(path: Path, paper: ParsedPaper, metadata: dict) -> None:
    """data/parsed/<id>.jsonl: one segment per line, with the paper-level metadata merged in."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".jsonl.tmp")
    with tmp.open("w") as f:
        for seg in paper.segments:
            f.write(json.dumps({**metadata, **asdict(seg)}) + "\n")
    tmp.replace(path)


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
