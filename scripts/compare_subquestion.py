"""M3 comparison (spec §9.3, notes only): LlamaIndex's SubQuestionQueryEngine on 3 questions.

It does in one library call what Workflow 2 will do explicitly in M4: decompose a question into
sub-questions (an LLM call), answer each against a tool (vector or summary engine), then synthesize.
The output is written to evals/reports/subquestion.md for you to compare with M4's plan + research
fan-out. About 6 Haiku calls per question, ~$0.01 in total.

    uv run python scripts/compare_subquestion.py
"""

from __future__ import annotations

import asyncio

import typer
from llama_index.core.indices.document_summary import DocumentSummaryIndexEmbeddingRetriever
from llama_index.core.query_engine import RetrieverQueryEngine, SubQuestionQueryEngine
from llama_index.core.question_gen import LLMQuestionGenerator
from llama_index.core.response_synthesizers import get_response_synthesizer
from llama_index.core.tools import QueryEngineTool, ToolMetadata
from rich.console import Console

from litreview.config import PROJECT_ROOT, get_settings
from litreview.resources import (
    get_cost_tracker,
    get_embed_model,
    get_llm,
    get_reranker,
    get_storage,
    get_summary_index,
    resolve,
)
from litreview.retrieval.engines import (
    SUMMARY_DESCRIPTION,
    VECTOR_DESCRIPTION,
    QueryConfig,
    make_query_engine,
    make_retriever,
)

QUESTIONS = [
    "How do centralized orchestrators and decentralized peer-to-peer designs differ for LLM agent teams?",
    "What mechanisms do multi-agent systems use to reduce hallucinations passed between agents?",
    "How is the communication topology between agents chosen or learned?",
]
REPORT = PROJECT_ROOT / "evals" / "reports" / "subquestion.md"
console = Console()


async def run() -> None:
    llm = await resolve(get_llm)
    embed_model = await resolve(get_embed_model)
    storage = await resolve(get_storage)
    summary_index = await resolve(get_summary_index)
    reranker = await resolve(get_reranker)
    before = get_cost_tracker().spent_usd

    config = QueryConfig(router=False, rerank=True)
    vector_engine = make_query_engine(
        make_retriever(storage.index, None, config, llm, embed_model), config, reranker, llm
    )
    summary_engine = RetrieverQueryEngine(
        retriever=DocumentSummaryIndexEmbeddingRetriever(
            summary_index, similarity_top_k=2, embed_model=embed_model
        ),
        node_postprocessors=[reranker],
        response_synthesizer=get_response_synthesizer(llm=llm),
    )
    engine = SubQuestionQueryEngine.from_defaults(
        query_engine_tools=[
            QueryEngineTool(vector_engine, ToolMetadata(name="passages", description=VECTOR_DESCRIPTION)),
            QueryEngineTool(summary_engine, ToolMetadata(name="summaries", description=SUMMARY_DESCRIPTION)),
        ],
        # Without an explicit question_gen, from_defaults insists on the OpenAI function-calling
        # generator (ImportError here). LLMQuestionGenerator is the provider-neutral one: a prompt
        # asking for a JSON list of {sub_question, tool_name}, parsed by SubQuestionOutputParser.
        question_gen=LLMQuestionGenerator.from_defaults(llm=llm),
        llm=llm,
        verbose=True,  # prints each generated sub-question and the tool it was sent to
        use_async=True,
    )

    lines = ["# SubQuestionQueryEngine on 3 questions", ""]
    for q in QUESTIONS:
        console.rule(q)
        response = await engine.aquery(q)
        papers = sorted({n.node.metadata.get("arxiv_id", "?") for n in response.source_nodes})
        lines += [f"## {q}", "", str(response), "", f"Sources: {', '.join(papers)}", ""]
    spent = get_cost_tracker().spent_usd - before
    lines += [
        f"Cost: ${spent:.4f}",
        "",
        "## Notes (yours)",
        "",
        "- Were the generated sub-questions the ones you'd have asked? (The console log shows them.)",
        "- What can't you control here that Workflow 2's explicit plan -> research steps will let you?",
        "",
    ]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines))
    console.print(f"\nreport: {REPORT}   cost ${spent:.4f}")


def main() -> None:
    if not get_settings().anthropic_api_key:
        raise typer.BadParameter("ANTHROPIC_API_KEY is not set; put it in .env")
    asyncio.run(run())


if __name__ == "__main__":
    typer.run(main)
