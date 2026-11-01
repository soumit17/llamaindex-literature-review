"""M3: drafting candidate questions (fake LLM) and the eval's paper-level metrics."""

import json

from llama_index.core.schema import NodeWithScore, TextNode

from evals.retrieval import evaluate, papers_in_rank_order
from litreview.corpus import PaperMeta
from litreview.qa import LabeledQuestion, batches, draft_batch
from tests.fakes import ScriptedLLM


def meta(i: str) -> PaperMeta:
    return PaperMeta(
        arxiv_id=i,
        version=1,
        title=f"T{i}",
        authors=["A"],
        year=2025,
        published="2025-01-01",
        abstract=f"abstract {i}",
        categories=["cs.MA"],
        primary_category="cs.MA",
        abs_url="u",
    )


async def test_draft_batch_parses_structured_output_and_drops_invented_ids():
    reply = {
        "questions": [
            {"question": "How are roles assigned?", "relevant_arxiv_ids": ["p1"], "kind": "specific"},
            {"question": "Compare topologies", "relevant_arxiv_ids": ["p1", "p2"], "kind": "cross"},
            {"question": "Made up", "relevant_arxiv_ids": ["9999.99999"], "kind": "specific"},
        ]
    }
    llm = ScriptedLLM(script={"[QA]": json.dumps(reply)})
    drafted = await draft_batch(llm, [meta("p1"), meta("p2")])

    assert [q.question for q in drafted] == ["How are roles assigned?", "Compare topologies"]
    assert "Do NOT name the paper" in llm.calls[0]


def test_batches_of_five():
    assert [len(b) for b in batches([meta(str(i)) for i in range(12)])] == [5, 5, 2]


def nodes(*paper_ids: str) -> list[NodeWithScore]:
    return [NodeWithScore(node=TextNode(text="x", metadata={"arxiv_id": p})) for p in paper_ids]


def test_papers_are_deduplicated_in_chunk_order():
    assert papers_in_rank_order(nodes("b", "a", "b", "c")) == ["b", "a", "c"]


class FakeEngine:
    def __init__(self, answers: dict[str, list[str]]):
        self.answers = answers

    def retrieve(self, bundle):
        return nodes(*self.answers[bundle.query_str])


def test_hit_rate_and_mrr_at_paper_level():
    questions = [
        LabeledQuestion(id="1", question="q1", relevant_arxiv_ids=["a"], kind="specific"),
        LabeledQuestion(id="2", question="q2", relevant_arxiv_ids=["c"], kind="specific"),
        LabeledQuestion(id="3", question="q3", relevant_arxiv_ids=["z"], kind="specific"),
    ]
    engine = FakeEngine({"q1": ["a", "a", "b"], "q2": ["b", "b", "c"], "q3": ["a", "b"]})
    hit, mrr, papers = evaluate(engine, questions)
    assert hit == 2 / 3
    assert papers == (2 + 2 + 2) / 3
    assert mrr == (1 + 1 / 2 + 0) / 3  # q2: "c" is the 2nd distinct paper even though it's the 3rd chunk
