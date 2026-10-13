"""AgentCore Memory, the agent's notes on each customer: the store a claim graph
keeps them in when UNDERCOVER_MEMORY_ID is set, what it saves of a decided claim,
and a search of one customer's memories."""

import os
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.store.base import BaseStore

from agent.agentcore_memory import store_at

MEMORY_ID = "UNDERCOVER_MEMORY_ID"
# Every memory of a customer is under /customers/<customer>, and the summary of
# each of their claims under /customers/<customer>/claims/<claim>/.
CUSTOMERS = "customers"
CLAIM_SUMMARY = f"/{CUSTOMERS}/{{customer_id}}/claims/{{claim_id}}/"
MOST_FOUND = 5


def memory_store() -> BaseStore | None:
    """AgentCore Memory at UNDERCOVER_MEMORY_ID, read now, in the AWS CLI's region,
    or None when it isn't set."""
    memory_id = os.getenv(MEMORY_ID)
    return store_at(memory_id) if memory_id else None


def what_was_claimed(claim: dict[str, Any]) -> str:
    """The claim as its customer made it: its summary, the benefit claimed, the
    date and place of the incident and the items claimed, and never the story or
    the documents."""
    items = "; ".join(
        f"{i['description']}, ${i['amount']:,.2f}" for i in claim["items"]
    )
    return (
        f"Claim {claim['claim_id']}: {claim['summary']}\n"
        f"Benefit claimed: {claim['claim_type']}\n"
        f"Incident: {claim['incident_date']}, {claim['incident_location']}\n"
        f"Items claimed: {items}"
    )


def what_was_decided(claim: dict[str, Any]) -> str:
    """The decision on a claim, with its payout, section and reason."""
    decision = claim["decision"]
    return (
        f"Decision on {claim['claim_id']}: {decision['decision']}, paying "
        f"${decision['payout']:,.2f}, under {decision['section']}. "
        f"{decision['reason']}"
    )


def remember(store: BaseStore, claim: dict[str, Any]) -> str:
    """Save a decided claim to memory, with its customer as the actor and the claim
    as the session: the claim as the customer's message and the decision as the
    agent's. Return what was saved."""
    actor_and_session = (claim["customer_id"], claim["claim_id"])
    claimed, decided = what_was_claimed(claim), what_was_decided(claim)
    store.put(actor_and_session, "claim", {"message": HumanMessage(claimed)})
    store.put(actor_and_session, "decision", {"message": AIMessage(decided)})
    return f"{claimed}\n{decided}"


def recall(store: BaseStore, customer_id: str, claim_id: str, query: str) -> list[str]:
    """Search one customer's memories and return each one's text, leaving out the
    summary of the claim being worked on. AgentCoreMemoryStore gives every result
    the prefix searched as its namespace, so a memory's own namespaces are read
    from its value."""
    own = CLAIM_SUMMARY.format(customer_id=customer_id, claim_id=claim_id)
    found = store.search((CUSTOMERS, customer_id), query=query, limit=MOST_FOUND)
    return [
        item.value["content"] for item in found if own not in item.value["namespaces"]
    ]
