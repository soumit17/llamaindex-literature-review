import re

import pytest
from llama_index.utils.workflow import draw_all_possible_flows_mermaid

from litreview.config import PROJECT_ROOT
from litreview.workflows.hello import HelloWorkflow
from litreview.workflows.ingestion import IngestionWorkflow
from litreview.workflows.review import ReviewWorkflow


@pytest.mark.parametrize(
    ("name", "workflow"),
    [("hello", HelloWorkflow), ("ingest", IngestionWorkflow), ("review", ReviewWorkflow)],
)
def test_diagram_matches_committed_docs(tmp_path, name, workflow):
    # The graph is derived from step type annotations; if a step's in/out types change,
    # this fails until `litreview draw` is re-run and the new diagram committed.
    # Compared as a set of lines: the drawer emits subclass-routing edges in set order.
    mermaid = draw_all_possible_flows_mermaid(workflow, filename=str(tmp_path / "x.mermaid"))
    committed = re.search(
        r"```mermaid\n(.*?)\n```", (PROJECT_ROOT / "docs" / f"{name}_flow.md").read_text(), re.S
    )

    assert committed is not None
    assert sorted(mermaid.splitlines()) == sorted(committed.group(1).splitlines())
