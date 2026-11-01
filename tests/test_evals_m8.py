"""M8: the eval scripts' logic, on a scripted review ($0)."""

import json
from pathlib import Path

from workflows.resource import Resource

from evals.citations import collect_items, judge, metrics, second_opinion
from evals.compare import current_metrics, regressions
from evals.quality import agreement, mean_pct
from litreview.resources import get_embed_model, get_storage, shared_resources
from tests.fakes import CountingEmbedding, ScriptedLLM
from tests.review_env import run_review, scripted


async def test_citation_eval_on_a_scripted_review(ingested):
    result, _, _ = await run_review(scripted())
    manager = await shared_resources({get_embed_model: CountingEmbedding.make()})
    storage = await manager.get(Resource(get_storage))

    items = collect_items(Path(result.markdown_path).parent, storage)
    assert items and all(it.claim_ids and not it.unknown_node and it.quotes_found for it in items)
    assert all("[" not in it.sentence for it in items)  # markers stripped before judging

    verdicts = {"verdicts": [{"item": 1, "verdict": "partial", "reason": "scope"}]}
    llm = ScriptedLLM(script={"[EVAL-CITE]": json.dumps(verdicts)}, default="YES")
    await judge(items, llm)
    sample = await second_opinion(items, llm)  # FaithfulnessEvaluator reads "YES" as a pass
    m = metrics(items, sample)

    assert items[0].verdict == "partial"
    assert m["unknown_node_pct"] == 0 and m["quotes_found_pct"] == 100
    assert m["faithfulness_sample"] == len(sample) > 0
    assert 0 <= m["supported_strict_pct"] <= m["supported_lenient_pct"] <= 100


def test_gate_fails_only_beyond_three_points():
    baseline = {"citations.supported_lenient": 96.0, "retrieval.hit_rate_at_5": 90.0}
    assert regressions({"citations.supported_lenient": 93.5, "retrieval.hit_rate_at_5": 92.0}, baseline) == []
    assert regressions({"citations.supported_lenient": 92.9, "retrieval.hit_rate_at_5": 90.0}, baseline) == [
        "citations.supported_lenient: 96.0 -> 92.9 (-3.1)"
    ]


def test_current_metrics_reads_the_reports(tmp_path):
    (tmp_path / "retrieval.json").write_text(
        json.dumps([{"hit_rate": 0.9, "mrr": 0.86}, {"hit_rate": 0.8, "mrr": 0.9}])
    )
    (tmp_path / "citations.json").write_text(
        json.dumps(
            {
                "metrics": {
                    "supported_lenient_pct": 97.0,
                    "supported_strict_pct": 88.0,
                    "unknown_node_pct": 0.0,
                }
            }
        )
    )
    m = current_metrics(tmp_path)
    assert m == {
        "retrieval.hit_rate_at_5": 90.0,
        "retrieval.mrr": 86.0,
        "citations.supported_lenient": 97.0,
        "citations.supported_strict": 88.0,
        "citations.neg_unknown_nodes": 0.0,
    }


def test_quality_scores():
    s = {c: {"score": 5, "why": ""} for c in ("coverage", "structure", "no_fabrication", "hedging")}
    low = {**s, "hedging": {"score": 1, "why": ""}}
    assert mean_pct({"a": s}) == 100.0 and mean_pct({"a": low}) == 75.0
    human = {"a": {"coverage": 4, "structure": 5, "no_fabrication": None, "hedging": 3}}
    assert agreement(human, {"a": low}) == {"coverage": 1.0, "structure": 0.0, "hedging": 2.0}
