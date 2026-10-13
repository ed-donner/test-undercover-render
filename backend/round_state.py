"""A round of the improver as its records stand, which the improvement router, the
runs router and the claim operations all need: finding a round, where it has got
to, what it has spent against its limit, and stopping it."""

from fastapi import HTTPException
from sqlalchemy import ColumnElement, Connection, RowMapping, select, update

from backend import spending
from backend.database import now, proposals, rounds, runs, settings, versions
from backend.models import (
    EvaluationSet,
    ProposalKind,
    RoundStage,
    RoundStatus,
    RunStatus,
    Spending,
    Verdict,
)
from backend.money import dollars
from backend.stops import stop_runs
from backend.verdict import STOPPED_BEFORE_VERDICT

ROUND_NOT_FOUND = "Round {round_id} not found"
NOT_OPEN = "Round {number} is {status}"
# A version's evaluations: once on the evaluation set and twice on the held-out set.
EVALUATIONS = [EvaluationSet.EVALUATION, EvaluationSet.HELD_OUT, EvaluationSet.HELD_OUT]


def round_row(db: Connection, round_id: str) -> RowMapping:
    """Return one round's row, or raise a 404."""
    query = select(rounds).where(rounds.c.round_id == round_id)
    row = db.execute(query).mappings().first()
    if row is None:
        raise HTTPException(404, ROUND_NOT_FOUND.format(round_id=round_id))
    return row


def open_round(db: Connection, round_id: str) -> RowMapping:
    """Return a round's row if it is open, or raise a 404 or a 409: a round that
    finished or was stopped records nothing more."""
    row = round_row(db, round_id)
    if row["status"] != RoundStatus.OPEN:
        raise HTTPException(
            409, NOT_OPEN.format(number=row["number"], status=row["status"])
        )
    return row


def waiting_proposal(db: Connection, round_id: str) -> RowMapping | None:
    """Return the round's proposal that waits for a handler, if any."""
    query = select(proposals).where(
        proposals.c.round_id == round_id, proposals.c.review.is_(None)
    )
    return db.execute(query).mappings().first()


def tried_versions(db: Connection, round_ids: list[str]) -> dict[str, RowMapping]:
    """Return the versions rounds made from an approved change, by round, in one
    query for all the rounds."""
    query = select(versions).where(versions.c.round_id.in_(round_ids))
    return {row["round_id"]: row for row in db.execute(query).mappings()}


def tried_version(db: Connection, round_id: str) -> RowMapping | None:
    """Return the version the round made from an approved change, if any."""
    return tried_versions(db, [round_id]).get(round_id)


def evaluations_of(db: Connection, round_id: str, version: int) -> list[RowMapping]:
    """Return the round's evaluations of a version, oldest first."""
    query = (
        select(runs)
        .where(runs.c.round_id == round_id, runs.c.version == version)
        .order_by(runs.c.number)
    )
    return list(db.execute(query).mappings())


def finished_of(evaluations: list[RowMapping]) -> int:
    """Count the evaluations that finished."""
    return sum(run["status"] == RunStatus.FINISHED for run in evaluations)


def stage_of(db: Connection, row: RowMapping) -> tuple[RoundStage, str | None]:
    """Work out where an open round has got to, with its progress through its
    evaluations: a proposal waiting comes first, then a verdict, then a version
    under test, then the first evaluations still needed."""
    waiting = waiting_proposal(db, row["round_id"])
    if waiting:
        if waiting["kind"] == ProposalKind.CHANGE:
            return RoundStage.CHANGE_WAITING, None
        return RoundStage.RECIPE_WAITING, None
    version = tried_version(db, row["round_id"])
    if version and version["verdict"]:
        return RoundStage.VERDICT, None
    if version:
        done = finished_of(evaluations_of(db, row["round_id"], version["number"]))
        return RoundStage.EVALUATING, f"{done} of {len(EVALUATIONS)}"
    needed = len(row["first_evaluations"])
    done = finished_of(evaluations_of(db, row["round_id"], row["starting_version"]))
    if done < needed:
        return RoundStage.FIRST_EVALUATIONS, f"{done} of {needed}"
    return RoundStage.IMPROVING, None


def spending_limits(db: Connection, round_ids: list[str]) -> dict[str, float]:
    """Return the spending limit each round works to, from its own settings, by
    round, in one query for all the rounds."""
    query = (
        select(rounds.c.round_id, settings.c.spending_limit)
        .join(settings, settings.c.number == rounds.c.settings)
        .where(rounds.c.round_id.in_(round_ids))
    )
    return {round_id: limit for round_id, limit in db.execute(query)}


def spending_limit(db: Connection, row: RowMapping) -> float:
    """Return the spending limit the round works to, as spending_limits does."""
    return spending_limits(db, [row["round_id"]])[row["round_id"]]


def spending_of(db: Connection, row: RowMapping) -> Spending:
    """Return the round's limit, what it has spent and what's left, which is never
    below zero."""
    limit, spent = spending_limit(db, row), spending.spent(db, row["round_id"])
    return Spending(limit=limit, spent=spent, left=max(limit - spent, 0))


def left_to_spend(db: Connection, row: RowMapping) -> float:
    """Return what's left of the round's limit."""
    return spending_of(db, row).left


def why_no_claim_starts(db: Connection, row: RowMapping) -> str | None:
    """Say why no new claim may start in a round's evaluations, if it may not: the
    round is no longer open, or it has spent its limit."""
    if row["status"] != RoundStatus.OPEN:
        return NOT_OPEN.format(number=row["number"], status=row["status"])
    if left_to_spend(db, row) <= 0:
        limit = dollars(spending_limit(db, row))
        return f"Round {row['number']} has spent its limit of {limit}"
    return None


def roll_back(db: Connection, version: int, reason: str) -> None:
    """Roll back a version, with why."""
    db.execute(
        update(versions)
        .where(versions.c.number == version)
        .values(verdict=Verdict.ROLLED_BACK, verdict_reason=reason)
    )


def stop(
    db: Connection,
    row: RowMapping,
    by: str | None,
    because: str,
    *also: ColumnElement[bool],
) -> bool:
    """Stop a round that is still open, and still matches `also`, with its running
    evaluation, both with why, rolling back a version it hadn't yet given a
    verdict, and say whether it stopped. A round finished or stopped since `row`
    was read is left as it is. The current version stays as it was."""
    stopped = db.execute(
        update(rounds)
        .where(
            rounds.c.round_id == row["round_id"],
            rounds.c.status == RoundStatus.OPEN,
            *also,
        )
        .values(
            status=RoundStatus.STOPPED,
            stopped_by=by,
            stopped_because=because,
            finished_at=now(),
        )
    )
    if stopped.rowcount == 0:
        return False
    stop_runs(db, because, runs.c.round_id == row["round_id"])
    version = tried_version(db, row["round_id"])
    if version and version["verdict"] is None:
        roll_back(db, version["number"], STOPPED_BEFORE_VERDICT)
    return True
