"""M5: CitationCheckWorkflow alone (it's a workflow like any other), then the revise loop it drives."""

import json
from pathlib import Path

from workflows.resource import Resource
from workflows.testing import WorkflowTestRunner

from litreview.resources import get_embed_model, get_llm, get_storage, shared_resources
from litreview.workflows.citation_check import (
    CheckRequest,
    CitationCheckWorkflow,
    CitationReport,
    ClaimRef,
    SectionText,
    split_sentences,
)
from tests.fakes import CountingEmbedding, ScriptedLLM
from tests.review_env import run_review, scripted


async def check(storage, llm, sections, claims) -> CitationReport:
    manager = await shared_resources({get_storage: storage, get_llm: llm})
    result = await WorkflowTestRunner(CitationCheckWorkflow(timeout=30, resource_manager=manager)).run(
        CheckRequest(sections=sections, claims=claims)
    )
    return result.result


async def load_storage():
    manager = await shared_resources({get_embed_model: CountingEmbedding.make()})
    return await manager.get(Resource(get_storage))


def test_sentence_split_keeps_markers_with_their_sentence():
    assert split_sentences("Hubs route work [1.1]. Rings pass tokens [2.1].\nA third.") == [
        "Hubs route work [1.1].",
        "Rings pass tokens [2.1].",
        "A third.",
    ]


async def test_deterministic_problems_need_no_llm(ingested):
    storage = await load_storage()
    node_id, node = next(iter(storage.index.docstore.docs.items()))
    real_quote = node.get_content()[10:60]
    claims = {
        "1.1": ClaimRef(node_id=node_id, quote=real_quote),
        "1.2": ClaimRef(node_id="no-such-node", quote="x"),
        "1.3": ClaimRef(node_id=node_id, quote="a sentence that appears nowhere in this chunk at all"),
    }
    text = (
        "Accuracy rose by 12 points. "  # a number, no marker -> no_citation
        "This one is grounded [1.1]. "  # passes -> goes to the LLM judge
        "This cites a missing chunk [1.2]. "  # -> unknown_node
        "This quote is not in the chunk [1.3]. "  # -> citation_not_supporting
        "Invented id [7.7]. "  # -> unknown_node
        "A framing sentence with no number."  # no marker, nothing factual -> fine
    )
    judge = ScriptedLLM(
        script={"[CHECK]": json.dumps({"verdicts": [{"item": 1, "verdict": "supported", "reason": "ok"}]})}
    )
    report = await check(storage, judge, [SectionText(section_idx=0, heading="H", markdown=text)], claims)

    problems = sorted(i.problem for i in report.issues)
    assert problems == ["citation_not_supporting", "no_citation", "unknown_node", "unknown_node"]
    assert report.n_sentences == 6 and report.n_judged == 1
    assert len(judge.calls) == 1 and "This one is grounded" in judge.calls[0]
    assert "[1.1]" not in judge.calls[0]  # markers stripped before judging


async def test_judge_runs_in_batches_of_ten_and_flags_unsupported(ingested):
    storage = await load_storage()
    node_id, node = next(iter(storage.index.docstore.docs.items()))
    claims = {"1.1": ClaimRef(node_id=node_id, quote=node.get_content()[:40])}
    text = " ".join(f"Grounded sentence {chr(65 + i)} [1.1]." for i in range(12))
    verdicts = {"verdicts": [{"item": 2, "verdict": "unsupported", "reason": "overstates it"}]}
    judge = ScriptedLLM(script={"[CHECK]": json.dumps(verdicts)})
    report = await check(storage, judge, [SectionText(section_idx=3, heading="H", markdown=text)], claims)

    assert len(judge.calls) == 2  # 12 sentences -> batches of 10 + 2 (list fan-out, list fan-in)
    assert [(i.section_idx, i.problem, i.suggested_fix) for i in report.issues] == [
        (3, "citation_not_supporting", "overstates it")
    ] * 2  # item 2 of each batch


async def test_revise_loop_rewrites_flagged_sections_then_finishes(ingested):
    # First check flags one sentence; the revised draft passes.
    checks = iter(
        [
            {"verdicts": [{"item": 1, "verdict": "unsupported", "reason": "not in source"}]},
            {"verdicts": []},
        ]
    )

    class TwoChecks(ScriptedLLM):
        def _reply(self, prompt: str) -> str:
            if "[CHECK]" in prompt:
                self.calls.append(prompt)
                return json.dumps(next(checks))
            return super()._reply(prompt)

    llm = TwoChecks(script=scripted().script)
    result, _, handler = await run_review(llm)

    state = await handler.ctx.store.get_state()
    assert (state.citation_rounds, state.revisions) == (2, 1)
    revise_prompts = [p for p in llm.calls if "[REVISE]" in p]
    assert len(revise_prompts) == 1 and "not in source" in revise_prompts[0]  # only the flagged section
    assert result.unsupported_claims == 0 and result.citation_rounds == 2
    assert "Orchestrators assign roles [" in Path(result.markdown_path).read_text()  # the revised text


async def test_revise_loop_is_bounded(ingested):
    always_bad = json.dumps({"verdicts": [{"item": 1, "verdict": "unsupported", "reason": "nope"}]})
    llm = scripted(script={"[CHECK]": always_bad})
    result, _, handler = await run_review(llm)

    state = await handler.ctx.store.get_state()
    assert (state.citation_rounds, state.revisions) == (3, 2)  # check, revise, check, revise, check
    assert result.unsupported_claims > 0 and result.error is None  # reported, not hidden
    issues = json.loads((Path(result.markdown_path).parent / "check_issues.json").read_text())
    assert len(issues) == result.unsupported_claims
