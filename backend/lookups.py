"""Finding a run, a version, the settings and the models allowed, and the messages
for what isn't found, which more than one of the backend's modules need."""

from fastapi import HTTPException
from sqlalchemy import Connection, RowMapping, func, select

from backend.database import models_allowed, rounds, runs, settings, versions
from backend.models import ModelAllowed, Settings, Verdict

RUN_NOT_FOUND = "Run {run_id} not found"
CLAIM_NOT_FOUND = "Claim {claim_id} not found"
VERSION_NOT_FOUND = "Version {number} not found"


def run_row(db: Connection, run_id: str) -> RowMapping:
    """Return one run's row, or raise a 404."""
    row = db.execute(select(runs).where(runs.c.run_id == run_id)).mappings().first()
    if row is None:
        raise HTTPException(404, RUN_NOT_FOUND.format(run_id=run_id))
    return row


def round_numbers(db: Connection, round_ids: list[str | None]) -> dict[str, int]:
    """Return the numbers of the rounds with these ids, by id, in one query."""
    query = select(rounds.c.round_id, rounds.c.number).where(
        rounds.c.round_id.in_(round_ids)
    )
    return {round_id: number for round_id, number in db.execute(query)}


def round_number(db: Connection, round_id: str | None) -> int | None:
    """Return the number of the round with this id, or none for no round."""
    if round_id is None:
        return None
    return round_numbers(db, [round_id])[round_id]


def version_row(db: Connection, number: int) -> RowMapping:
    """Return one version of the claim agent's configuration, or raise a 404."""
    query = select(versions).where(versions.c.number == number)
    row = db.execute(query).mappings().first()
    if row is None:
        raise HTTPException(404, VERSION_NOT_FOUND.format(number=number))
    return row


def current_version_number(db: Connection) -> int:
    """Return the current version: the newest one the business's rule kept, which
    is version 1 until a round keeps another."""
    query = select(func.max(versions.c.number)).where(
        versions.c.verdict == Verdict.KEPT
    )
    return db.execute(query).scalar_one()


def current_settings(db: Connection) -> Settings:
    """Return the settings in force: the newest change."""
    newest = select(func.max(settings.c.number)).scalar_subquery()
    query = select(settings).where(settings.c.number == newest)
    return Settings(**db.execute(query).mappings().one())


def allowed_models(db: Connection) -> list[ModelAllowed]:
    """Return the models the claim agent may use, with their reasoning efforts and
    prices."""
    query = select(models_allowed).order_by(models_allowed.c.position)
    return [ModelAllowed(**row) for row in db.execute(query).mappings()]


def settings_number(db: Connection, number: int) -> Settings:
    """Return the settings as one change left them, such as a round's."""
    query = select(settings).where(settings.c.number == number)
    return Settings(**db.execute(query).mappings().one())
