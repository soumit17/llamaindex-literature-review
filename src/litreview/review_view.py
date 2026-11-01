"""Live terminal view for `litreview review` (spec §14): stage, sub-questions, sections, log, cost.

It only *reads* the run's stream: every update below is a reaction to one streamed event.
"""

from __future__ import annotations

import json
import time
from collections import deque
from pathlib import Path

from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from workflows.events import Event

from litreview.events import (
    NeedsClarification,
    OutlineApprovalRequired,
    Progress,
    ResearchProgress,
    SectionToken,
    WriteProgress,
)
from litreview.prompts import outline_as_text

STATUS_STYLE = {
    "queued": "dim",
    "researching": "cyan",
    "writing": "cyan",
    "retry": "yellow",
    "done": "green",
    "failed": "red",
}


def ledger_spent(path: Path) -> float:
    if not path.exists():
        return 0.0
    return sum(json.loads(line)["cost_usd"] for line in path.read_text().splitlines() if line)


class ReviewView:
    def __init__(self, ledger: Path) -> None:
        self.ledger = ledger
        self.cost_at_start = ledger_spent(ledger)
        self.started = time.monotonic()
        self.stage = "scope"
        self.subs: dict[int, tuple[str, str]] = {}  # idx -> (status, text)
        self.sections: dict[int, tuple[str, str]] = {}  # idx -> (status, heading)
        self.text: dict[int, str] = {}  # idx -> streamed markdown so far
        self.active: int | None = None
        self.log: deque[str] = deque(maxlen=6)
        self._cost, self._cost_read = 0.0, 0.0

    def update(self, ev: Event) -> None:
        if isinstance(ev, ResearchProgress):
            self.stage = "research"
            self.subs[ev.idx] = (ev.status, self.subs.get(ev.idx, ("", ev.message))[1])
            if ev.status == "researching":
                self.subs[ev.idx] = (ev.status, ev.message)
        elif isinstance(ev, WriteProgress):
            self.stage = "write"
            self.sections[ev.section_idx] = (ev.status, ev.message)
        elif isinstance(ev, SectionToken):
            if ev.restart:
                self.text[ev.section_idx] = ""
            self.text[ev.section_idx] = self.text.get(ev.section_idx, "") + ev.delta
            self.active = ev.section_idx
        elif isinstance(ev, Progress):
            self.stage = ev.stage
        if isinstance(ev, Progress) and not isinstance(ev, ResearchProgress | WriteProgress):
            self.log.append(f"[{ev.stage}] {ev.message}")
        elif isinstance(ev, ResearchProgress | WriteProgress) and ev.status in ("retry", "failed"):
            self.log.append(f"[{ev.stage}] {ev.status}: {ev.message}")
        elif isinstance(ev, NeedsClarification):
            self.log.append(f"[scope] too vague ({ev.reason})")
        elif isinstance(ev, OutlineApprovalRequired):
            self.stage = "outline"
            self.log.append(f"[outline] attempt {ev.attempt}:\n" + outline_as_text(ev.outline))

    def cost(self) -> float:
        if time.monotonic() - self._cost_read > 1:  # the ledger is a file; re-read at most once a second
            self._cost = ledger_spent(self.ledger) - self.cost_at_start
            self._cost_read = time.monotonic()
        return self._cost

    def __rich__(self) -> Group:
        header = Text.assemble(
            ("stage ", "dim"),
            (self.stage, "bold"),
            (f"   {time.monotonic() - self.started:.0f}s   ", "dim"),
            (f"${self.cost():.4f}", "yellow"),
        )
        subs = Table(title="sub-questions", expand=True, show_edge=False)
        subs.add_column("#", width=3)
        subs.add_column("status", width=12)
        subs.add_column("question")
        for idx, (status, text) in sorted(self.subs.items()):
            subs.add_row(str(idx), Text(status, STATUS_STYLE.get(status, "")), text)
        parts: list = [header, subs]
        if self.sections:
            secs = Table(title="sections", expand=True, show_edge=False)
            secs.add_column("#", width=3)
            secs.add_column("status", width=12)
            secs.add_column("heading")
            secs.add_column("words", width=6, justify="right")
            for idx, (status, heading) in sorted(self.sections.items()):
                words = str(len(self.text.get(idx, "").split()))
                secs.add_row(str(idx + 1), Text(status, STATUS_STYLE.get(status, "")), heading, words)
            parts.append(secs)
        if self.active is not None:
            tail = self.text.get(self.active, "")[-400:]
            parts.append(Panel(tail, title=f"writing section {self.active + 1}", height=8))
        parts.append(Panel("\n".join(self.log) or "-", title="log"))
        return Group(*parts)
