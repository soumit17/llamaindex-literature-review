"""Review quality eval (spec §17.3): an LLM rubric judge (Sonnet, once) and your blind scores.

Rubric, 1-5 each: coverage (does it answer every sub-question?), structure, no_fabrication (claims and
papers only from the sources; reference list = cited papers), hedging (confidence matches evidence).

    uv run python -m evals.quality judge        # Sonnet scores the 3 newest reviews (~$0.05)
    uv run python -m evals.quality sheet        # blind copies + a score sheet for YOU
    (fill evals/reports/quality_blind/scores.json: 1-5 per criterion, without looking at the key)
    uv run python -m evals.quality agree        # your scores vs the judge's
"""

from __future__ import annotations

import asyncio
import json
import random
from pathlib import Path

import typer
from llama_index.core.prompts import PromptTemplate
from pydantic import BaseModel, Field
from rich.console import Console
from rich.table import Table

from litreview.config import CONFIG_DIR, PROJECT_ROOT, get_settings
from litreview.cost import CostTracker, load_prices
from litreview.resources import BudgetedAnthropic, LLMProfiles

REPORTS = PROJECT_ROOT / "evals" / "reports"
BLIND = REPORTS / "quality_blind"
CRITERIA = ("coverage", "structure", "no_fabrication", "hedging")
app = typer.Typer(no_args_is_help=True, add_completion=False)
console = Console()

RUBRIC = """[EVAL-QUALITY]
You are reviewing a short literature review written for ML engineers from a fixed set of papers.

Research question: {question}
Sub-questions it was meant to cover:
{sub_questions}

Review (Markdown, with numbered citations and a reference list):
-----
{review}
-----

Score each criterion from 1 (poor) to 5 (excellent), with one sentence of justification:
- coverage: answers every sub-question with substance; gaps acknowledged.
- structure: logical sections, synthesis across papers rather than paper-by-paper summaries.
- no_fabrication: no claims beyond what citations plausibly support; no invented papers, numbers or systems.
- hedging: confidence matches the evidence; limitations and disagreements noted."""


class Score(BaseModel):
    score: int = Field(ge=1, le=5)
    why: str


class QualityScores(BaseModel):
    coverage: Score
    structure: Score
    no_fabrication: Score
    hedging: Score


def newest_reviews(n: int = 3) -> list[Path]:
    """The n most recently written Workflow 2 reviews (folders with review.md + findings.json)."""
    folders = [p.parent for p in get_settings().p2_out_dir.glob("*/findings.json")]
    return sorted(folders, key=lambda f: (f / "review.md").stat().st_mtime, reverse=True)[:n]


def sonnet() -> BudgetedAnthropic:
    s = get_settings()
    profiles = LLMProfiles.model_validate(json.loads((CONFIG_DIR / "llm.json").read_text()))
    tracker = CostTracker(s.p2_runs_dir / "costs.jsonl", s.p2_spend_cap_usd, load_prices())
    from litreview import cost

    cost.install(tracker)
    c = profiles.final
    return BudgetedAnthropic(
        tracker,
        model=c.model,
        temperature=0.0,
        max_tokens=c.max_tokens,
        api_key=s.anthropic_api_key,
        max_retries=2,
    )


async def judge_reviews(folders: list[Path], llm) -> dict[str, dict]:
    out = {}
    for f in folders:
        draft = json.loads((f / "draft.json").read_text())
        findings = json.loads((f / "findings.json").read_text())
        scores = await llm.astructured_predict(
            QualityScores,
            PromptTemplate(RUBRIC),
            question=draft.get("question", f.name),
            sub_questions="\n".join(f"- {x['sub_question']}" for x in findings),
            review=(f / "review.md").read_text(),
        )
        out[f.name] = scores.model_dump()
        console.print(f"  {f.name}: " + ", ".join(f"{c} {out[f.name][c]['score']}" for c in CRITERIA))
    return out


def mean_pct(scores: dict[str, dict]) -> float:
    """Mean rubric score as a percentage (1 -> 0%, 5 -> 100%), for the regression gate."""
    values = [s[c]["score"] for s in scores.values() for c in CRITERIA]
    return round(100 * (sum(values) / len(values) - 1) / 4, 1) if values else 0.0


@app.command()
def judge(n: int = typer.Option(3, help="How many of the newest reviews.")) -> None:
    """Score the newest reviews with Sonnet (the 'final' block of config/llm.json)."""
    folders = newest_reviews(n)
    if not folders:
        raise typer.BadParameter("no reviews with findings.json in out/ (write some with `litreview review`)")
    scores = asyncio.run(judge_reviews(folders, sonnet()))
    result = {
        "judge_model": json.loads((CONFIG_DIR / "llm.json").read_text())["final"]["model"],
        "scores": scores,
        "mean_pct": mean_pct(scores),
    }
    (REPORTS / "quality.json").write_text(json.dumps(result, indent=2))
    console.print(f"mean {result['mean_pct']}%  -> {REPORTS / 'quality.json'}")


@app.command()
def sheet(seed: int = typer.Option(0)) -> None:
    """Copy the judged reviews under random ids, and write a blank score sheet for you."""
    judged = json.loads((REPORTS / "quality.json").read_text())["scores"]
    folders = [get_settings().p2_out_dir / name for name in judged]
    ids = random.Random(seed).sample(range(100, 999), len(folders))
    BLIND.mkdir(parents=True, exist_ok=True)
    key = {}
    for i, f in zip(ids, folders, strict=True):
        (BLIND / f"review-{i}.md").write_text((f / "review.md").read_text())
        key[f"review-{i}"] = f.name
    (REPORTS / "quality_key.json").write_text(json.dumps(key, indent=2))  # don't open before scoring
    template = {name: {c: None for c in CRITERIA} for name in sorted(key)}
    (BLIND / "scores.json").write_text(json.dumps(template, indent=2))
    console.print(f"score {len(key)} reviews in {BLIND}/ by filling {BLIND / 'scores.json'} (1-5)")


def agreement(human: dict[str, dict], machine: dict[str, dict]) -> dict[str, float]:
    """Mean absolute difference per criterion (0 = you and the judge agree exactly)."""
    diffs: dict[str, list[int]] = {c: [] for c in CRITERIA}
    for name, scores in human.items():
        for c in CRITERIA:
            if scores.get(c) is not None and name in machine:
                diffs[c].append(abs(scores[c] - machine[name][c]["score"]))
    return {c: round(sum(v) / len(v), 2) for c, v in diffs.items() if v}


@app.command()
def agree() -> None:
    """Compare your blind scores with the judge's."""
    key = json.loads((REPORTS / "quality_key.json").read_text())
    human = {key[k]: v for k, v in json.loads((BLIND / "scores.json").read_text()).items()}
    machine = json.loads((REPORTS / "quality.json").read_text())["scores"]
    table = Table(title="You vs the judge (1-5)")
    for col in ("review", *CRITERIA):
        table.add_column(col)
    for name, scores in human.items():
        table.add_row(
            name[:40],
            *[f"{scores.get(c)} / {machine[name][c]['score']}" if name in machine else "-" for c in CRITERIA],
        )
    console.print(table)
    diff = agreement(human, machine)
    console.print("mean |you - judge| per criterion: " + ", ".join(f"{c} {v}" for c, v in diff.items()))
    data = json.loads((REPORTS / "quality.json").read_text())
    data["human_agreement_mad"] = diff
    (REPORTS / "quality.json").write_text(json.dumps(data, indent=2))


if __name__ == "__main__":
    app()
