"""Claims as the API shows them, built from rows of the claim view."""

from sqlalchemy import RowMapping

from backend.models import Claim, ClaimSummary, Decision, Payment


def to_summary(row: RowMapping) -> ClaimSummary:
    """Build a claim's line in the queue from its row."""
    return ClaimSummary(
        **row["record"]
        | {
            "status": row["status"],
            "customer_name": row["customer_name"],
            "decision": row["decision"],
            "payout": row["payout"],
        }
    )


def to_claim(row: RowMapping) -> Claim:
    """Build a claim in full, with its decision and payment, from its row."""
    decision = None
    if row["decision"] is not None:
        decision = Decision(**{field: row[field] for field in Decision.model_fields})
    payment = None
    if row["paid_at"] is not None:
        payment = Payment(**{field: row[field] for field in Payment.model_fields})
    return Claim(
        **row["record"]
        | {
            "status": row["status"],
            "customer_name": row["customer_name"],
            "thread_id": row["thread_id"],
            "attempts": row["attempts"],
            "evaluation_id": row["evaluation_id"],
            "copy_of": row["copy_of"],
            "decision": decision,
            "payment": payment,
        }
    )
