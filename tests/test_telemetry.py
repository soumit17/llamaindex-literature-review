"""M8: a traced review (in a subprocess) shows run -> step spans, parallel research, and the custom
quote_in_chunk span with its CitationChecked event."""

import subprocess
import sys

from litreview.config import PROJECT_ROOT, get_settings
from litreview.traces import latest_trace, load, peak_overlap, tree


def test_traced_review_shows_steps_parallel_research_and_custom_spans(ingested):
    env_ok = subprocess.run(
        [sys.executable, "-m", "tests.telemetry_child"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert env_ok.returncode == 0, env_ok.stderr[-3000:]

    spans = load(get_settings().p2_runs_dir / "traces" / "spans.jsonl")
    trace = latest_trace(spans, root_contains="ReviewWorkflow.run")
    names = [s.name for s in trace]
    assert names.count("ReviewWorkflow.research") == 5
    assert peak_overlap(trace, ".research") >= 2  # research steps really overlapped in time
    assert {"ReviewWorkflow.plan", "ReviewWorkflow.finalize", "CitationCheckWorkflow.run"} <= set(names)

    quote_spans = [s for s in trace if "quote_in_chunk" in s.name]
    assert quote_spans and any(e["name"] == "CitationChecked" for s in quote_spans for e in s.events)
    root = tree(trace)[0]
    assert root.name == "ReviewWorkflow.run" and any(
        c.name == "ReviewWorkflow.research" for c in root.children
    )
