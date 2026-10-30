import pytest
from llama_index.utils.workflow import draw_all_possible_flows_mermaid

from litreview.config import PROJECT_ROOT
from litreview.workflows.hello import HelloWorkflow
from litreview.workflows.ingestion import IngestionWorkflow


@pytest.mark.parametrize(("name", "workflow"), [("hello", HelloWorkflow), ("ingest", IngestionWorkflow)])
def test_diagram_matches_committed_docs(tmp_path, name, workflow):
    # The graph is derived from step type annotations; if a step's in/out types change,
    # this fails until `litreview draw` is re-run and the new diagram committed.
    mermaid = draw_all_possible_flows_mermaid(workflow, filename=str(tmp_path / "x.mermaid"))

    assert mermaid in (PROJECT_ROOT / "docs" / f"{name}_flow.md").read_text()
