"""Stopping running runs with why they stopped, which a round that stops, the agent's
work that went quiet or failed, and a start the agent didn't take all do."""

from sqlalchemy import ColumnElement, Connection, update

from backend.database import runs
from backend.models import RunStatus


def stop_runs(db: Connection, because: str, *which: ColumnElement[bool]) -> None:
    """Mark the running runs that match stopped, with why."""
    db.execute(
        update(runs)
        .where(runs.c.status == RunStatus.RUNNING, *which)
        .values(status=RunStatus.STOPPED, stopped_because=because)
    )
