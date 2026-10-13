"""The claim agent's tools, each calling the backend operation it is named after, and
the context and state they read."""

import operator
from dataclasses import dataclass
from typing import Annotated, Any, TypedDict

from langchain.tools import ToolRuntime, tool
from langchain_core.messages import AnyMessage, ToolMessage
from langgraph.graph.message import add_messages
from langgraph.types import Command

from agent import api
from agent.json_text import as_json


@dataclass
class ClaimContext:
    """The claim a claim agent is working on, and the run it works in, if any."""

    claim_id: str
    run_id: str | None


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


def claim_as_read(claim_id: str) -> str:
    """A claim in full, as the claim agent reads it, which is also what the check for
    hidden instructions reads."""
    return as_json(api.get_claim(claim_id))


@tool
def get_claim(runtime: ToolRuntime[ClaimContext]) -> str:
    """Get your claim in full: the story, the items claimed and the documents."""
    return claim_as_read(runtime.context.claim_id)


@tool
def get_policy(policy_id: str) -> str:
    """Get a policy: the plan, add-ons, purchase date, trip and travelers."""
    return as_json(api.get_policy(policy_id))


@tool
def get_claim_history(customer_id: str) -> str:
    """Get a customer's earlier claims, with the outcome and the amount paid."""
    return as_json(api.get_claim_history(customer_id))


@tool
def search_documents(query: str) -> str:
    """Find the sections of the wording and the manual containing one word or phrase."""
    return as_json(api.search_documents(query))


@tool(response_format="content_and_artifact")
def read_section(
    document: api.DocumentName, number: int
) -> tuple[str, tuple[api.StepKind, str]]:
    """Read one section of the policy wording or the claims manual in full."""
    section = api.read_section(document, number)
    read = f"{section['document_title']}, section {number}: {section['title']}"
    return as_json(section), ("reading", read)


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
    claim_id = runtime.context.claim_id
    return as_json(api.calculate_payout(claim_id, benefit, lines, paid_by_others))


@tool
def record_decision(
    decision: api.DecisionKind,
    payout: Annotated[float, "In US dollars, and 0 for a decline or a referral"],
    section: Annotated[str, "The sections of the wording and the manual relied on"],
    reason: Annotated[str, "Two or three plain sentences for a colleague"],
    runtime: ToolRuntime[ClaimContext],
) -> Command:
    """Record the decision on your claim, once, which ends your work on it."""
    claim_id = runtime.context.claim_id
    claim = api.record_decision(claim_id, decision, payout, section, reason)
    message = ToolMessage(as_json(claim), tool_call_id=runtime.tool_call_id)
    update = {
        "messages": [message],
        "decision": claim["decision"],
        "status": claim["status"],
    }
    return Command(update=update)


CLAIM_TOOLS = [
    get_claim,
    get_policy,
    get_claim_history,
    search_documents,
    read_section,
    calculate_payout,
    record_decision,
]
