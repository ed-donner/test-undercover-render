"""The UnderCover backend's API for the claim agent and the agent's service: one
function for each operation they use. It has no way to the scores, the settings,
the rounds or the handlers' decisions."""

from enum import StrEnum
from typing import Any, Literal, TypedDict, Unpack

from pydantic import BaseModel, Field

from agent.connection import call

DecisionKind = Literal["approve", "decline", "refer"]
APPROVE: DecisionKind = "approve"
REFER: DecisionKind = "refer"
StepKind = Literal[
    "screening",
    "tool_call",
    "tool_result",
    "message",
    "lookup",
    "memory_search",
    "memory_save",
    "refusal",
]
# The context files a lookup came from, each with its system, owner and review date.
Sources = list[dict[str, str]]
EvaluationSet = Literal["evaluation", "held_out"]
RunKind = Literal["dispatch", "evaluation"]
DISPATCH: RunKind = "dispatch"
EVALUATION: RunKind = "evaluation"
Benefit = Literal[
    "trip_cancellation",
    "trip_interruption",
    "trip_delay",
    "baggage_delay",
    "baggage",
    "passport",
    "emergency_medical",
]


class Status(StrEnum):
    """Where a claim stands."""

    WAITING = "waiting"
    IN_PROGRESS = "in_progress"
    WAITING_FOR_SIGN_OFF = "waiting_for_sign_off"
    DECIDED = "decided"
    LEFT_FOR_HANDLER = "left_for_handler"


LineKind = Literal[
    "item", "electronics", "cash", "expense", "hotel", "meals_without_receipts"
]


class Line(BaseModel):
    """One covered item or expense on a claim."""

    description: str = Field(description="What the item or expense is")
    amount: float = Field(
        description="The total claimed for the line in US dollars, before any limits. "
        "For several items, the total for all of them"
    )
    quantity: int = Field(
        ge=1,
        description="How many separate items the line holds, such as 3 for three "
        "shirts. A pair or a set is one item, and an expense is 1",
    )
    kind: LineKind = Field(
        description="item: a belonging, or a pair or set that counts as one item. "
        "electronics: only a phone, tablet, laptop, camera or its lens, e-reader or "
        "smartwatch; any other device is an item. "
        "cash: cash that was lost or stolen. "
        "expense: any other cost with a receipt, such as a medical bill, a meal, a "
        "taxi, a fee or a prepaid trip cost. "
        "hotel: a hotel during a trip delay. "
        "meals_without_receipts: meals during a trip delay with no receipts."
    )
    nights: int = Field(
        description="For a hotel, the number of nights, and 0 otherwise"
    )
    hours: float = Field(
        description="For meals without receipts, the length of the delay in hours, "
        "and 0 otherwise"
    )


def list_claims() -> list[dict[str, Any]]:
    return call("GET", "/claims")


def get_claim(claim_id: str) -> dict[str, Any]:
    return call("GET", f"/claims/{claim_id}")


def get_policy(policy_id: str) -> dict[str, Any]:
    return call("GET", f"/policies/{policy_id}")


def get_claim_history(customer_id: str) -> list[dict[str, Any]]:
    return call("GET", f"/customers/{customer_id}/claims")


def get_version(number: int) -> dict[str, Any]:
    return call("GET", f"/versions/{number}")


def get_current_version() -> dict[str, Any]:
    return call("GET", "/versions/current")


def get_screening() -> dict[str, Any]:
    return call("GET", "/screening")


def calculate_payout(
    claim_id: str, benefit: Benefit, lines: list[dict[str, Any]], paid_by_others: float
) -> dict[str, Any]:
    body = {"benefit": benefit, "lines": lines, "paid_by_others": paid_by_others}
    return call("POST", f"/claims/{claim_id}/payout", json=body)


def start_claim(claim_id: str, thread_id: str) -> dict[str, Any]:
    return call("POST", f"/claims/{claim_id}/start", json={"thread_id": thread_id})


def record_step(
    claim_id: str, kind: StepKind, content: str, sources: Sources
) -> dict[str, Any]:
    body = {"kind": kind, "content": content, "sources": sources}
    return call("POST", f"/claims/{claim_id}/steps", json=body)


class DecisionRequest(TypedDict):
    """A decision to record, with who or what made it."""

    decision: DecisionKind
    payout: float
    section: str
    reason: str
    decided_by: str


# The body's fields as keywords, as the direct route passes a tool's inputs.
def record_decision(
    claim_id: str, **request: Unpack[DecisionRequest]
) -> dict[str, Any]:
    return call("POST", f"/claims/{claim_id}/decision", json=request)


def pay_claim(claim_id: str, amount: float) -> dict[str, Any]:
    return call("POST", f"/claims/{claim_id}/payment", json={"amount": amount})


def hold_payment(claim_id: str, reason: str) -> dict[str, Any]:
    return call("POST", f"/claims/{claim_id}/hold", json={"reason": reason})


def fail_claim(claim_id: str, reason: str) -> dict[str, Any]:
    return call("POST", f"/claims/{claim_id}/failure", json={"reason": reason})


def record_model_call(
    claim_id: str,
    run_id: str | None,
    input_tokens: int,
    output_tokens: int,
    cost: float,
) -> dict[str, Any]:
    body = {
        "run_id": run_id,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost": cost,
    }
    return call("POST", f"/claims/{claim_id}/model-calls", json=body)


def record_work_time(
    claim_id: str, run_id: str | None, seconds: float
) -> dict[str, Any]:
    body = {"run_id": run_id, "seconds": seconds}
    return call("POST", f"/claims/{claim_id}/work-times", json=body)


def create_dispatch(agents: int) -> dict[str, Any]:
    return call("POST", "/runs/dispatches", json={"agents": agents})


def create_evaluation(
    evaluation_set: EvaluationSet, tiny: bool, agents: int
) -> dict[str, Any]:
    body = {"evaluation_set": evaluation_set, "tiny": tiny, "agents": agents}
    return call("POST", "/runs/evaluations", json=body)


def record_run_claims(run_id: str, claim_ids: list[str]) -> dict[str, Any]:
    return call("PUT", f"/runs/{run_id}/claims", json={"claim_ids": claim_ids})


def finish_run(run_id: str) -> dict[str, Any]:
    return call("POST", f"/runs/{run_id}/finish")


def stop_runs() -> list[str]:
    return call("POST", "/runs/stop")
