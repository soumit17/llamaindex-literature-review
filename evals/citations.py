"""Citation faithfulness eval (spec §17.2). Costs real money (Haiku): ~$0.03 for 3 new reviews + judging.

For every cited sentence in a review's draft (claim markers, before numbering):
- deterministic: every cited claim's chunk exists in the index, and its quote is found in that chunk;
- judge (Haiku, batches of 10): does the cited text support the sentence? supported / partial / unsupported.
  A separate prompt from the pipeline's own citation check, so the eval doesn't grade its own homework
  verbatim (it is still the same model family: see "LLM-as-judge" in your journal).
- second opinion: LlamaIndex `FaithfulnessEvaluator` on a sample of 10 sentences; agreement is reported.

Metrics: % supported (strict: supported; lenient: supported + partial; target >= 95% lenient),
% unknown nodes (target 0), % quotes found.

    uv run python -m evals.citations                     # write 3 fresh reviews (Workflow 2), then evaluate
    uv run python -m evals.citations --existing          # evaluate every review already in out/
"""

from __future__ import annotations

import asyncio
import json
import random
from dataclasses import asdict, dataclass
from pathlib import Path

import typer
from llama_index.core.evaluation import FaithfulnessEvaluator
from llama_index.core.llms import LLM
from llama_index.core.prompts import PromptTemplate
from rich.console import Console
from workflows.resource import Resource, ResourceManager

from litreview.bib import MARKER_RE
from litreview.config import PROJECT_ROOT, get_settings
from litreview.events import ReviewReady, ReviewRequest
from litreview.hitl import auto_responder, drive
from litreview.quotes import quote_in_chunk
from litreview.resources import get_cost_tracker, get_llm, get_storage
from litreview.retrieval.pipeline import Storage
from litreview.workflows.citation_check import Verdicts, cited_ids, split_sentences
from litreview.workflows.review import ReviewWorkflow

QUESTIONS = [
    "What orchestration patterns do LLM-based multi-agent systems use, and how do they trade off control, "
    "cost and robustness?",
    "How do multi-agent LLM systems decide which agent acts next, and what does each approach cost?",
    "What communication topologies do LLM agent teams use, and how does topology affect task performance?",
]
REPORT = PROJECT_ROOT / "evals" / "reports" / "citations.md"
BATCH = 10
SAMPLE = 10
console = Console()

JUDGE = """[EVAL-CITE]
You are auditing citations in a literature review. For each item, read the SENTENCE and the SOURCE
passage(s) it cites, and grade strictly:
- supported: every factual part of the sentence is stated in, or directly follows from, the sources.
- partial: the core is supported, but a detail (a number, a scope, a comparison) is not.
- unsupported: the sources do not say this, say something else, or the sentence overstates them.

{items}"""


@dataclass
class Item:
    review: str
    section: str
    sentence: str
    claim_ids: list[str]
    sources: list[str]
    unknown_node: bool
    quotes_found: bool
    verdict: str = ""
    reason: str = ""
    faithfulness: bool | None = None  # FaithfulnessEvaluator's opinion (sampled items only)


def collect_items(folder: Path, storage: Storage) -> list[Item]:
    draft = json.loads((folder / "draft.json").read_text())
    claims = {
        c["claim_id"]: c for f in json.loads((folder / "findings.json").read_text()) for c in f["claims"]
    }
    docstore = storage.index.docstore.docs
    items = []
    for section in draft["sections"]:
        for sentence in split_sentences(section["markdown"]):
            ids = cited_ids(sentence)
            if not ids:
                continue
            sources, unknown, quotes = [], False, True
            for i in ids:
                claim = claims.get(i)
                node = docstore.get(claim["citation"]["node_id"]) if claim else None
                if claim is None or node is None:
                    unknown = True
                    continue
                text = node.get_content()
                sources.append(text)
                cite = claim["citation"]
                quotes = quotes and quote_in_chunk(cite["quote"], text, cite["node_id"])
            items.append(
                Item(
                    review=folder.name,
                    section=section["heading"],
                    sentence=MARKER_RE.sub("", sentence).strip(),
                    claim_ids=ids,
                    sources=sources,
                    unknown_node=unknown,
                    quotes_found=quotes and not unknown,
                )
            )
    return items


async def judge(items: list[Item], llm: LLM) -> None:
    for start in range(0, len(items), BATCH):
        batch = [it for it in items[start : start + BATCH] if it.sources]
        text = "\n\n".join(
            f"Item {n}\nSENTENCE: {it.sentence}\nSOURCE: " + "\n---\n".join(s[:1500] for s in it.sources)
            for n, it in enumerate(batch, start=1)
        )
        result = await llm.astructured_predict(Verdicts, PromptTemplate(JUDGE), items=text)
        for v in result.verdicts:
            if 1 <= v.item <= len(batch):
                batch[v.item - 1].verdict, batch[v.item - 1].reason = v.verdict, v.reason
    for it in items:
        it.verdict = it.verdict or ("unsupported" if not it.sources else "unjudged")


async def second_opinion(items: list[Item], llm: LLM, seed: int = 0) -> list[Item]:
    evaluator = FaithfulnessEvaluator(llm=llm)
    sample = random.Random(seed).sample([it for it in items if it.sources], min(SAMPLE, len(items)))
    for it in sample:
        result = await evaluator.aevaluate(response=it.sentence, contexts=it.sources)
        it.faithfulness = bool(result.passing)
    return sample


def metrics(items: list[Item], sample: list[Item]) -> dict:
    n = len(items) or 1
    supported = sum(it.verdict == "supported" for it in items)
    partial = sum(it.verdict == "partial" for it in items)
    agree = [it for it in sample if it.faithfulness is not None]
    return {
        "reviews": len({it.review for it in items}),
        "cited_sentences": len(items),
        "supported_strict_pct": round(100 * supported / n, 1),
        "supported_lenient_pct": round(100 * (supported + partial) / n, 1),
        "unknown_node_pct": round(100 * sum(it.unknown_node for it in items) / n, 1),
        "quotes_found_pct": round(100 * sum(it.quotes_found for it in items) / n, 1),
        "faithfulness_sample": len(agree),
        "faithfulness_agreement_pct": round(
            100
            * sum((it.verdict in ("supported", "partial")) == it.faithfulness for it in agree)
            / len(agree),
            1,
        )
        if agree
        else None,
    }


def write_report(m: dict, items: list[Item], cost: float) -> None:
    flagged = [it for it in items if it.verdict == "unsupported"][:15]
    disagreements = [
        it
        for it in items
        if it.faithfulness is not None and (it.verdict in ("supported", "partial")) != it.faithfulness
    ]
    met = m["supported_lenient_pct"] >= 95 and m["unknown_node_pct"] == 0
    lines = [
        "# Citation faithfulness",
        "",
        f"{m['cited_sentences']} cited sentences in {m['reviews']} reviews. Judge: Haiku, strict rubric "
        f"([EVAL-CITE] prompt); second opinion: LlamaIndex FaithfulnessEvaluator on "
        f"{m['faithfulness_sample']} sentences.",
        "",
        "| metric | value | target |",
        "|---|---|---|",
        f"| supported (strict) | {m['supported_strict_pct']}% | |",
        f"| supported + partial | {m['supported_lenient_pct']}% | >= 95% |",
        f"| unknown nodes | {m['unknown_node_pct']}% | 0% |",
        f"| quotes found in their chunks | {m['quotes_found_pct']}% | |",
        f"| judge vs FaithfulnessEvaluator agreement | {m['faithfulness_agreement_pct']}% | |",
        "",
        f"Acceptance (spec M8): **{'met' if met else 'NOT met'}**. Eval cost: ${cost:.4f}.",
        "",
        "## Unsupported sentences (up to 15)",
        "",
        *[f"- [{it.review} / {it.section}] {it.sentence}  \n  _judge: {it.reason}_" for it in flagged],
        "",
        "## Where the two judges disagreed",
        "",
        *[
            f"- judge **{it.verdict}**, FaithfulnessEvaluator "
            f"**{'pass' if it.faithfulness else 'fail'}**: {it.sentence}"
            for it in disagreements
        ],
        "",
        "## Notes (yours)",
        "",
        "- Read 5 flagged sentences and their sources yourself. How often do you agree with the judge?",
        "",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines))
    REPORT.with_suffix(".json").write_text(
        json.dumps(
            {"metrics": m, "items": [asdict(it) | {"sources": len(it.sources)} for it in items]}, indent=2
        )
    )


async def write_reviews() -> list[Path]:
    folders = []
    for q in QUESTIONS:
        console.print(f"[cyan]review[/] {q[:80]}")
        result = await drive(
            ReviewWorkflow(timeout=3600).run(start_event=ReviewRequest(question=q)), auto_responder
        )
        assert isinstance(result, ReviewReady)
        if result.error:
            console.print(f"  [red]failed[/]: {result.error}")
            continue
        folders.append(Path(result.markdown_path).parent)
    return folders


async def run(existing: bool) -> None:
    out = get_settings().p2_out_dir
    folders = sorted({p.parent for p in out.rglob("draft.json")}) if existing else await write_reviews()
    if not folders:
        raise typer.BadParameter("no reviews with draft.json found (reviews written before M6 lack it)")
    manager = ResourceManager()
    storage = await manager.get(Resource(get_storage))
    llm = await manager.get(Resource(get_llm))
    before = get_cost_tracker().spent_usd
    items = [it for f in folders for it in collect_items(f, storage)]
    console.print(f"{len(items)} cited sentences in {len(folders)} reviews; judging...")
    await judge(items, llm)
    sample = await second_opinion(items, llm)
    m = metrics(items, sample)
    write_report(m, items, get_cost_tracker().spent_usd - before)
    console.print(json.dumps(m, indent=2))
    console.print(f"report: {REPORT}")


def main(
    existing: bool = typer.Option(False, "--existing", help="Evaluate reviews already in out/."),
) -> None:
    if not get_settings().anthropic_api_key:
        raise typer.BadParameter("ANTHROPIC_API_KEY is not set")
    asyncio.run(run(existing))


if __name__ == "__main__":
    typer.run(main)
