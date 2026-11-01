"""The one place a quote is checked against a chunk (research, the citation check, the agents).

Also the custom instrumentation example (spec §15): `@dispatcher.span` gives every call its own span
under whichever step called it, and `dispatcher.event` records a `CitationChecked` event on it.
"""

from __future__ import annotations

from llama_index_instrumentation import get_dispatcher
from rapidfuzz import fuzz

from litreview.telemetry import CitationChecked

QUOTE_MATCH_THRESHOLD = 85  # rapidfuzz partial_ratio, 0-100: the quote appears (almost) verbatim

dispatcher = get_dispatcher(__name__)


@dispatcher.span
def quote_in_chunk(quote: str, chunk_text: str, node_id: str = "") -> bool:
    score = fuzz.partial_ratio(quote.lower(), chunk_text.lower())
    matched = score >= QUOTE_MATCH_THRESHOLD
    dispatcher.event(CitationChecked(node_id=node_id, score=score, matched=matched))
    return matched
