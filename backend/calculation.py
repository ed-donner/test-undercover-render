"""Each claim's latest calculation of its payout, kept for the attempt it was made
in, which an approval in that attempt must match."""

from sqlalchemy import Connection, RowMapping, delete, insert, select

from backend.database import calculations, now
from backend.models import Calculation, Payout


def keep_calculation(
    db: Connection, claim_id: str, thread_id: str, payout: Payout
) -> None:
    """Keep a claim's latest calculation, in place of any before it, on the thread
    of the attempt it was made in."""
    db.execute(delete(calculations).where(calculations.c.claim_id == claim_id))
    lines = [line.model_dump() for line in payout.calculation]
    db.execute(
        insert(calculations).values(
            claim_id=claim_id,
            thread_id=thread_id,
            lines=lines,
            payout=payout.payout,
            calculated_at=now(),
        )
    )


def clear_calculation(db: Connection, claim_id: str) -> None:
    """Forget a claim's calculation, so its next approval needs one of its own."""
    db.execute(delete(calculations).where(calculations.c.claim_id == claim_id))


def attempts_calculation(db: Connection, claim: RowMapping) -> Calculation | None:
    """Return the latest calculation on a claim's current attempt, if any."""
    query = select(calculations).where(
        calculations.c.claim_id == claim["claim_id"],
        calculations.c.thread_id == claim["thread_id"],
    )
    row = db.execute(query).mappings().first()
    return Calculation(lines=row["lines"], payout=row["payout"]) if row else None
