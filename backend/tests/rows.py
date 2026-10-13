"""What the backend has recorded, read and written straight in its tables."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import Table, func, select, update

from backend.calculation import keep_calculation
from backend.database import (
    claim_view,
    claims,
    engine,
    metadata,
    rounds,
    runs,
    stamp,
)
from backend.models import CalculationStep, Payout


def count(table: Table) -> int:
    """How many rows a table holds."""
    with engine().connect() as db:
        return db.execute(select(func.count()).select_from(table)).scalar_one()


def calculated(claim_id: str, payout: float) -> None:
    """Keep a calculation of a payout for a started claim's current attempt, as
    calculate_payout keeps one."""
    with engine().begin() as db:
        query = select(claims.c.thread_id).where(claims.c.claim_id == claim_id)
        thread_id = db.execute(query).scalar_one()
        steps = [CalculationStep(step="The covered costs", amount=payout)]
        worked_out = Payout(calculation=steps, payout=payout, needs_sign_off=False)
        keep_calculation(db, claim_id, thread_id, worked_out)


def heard(table: Table, key: str, value: str, ago: timedelta, column="heard_at"):
    """Set when the app last heard of a piece of the agent's work."""
    moment = stamp(datetime.now(UTC) - ago)
    with engine().begin() as db:
        db.execute(update(table).where(table.c[key] == value).values({column: moment}))


def resume_heard(claim_id: str, ago: timedelta) -> None:
    """Set when the agent last said a resume was working on a claim."""
    heard(claims, "claim_id", claim_id, ago, "resume_heard_at")


def run_heard(run_id: str, ago: timedelta) -> None:
    heard(runs, "run_id", run_id, ago)


def round_heard(round_id: str, ago: timedelta) -> None:
    heard(rounds, "round_id", round_id, ago)


def committed_claim(claim_id: str):
    """A claim's row as another connection reads it: what has been committed."""
    with engine().connect() as db:
        query = claim_view.where(claims.c.claim_id == claim_id)
        return db.execute(query).mappings().one()


def newest(table: Table, key: str) -> str:
    """The id of the newest run or round, which the app created as a handler asked."""
    with engine().connect() as db:
        query = select(table.c[key]).order_by(table.c.number.desc()).limit(1)
        return db.execute(query).scalar_one()


def newest_run() -> str:
    return newest(runs, "run_id")


def newest_round() -> str:
    return newest(rounds, "round_id")


def everything_recorded():
    """Every row of every table, to show that a request changed nothing."""
    with engine().connect() as db:
        return {
            table.name: [dict(row) for row in db.execute(select(table)).mappings()]
            for table in metadata.sorted_tables
        }
