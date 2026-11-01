"""Tracing (spec §15): every workflow run, step and LLM call becomes an OpenTelemetry span.

`llama-index-observability-otel` turns LlamaIndex's instrumentation (the dispatcher every workflow step
and LLM call reports to) into OTel spans: one span per run, one per step under it (with run id and
input event as attributes), LLM and retrieval spans under the steps that made them.

Where spans go (OTEL_EXPORTER):
    file  (default)  runs/traces/spans.jsonl, one JSON span per line; `scripts/trace_summary.py` reads it
    otlp             also to an OTLP/HTTP endpoint, e.g. Phoenix: `uvx --from arize-phoenix phoenix serve`,
                     then OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:6006/v1/traces
    console          also printed to stdout (noisy; for a quick look)

Custom instrumentation lives where it is used: `quote_in_chunk` (workflows/citation_check.py) has its
own span via `@dispatcher.span`, and emits a `CitationChecked` event.
"""

from __future__ import annotations

import json
import os
import threading
from collections.abc import Sequence
from pathlib import Path

from llama_index.core.instrumentation.events import BaseEvent
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult

from litreview.config import get_settings

_started = False


class CitationChecked(BaseEvent):
    """Custom instrumentation event: one quote checked against one chunk (recorded on the span)."""

    node_id: str
    score: float
    matched: bool

    @classmethod
    def class_name(cls) -> str:
        return "CitationChecked"


class JsonLinesSpanExporter(SpanExporter):
    """Appends each finished span as one JSON line. Readable without any tracing backend."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        lines = []
        for s in spans:
            if s.context is None:
                continue
            lines.append(
                json.dumps(
                    {
                        "name": s.name,
                        "trace_id": f"{s.context.trace_id:032x}",
                        "span_id": f"{s.context.span_id:016x}",
                        "parent_id": f"{s.parent.span_id:016x}" if s.parent else None,
                        "start_ns": s.start_time,
                        "end_ns": s.end_time,
                        "status": s.status.status_code.name,
                        "attributes": {k: v for k, v in (s.attributes or {}).items()},
                        "events": [
                            {"name": e.name, "attributes": dict(e.attributes or {})} for e in s.events
                        ],
                    },
                    default=str,
                )
            )
        with self._lock, self.path.open("a") as f:
            f.write("\n".join(lines) + "\n")
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        pass


def setup_telemetry(service: str = "litreview") -> Path | None:
    """Start exporting spans (once per process). Returns the JSON-lines file, or None if disabled."""
    global _started
    mode = os.environ.get("OTEL_EXPORTER", "file").strip().lower()
    if _started or mode in ("", "none", "off"):
        return None
    from llama_index.observability.otel import LlamaIndexOpenTelemetry

    path = get_settings().p2_runs_dir / "traces" / "spans.jsonl"
    exporter: SpanExporter = JsonLinesSpanExporter(path)
    extra = []
    if mode == "otlp":
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") or "http://localhost:6006/v1/traces"
        extra.append(SimpleSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    elif mode == "console":
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter

        extra.append(SimpleSpanProcessor(ConsoleSpanExporter()))
    LlamaIndexOpenTelemetry(
        span_exporter=exporter,
        span_processor="simple",  # write each span when it ends: nothing lost if the process is killed
        extra_span_processors=extra,
        service_name_or_resource=service,
    ).start_registering()
    _started = True
    return path
