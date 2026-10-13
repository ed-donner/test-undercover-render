"""The claim agent's tools, the app's operations it calls on its route, the context
layer's lookups both agents have, and the search of its memory, and the context and
state they read."""

import operator
from dataclasses import dataclass
from typing import Annotated, Any, TypedDict, cast

from langchain.tools import BaseTool, ToolException, ToolRuntime, tool
from langchain_core.messages import AnyMessage, ToolMessage
from langgraph.graph.message import add_messages
from langgraph.store.base import BaseStore
from langgraph.types import Command

from agent import api, app_terms, memory
from agent.agentcore_memory import UNREACHABLE
from agent.context_tools import CONTEXT_TOOLS, Query
from agent.json_text import as_json
from agent.routes import Route, Target


@dataclass
class ClaimContext:
    """The claim a claim agent is working on, its policy and customer, the run it
    works in, if any, the route its tools take, and who its decisions are made by."""

    claim_id: str
    run_id: str | None
    policy_id: str
    customer_id: str
    route: Route
    decided_by: str


def keep_last(_: Any, new: Any) -> Any:
    """Keep the newest value, even when two tool calls set it in the same step. With
    it, LangGraph starts the key empty, as {} or "", so the key is always there."""
    return new


class ClaimState(TypedDict):
    """What the claim graph keeps for one claim, saved after every step: the check
    for hidden instructions' result, its reason and instructions_found, empty until
    the check has run, and the decision and the claim's status as the backend
    recorded them, empty until then."""

    messages: Annotated[list[AnyMessage], add_messages]
    model_calls: Annotated[int, operator.add]
    screening: Annotated[dict[str, Any], keep_last]
    decision: Annotated[dict[str, Any], keep_last]
    status: Annotated[str, keep_last]


# What the claim agent never reads of a claim: the decisions handlers sent back,
# whose notes reach its model only as a handler's message.
UNREAD = "sent_back_decisions"


def claim_as_read(claim: dict[str, Any]) -> str:
    """A claim in full, as the claim agent reads it, which is also what the check for
    hidden instructions reads."""
    return as_json({field: value for field, value in claim.items() if field != UNREAD})


def on_app(runtime: ToolRuntime[ClaimContext], operation: str, **inputs: Any) -> Any:
    """Call one of the app's operations on the claim agent's route."""
    return runtime.context.route.call(Target.APP, operation, inputs)


# A step a tool gives as its artifact, which the harness records on the claim: its
# kind, its content and the context files it came from.
Step = tuple[api.StepKind, str, api.Sources]


@tool
def get_claim(runtime: ToolRuntime[ClaimContext]) -> str:
    """Get your claim in full: the story, the items claimed and the documents."""
    return claim_as_read(
        on_app(runtime, "get_claim", claim_id=runtime.context.claim_id)
    )


@tool
def get_policy(runtime: ToolRuntime[ClaimContext]) -> str:
    """Get your claim's policy: the plan, add-ons, purchase date, trip and travelers."""
    policy_id = runtime.context.policy_id
    return as_json(on_app(runtime, "get_policy", policy_id=policy_id))


@tool
def get_claim_history(runtime: ToolRuntime[ClaimContext]) -> str:
    """Get your customer's earlier claims, with the outcome and the amount paid."""
    customer_id = runtime.context.customer_id
    return as_json(on_app(runtime, "get_claim_history", customer_id=customer_id))


@tool(response_format="content_and_artifact")
def search_memory(query: Query, runtime: ToolRuntime[ClaimContext]) -> tuple[str, Step]:
    """Search what we remember about this claim's customer from their earlier claims."""
    context = runtime.context
    try:
        found = memory.recall(
            cast(BaseStore, runtime.store),
            context.customer_id,
            context.claim_id,
            query,
        )
    except UNREACHABLE as error:
        raise ToolException(f"The memory can't be reached. {error}") from error
    return as_json(found), ("memory_search", what_was_found(query, found), [])


def what_was_found(query: str, found: list[str]) -> str:
    """Say what a search of the memory looked for and what it found."""
    if not found:
        return f'"{query}": nothing found'
    return "\n".join([f'"{query}"', *(f"- {text}" for text in found)])


@tool
def calculate_payout(
    benefit: Annotated[api.Benefit, "The benefit the claim is paid under"],
    lines: Annotated[
        list[api.Line],
        "The covered items and expenses, one for each line of the claim, with any "
        "excluded ones left out",
    ],
    paid_by_others: Annotated[
        float, "What a carrier, hotel or anyone else has paid or refunded, or 0"
    ],
    runtime: ToolRuntime[ClaimContext],
) -> str:
    """Work out the payout on your claim with UnderCover's payout rules."""
    payout = on_app(
        runtime,
        "calculate_payout",
        claim_id=runtime.context.claim_id,
        benefit=benefit,
        lines=[line.model_dump() for line in lines],
        paid_by_others=paid_by_others,
    )
    return as_json(payout)


@tool
def record_decision(
    decision: app_terms.DecisionKind,
    payout: Annotated[float, "In US dollars, and 0 for a decline or a referral"],
    section: Annotated[str, "The sections of the wording and the manual relied on"],
    reason: Annotated[str, "Two or three plain sentences for a colleague"],
    runtime: ToolRuntime[ClaimContext],
) -> Command:
    """Record the decision on your claim, once, which ends your work on it."""
    claim = on_app(
        runtime,
        "record_decision",
        claim_id=runtime.context.claim_id,
        decision=decision,
        payout=payout,
        section=section,
        reason=reason,
        decided_by=runtime.context.decided_by,
    )
    message = ToolMessage(claim_as_read(claim), tool_call_id=runtime.tool_call_id)
    update = {
        "messages": [message],
        "decision": claim["decision"],
        "status": claim["status"],
    }
    return Command(update=update)


APP_TOOLS = [
    get_claim,
    get_policy,
    get_claim_history,
    calculate_payout,
    record_decision,
]
CLAIM_TOOLS = APP_TOOLS + CONTEXT_TOOLS


def claim_tools(remembers: bool) -> list[BaseTool]:
    """The claim agent's tools, with a search of its memory when it has one."""
    return CLAIM_TOOLS + [search_memory] if remembers else CLAIM_TOOLS


# The target each tool calls, by which a route names a call to it.
TARGETS = {tool.name: Target.APP for tool in APP_TOOLS} | {
    tool.name: Target.CONTEXT for tool in CONTEXT_TOOLS
}
