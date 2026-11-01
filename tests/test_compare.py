"""M6: the comparison script's pure parts (no runs, no LLM)."""

import importlib.util
import json
import sys

from litreview.config import PROJECT_ROOT

spec = importlib.util.spec_from_file_location(
    "compare_workflows", PROJECT_ROOT / "scripts" / "compare_workflows.py"
)
compare = importlib.util.module_from_spec(spec)
sys.modules["compare_workflows"] = compare  # @dataclass looks its module up in sys.modules
spec.loader.exec_module(compare)  # type: ignore[union-attr]


def test_code_lines_skip_blanks_comments_and_docstrings(tmp_path):
    f = tmp_path / "m.py"
    f.write_text('"""Module doc\nover two lines."""\n\n# comment\ndef f():\n    """Doc."""\n    return 1\n')
    assert compare.code_lines(f) == 2  # "def f():" and "return 1"


def test_outline_overlap():
    assert compare.overlap(["Intro", "Hubs", "Conclusion"], ["intro", "Hubs!", "Conclusion"]) == 1.0
    assert compare.overlap(["A", "B"], ["B", "C"]) == 1 / 3


def run(wf, q, repeat, outline, issues=1):
    return compare.RunMetrics(
        workflow=wf,
        question=q,
        repeat=repeat,
        ok=True,
        seconds=10,
        llm_calls=12,
        input_tokens=9000,
        output_tokens=1000,
        cost_usd=0.01,
        papers=5,
        passages=8,
        cited_sentences=10,
        sentences_with_issues=issues,
        outline=outline,
    )


def test_report_is_written_with_both_workflows(tmp_path, monkeypatch):
    monkeypatch.setattr(compare, "DOC", tmp_path / "doc.md")
    monkeypatch.setattr(compare, "REPORT", tmp_path / "compare.json")
    runs = [
        run("explicit", 1, 1, ["Intro", "Hubs"]),
        run("explicit", 1, 2, ["Intro", "Hubs"]),
        run("agentic", 1, 1, ["Intro", "Rings"], issues=3),
        run("agentic", 1, 2, ["Intro", "Trees"], issues=3),
    ]
    compare.write_doc(runs, n_questions=1, repeats=2)

    doc = (tmp_path / "doc.md").read_text()
    assert "| explicit | 2/2 | $0.0100 |" in doc and "| 90% |" in doc and "| 100% |" in doc  # overlap 1.0
    assert "| agentic | 2/2 |" in doc and "| 70% |" in doc and "| 33% |" in doc
    assert len(json.loads((tmp_path / "compare.json").read_text())) == 4
