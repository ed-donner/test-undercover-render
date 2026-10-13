"""Setting the test queue up, straight in the backend's tables."""

from sqlalchemy import update

from backend.database import claims, engine


def leave_waiting(*claim_ids):
    """Leave every claim but the ones named for a handler, out of the agent's way."""
    with engine().begin() as db:
        db.execute(update(claims).values(status="left_for_handler"))
        db.execute(
            update(claims)
            .where(claims.c.claim_id.in_(claim_ids))
            .values(status="waiting")
        )
