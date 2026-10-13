"""What the app knows of the agent's work: one piece of it at a time, a dispatch, an
evaluation or a round of the improver while it works, and when the agent last spoke
of it. A start takes the lock, marks quiet work stopped, refuses while other work is
going, and then asks the agent, undoing what it did when the agent didn't take the
work."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import Connection, RowMapping, select, update

from backend import agent_service
from backend.database import AGENTS_WORK, locks, now, rounds, runs, stamp
from backend.models import RoundStatus, RunKind, RunStatus
from backend.round_state import stop, waiting_proposal
from backend.stops import stop_runs

# The agent says it is still working every minute; work it hasn't spoken of for
# this long counts as stopped.
QUIET = timedelta(minutes=5)
GONE_QUIET = "The agent stopped answering"
GOING = {
    RunKind.DISPATCH: "A dispatch is running",
    RunKind.EVALUATION: "An evaluation is running",
}
A_ROUND = "Round {number} is running"
NO_LOCK = "The lock on the agent's work is missing. Reseed with npm run seed."


def heard_lately(stamp: str | None) -> bool:
    """Say whether the agent last said it was working within QUIET of now."""
    return (
        stamp is not None and datetime.now(UTC) - datetime.fromisoformat(stamp) < QUIET
    )


def take_the_lock(db: Connection) -> None:
    """Take the lock on the agent's work until the transaction ends. It is the
    transaction's first write, so a second start waits for this one to commit and
    then sees its work. Postgres locks only a row the update finds, so a missing
    row is an error, which reseeding puts right."""
    taken = db.execute(
        update(locks).where(locks.c.name == AGENTS_WORK).values(taken_at=now())
    )
    if taken.rowcount != 1:
        raise RuntimeError(NO_LOCK)


def working_rounds(db: Connection) -> list[RowMapping]:
    """The open rounds the agent is working: those with no proposal waiting for a
    handler."""
    query = select(rounds).where(rounds.c.status == RoundStatus.OPEN)
    return [
        row
        for row in db.execute(query).mappings().all()
        if waiting_proposal(db, row["round_id"]) is None
    ]


def stop_quiet_work(db: Connection) -> None:
    """Mark stopped the work the agent hasn't spoken of for QUIET: a run, or a round
    with its running evaluation, which is part of the round's work."""
    quiet_since = stamp(datetime.now(UTC) - QUIET)
    stop_runs(db, GONE_QUIET, runs.c.round_id.is_(None), runs.c.heard_at < quiet_since)
    for row in working_rounds(db):
        stop(db, row, None, GONE_QUIET, rounds.c.heard_at < quiet_since)


def refuse_while_work_goes_on(db: Connection) -> None:
    """Raise a 409 naming the work that's going: a dispatch, an evaluation, or a
    round while the agent works it."""
    query = select(runs.c.kind).where(
        runs.c.status == RunStatus.RUNNING, runs.c.round_id.is_(None)
    )
    if kind := db.execute(query).scalars().first():
        raise HTTPException(409, GOING[RunKind(kind)])
    if working := working_rounds(db):
        raise HTTPException(409, A_ROUND.format(number=working[0]["number"]))


def clear_the_way(db: Connection) -> None:
    """Make way for a start of the agent's work: take the lock, mark quiet work
    stopped, which stays stopped however the start ends, and refuse while other
    work is going."""
    take_the_lock(db)
    stop_quiet_work(db)
    db.commit()
    take_the_lock(db)
    refuse_while_work_goes_on(db)


def ask_the_agent(
    db: Connection, ask: Callable[[], None], undo: Callable[[str], object]
) -> None:
    """Commit what the app did for the work, so the agent sees it, then ask the
    agent to take it. When the agent didn't, undo it with the reason and commit
    the undo before passing on the refusal; when it may have started, change
    nothing."""
    db.commit()
    try:
        ask()
    except agent_service.NotTaken as refusal:
        undo(refusal.detail)
        db.commit()
        raise
