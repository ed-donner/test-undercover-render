"""What needs a handler, worked out in code from the queue: the payouts held for
sign-off with their amounts, the claims referred, the claims left for a handler,
and any claim sent back that the agent hasn't taken up."""

from typing import Any

from agent.app_terms import REFER, Status


def needs_a_handler(queue: list[dict[str, Any]]) -> dict[str, Any]:
    """What in the queue needs a handler."""
    return {
        "held_for_sign_off": [
            {"claim_id": c["claim_id"], "payout": c["payout"]}
            for c in queue
            if c["status"] == Status.WAITING_FOR_SIGN_OFF
        ],
        "referred": [
            c["claim_id"]
            for c in queue
            if c["status"] == Status.DECIDED and c["decision"] == REFER
        ],
        "left_for_a_handler": [
            c["claim_id"] for c in queue if c["status"] == Status.LEFT_FOR_HANDLER
        ],
        "sent_back_not_taken_up": [
            c["claim_id"] for c in queue if c["status"] == Status.SENT_BACK
        ],
    }
