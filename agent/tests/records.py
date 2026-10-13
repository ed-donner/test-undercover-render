"""What the test backend has recorded on claims and runs."""

from sqlalchemy import select

from backend.database import engine, model_calls, payments, work_times


def claim_of(client, claim_id):
    return client.get(f"/api/claims/{claim_id}").json()


def rows_of(table, claim_id):
    """The rows of a claim in one of the backend's tables, in the order recorded."""
    query = select(table).where(table.c.claim_id == claim_id)
    with engine().connect() as db:
        rows = db.execute(query.order_by(*table.primary_key)).mappings()
        return [dict(row) for row in rows]


def model_calls_of(claim_id):
    return rows_of(model_calls, claim_id)


def work_times_of(claim_id):
    return rows_of(work_times, claim_id)


def payments_of(claim_id):
    return rows_of(payments, claim_id)
