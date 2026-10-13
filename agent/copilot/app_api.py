"""The UnderCover backend's API for the Copilot: one function for each operation it
uses, each taking the handler's sign-in first and sending it, never the agent's
key, and the app's refusal, which each raises. It has no way to the handlers'
decisions on the labeled sets, the rounds or anything only the agent may do."""

from typing import Any, Literal, TypedDict

from agent import connection
from agent.app_terms import EvaluationSet
from agent.connection import call_as
from agent.context_tools import Sources

CardKind = Literal["claims", "customers", "context", "work", "memory", "action"]
CardStatus = Literal["done", "refused", "failed"]
# The app's refusal of a request, which each function raises.
Refused = connection.Refused
# A turn the Copilot is still working on, as the app records it.
WORKING = "working"


def get_signed_in_handler(sign_in: str) -> dict[str, Any]:
    return call_as(sign_in, "GET", "/me")


def get_conversation(sign_in: str, conversation_id: str) -> dict[str, Any]:
    return call_as(sign_in, "GET", f"/copilot/conversations/{conversation_id}")


def get_copilot_model(sign_in: str) -> dict[str, Any]:
    return call_as(sign_in, "GET", "/copilot/model")


class CardStart(TypedDict):
    """A card as a step starts: its tool, its kind, its main input and what was
    asked."""

    tool: str
    kind: CardKind
    input: str
    asked: str


class CardResult(TypedDict):
    """How a step ended: what came back, or why it was refused or failed, and the
    files an answer came from."""

    status: CardStatus
    answer: str | None
    reason: str | None
    sources: Sources


def start_copilot_step(sign_in: str, turn_id: str, card: CardStart) -> dict[str, Any]:
    path = f"/copilot/turns/{turn_id}/steps"
    return call_as(sign_in, "POST", path, json=card)


def finish_copilot_step(
    sign_in: str, turn_id: str, step_id: int, result: CardResult
) -> dict[str, Any]:
    path = f"/copilot/turns/{turn_id}/steps/{step_id}/finish"
    return call_as(sign_in, "POST", path, json=result)


def finish_turn(
    sign_in: str, turn_id: str, answer: str, model_calls: int, cost: float
) -> dict[str, Any]:
    body = {"answer": answer, "model_calls": model_calls, "cost": cost}
    return call_as(sign_in, "POST", f"/copilot/turns/{turn_id}/finish", json=body)


def pause_turn(sign_in: str, turn_id: str, claim_id: str) -> dict[str, Any]:
    body = {"claim_id": claim_id}
    return call_as(sign_in, "POST", f"/copilot/turns/{turn_id}/pause", json=body)


def fail_turn(sign_in: str, turn_id: str, reason: str) -> dict[str, Any]:
    body = {"reason": reason}
    return call_as(sign_in, "POST", f"/copilot/turns/{turn_id}/failure", json=body)


def list_claims(sign_in: str) -> list[dict[str, Any]]:
    return call_as(sign_in, "GET", "/claims")


def get_claim(sign_in: str, claim_id: str) -> dict[str, Any]:
    return call_as(sign_in, "GET", f"/claims/{claim_id}")


def list_steps(sign_in: str, claim_id: str) -> list[dict[str, Any]]:
    return call_as(sign_in, "GET", f"/claims/{claim_id}/steps")


def get_policy(sign_in: str, policy_id: str) -> dict[str, Any]:
    return call_as(sign_in, "GET", f"/policies/{policy_id}")


def find_customers(sign_in: str, name: str) -> list[dict[str, Any]]:
    return call_as(sign_in, "GET", "/customers", params={"name": name})


def get_customer(sign_in: str, customer_id: str) -> dict[str, Any]:
    return call_as(sign_in, "GET", f"/customers/{customer_id}")


def get_latest_dispatch(sign_in: str) -> dict[str, Any] | None:
    return call_as(sign_in, "GET", "/dispatches/latest")


def list_evaluations(sign_in: str) -> list[dict[str, Any]]:
    return call_as(sign_in, "GET", "/evaluations")


def get_settings(sign_in: str) -> dict[str, Any]:
    return call_as(sign_in, "GET", "/settings")


def get_run(sign_in: str, run_id: str) -> dict[str, Any]:
    return call_as(sign_in, "GET", f"/runs/{run_id}")


def start_dispatch(sign_in: str, agents: int) -> dict[str, Any]:
    return call_as(sign_in, "POST", "/dispatches", json={"agents": agents})


def start_evaluation(
    sign_in: str, evaluation_set: EvaluationSet, tiny: bool, agents: int
) -> dict[str, Any]:
    body = {"evaluation_set": evaluation_set, "tiny": tiny, "agents": agents}
    return call_as(sign_in, "POST", "/evaluations", json=body)


def send_back_claim(sign_in: str, claim_id: str, note: str) -> dict[str, Any]:
    body = {"note": note}
    return call_as(sign_in, "POST", f"/claims/{claim_id}/send-back", json=body)


def sign_off_claim(sign_in: str, claim_id: str) -> dict[str, Any]:
    return call_as(sign_in, "POST", f"/claims/{claim_id}/sign-off")


def count_payouts_over_limit(sign_in: str) -> dict[str, Any]:
    return call_as(sign_in, "GET", "/payouts/over-limit")
