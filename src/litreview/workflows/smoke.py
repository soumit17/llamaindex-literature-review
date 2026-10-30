"""One-step workflow whose only job is to prove the Resource-injected LLM works (M0 acceptance).

The step never constructs a client: it declares `llm` as an injected Resource, and the framework
builds it via the chained `get_llm` factory (JSON config + cost tracker -> BudgetedAnthropic).
"""

from typing import Annotated

from llama_index.core.llms import LLM, ChatMessage
from workflows import Workflow, step
from workflows.events import StartEvent, StopEvent
from workflows.resource import Resource

from litreview.resources import get_llm


class Ask(StartEvent):
    prompt: str = "In one sentence: what is an event-driven workflow?"


class SmokeWorkflow(Workflow):
    @step
    async def ask(self, ev: Ask, llm: Annotated[LLM, Resource(get_llm)]) -> StopEvent:
        resp = await llm.achat([ChatMessage(role="user", content=ev.prompt)])
        return StopEvent(result=resp.message.content)
