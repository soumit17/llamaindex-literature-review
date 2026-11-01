"""Reading runs/traces/spans.jsonl back: one trace as a tree, and how many steps overlapped."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Span:
    name: str
    trace_id: str
    span_id: str
    parent_id: str | None
    start_ns: int
    end_ns: int
    status: str
    attributes: dict
    events: list[dict]
    children: list[Span] = field(default_factory=list)

    @property
    def ms(self) -> float:
        return (self.end_ns - self.start_ns) / 1e6


def load(path: Path) -> list[Span]:
    if not path.exists():
        return []
    return [Span(**json.loads(line)) for line in path.read_text().splitlines() if line.strip()]


def latest_trace(spans: list[Span], root_contains: str = ".run") -> list[Span]:
    roots = [s for s in spans if s.parent_id is None and root_contains in s.name]
    if not roots:
        return []
    trace_id = max(roots, key=lambda s: s.start_ns).trace_id
    return [s for s in spans if s.trace_id == trace_id]


def tree(spans: list[Span]) -> list[Span]:
    by_id = {s.span_id: s for s in spans}
    roots = []
    for s in sorted(spans, key=lambda s: s.start_ns):
        parent = by_id.get(s.parent_id or "")
        (parent.children if parent else roots).append(s)
    return roots


def peak_overlap(spans: list[Span], name_suffix: str) -> int:
    """Most spans named *name_suffix running at the same moment (e.g. '.research' -> parallel workers)."""
    edges = []
    for s in spans:
        if s.name.endswith(name_suffix):
            edges += [(s.start_ns, 1), (s.end_ns, -1)]
    running = peak = 0
    for _, delta in sorted(edges, key=lambda e: (e[0], e[1])):  # ends before starts at equal times
        running += delta
        peak = max(peak, running)
    return peak
