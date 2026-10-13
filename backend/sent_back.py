"""The decisions handlers sent back to the agent: keeping one with its note, and
reading a claim's, oldest first."""

from sqlalchemy import Connection, RowMapping, insert, select

from backend.database import now, sent_back_decisions
from backend.models import DecisionRecord, SentBackDecision


def keep(db: Connection, claim: RowMapping, note: str, sent_back_by: str) -> None:
    """Keep a claim's decision as sent back, with the handler's note, who sent it
    back and when."""
    db.execute(
        insert(sent_back_decisions).values(
            claim_id=claim["claim_id"],
            **{field: claim[field] for field in DecisionRecord.model_fields},
            note=note,
            sent_back_by=sent_back_by,
            sent_back_at=now(),
        )
    )


def sent_back_of(db: Connection, claim_id: str) -> list[SentBackDecision]:
    """Return the decisions sent back on a claim, oldest first."""
    query = (
        select(sent_back_decisions)
        .where(sent_back_decisions.c.claim_id == claim_id)
        .order_by(sent_back_decisions.c.sent_back_id)
    )
    return [SentBackDecision(**row) for row in db.execute(query).mappings()]
