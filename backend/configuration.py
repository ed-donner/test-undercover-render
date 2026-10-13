"""The backend's operations on the claim agent's configuration: its versions, for the
claim agent and for the Configuration page, and the platform's settings and the
models allowed, for the Settings page."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import Connection, RowMapping, insert, select

from backend.database import now, settings, versions
from backend.dependencies import AgentKey, Database, SignedInHandler, senior
from backend.diffs import diff
from backend.documents import contents
from backend.free_models import model_or_free
from backend.lookups import (
    allowed_models,
    current_settings,
    current_version_number,
    version_row,
)
from backend.models import (
    ClaimAgentVersion,
    Configuration,
    Handler,
    ScreeningModel,
    Settings,
    SettingsPage,
    SettingsValues,
    VersionDetails,
    VersionScores,
    VersionStatus,
    VersionSummary,
)
from backend.scoreboard import expected_answers, scores_of_versions, version_scores

router = APIRouter()

# The model the check for instructions hidden in a claim runs on, with no
# reasoning. No version, proposal or setting changes it.
SCREENING_MODEL = ("openai/gpt-6-luna", "none")

ChangesTheSettings = Annotated[Handler, Depends(senior("change the settings"))]


def with_contents(db: Connection, instructions: str) -> str:
    """The claim agent's instructions as it reads them: they end with the contents
    of the policy wording and the claims manual."""
    return f"{instructions}\n{contents(db)}"


def for_the_claim_agent(db: Connection, row: RowMapping) -> ClaimAgentVersion:
    """A version as the claim agent reads it, with no scores."""
    return ClaimAgentVersion(
        number=row["number"],
        instructions=with_contents(db, row["instructions"]),
        model=row["model"],
        reasoning_effort=row["reasoning_effort"],
    )


def status_of(row: RowMapping, current: int) -> VersionStatus:
    """Say where a version stands: current, kept, rolled back or under test."""
    if row["number"] == current:
        return VersionStatus.CURRENT
    if row["verdict"] is None:
        return VersionStatus.UNDER_TEST
    return VersionStatus(row["verdict"])


def summary_of(
    row: RowMapping,
    before: RowMapping | None,
    current: int,
    scores: VersionScores,
) -> VersionSummary:
    """A version with what it changed from the version it was based on, if any,
    where it stands and its scores."""
    changes = diff(before["instructions"], row["instructions"]) if before else None
    return VersionSummary(
        **row,
        status=status_of(row, current),
        model_before=before["model"] if before else None,
        reasoning_effort_before=before["reasoning_effort"] if before else None,
        lines_added=changes.added if changes else 0,
        lines_removed=changes.removed if changes else 0,
        scores=scores,
    )


@router.get(
    "/api/versions/current", operation_id="get_current_version", dependencies=[AgentKey]
)
def get_current_version(db: Database) -> ClaimAgentVersion:
    """Get the current version of the claim agent: its instructions and its model."""
    return for_the_claim_agent(db, version_row(db, current_version_number(db)))


@router.get(
    "/api/versions/{number}", operation_id="get_version", dependencies=[AgentKey]
)
def get_version(number: int, db: Database) -> ClaimAgentVersion:
    """Get one version of the claim agent: its instructions and its model."""
    return for_the_claim_agent(db, version_row(db, number))


@router.get("/api/screening", operation_id="get_screening", dependencies=[AgentKey])
def get_screening() -> ScreeningModel:
    """Get the model the check for instructions hidden in a claim runs on."""
    model, reasoning_effort = model_or_free(*SCREENING_MODEL)
    return ScreeningModel(model=model, reasoning_effort=reasoning_effort)


@router.get(
    "/api/configuration",
    operation_id="get_configuration",
    dependencies=[SignedInHandler],
)
def get_configuration(db: Database) -> Configuration:
    """Get the claim agent's versions, newest first, with what each changed."""
    current = current_version_number(db)
    query = select(versions).order_by(versions.c.number.desc())
    rows = {row["number"]: row for row in db.execute(query).mappings()}
    scores = scores_of_versions(db, list(rows), expected_answers(db))
    return Configuration(
        current=current,
        versions=[
            summary_of(row, rows.get(row["based_on"]), current, scores[number])
            for number, row in rows.items()
        ],
    )


@router.get(
    "/api/configuration/versions/{number}",
    operation_id="get_version_details",
    dependencies=[SignedInHandler],
)
def get_version_details(number: int, db: Database) -> VersionDetails:
    """Get one version in full, with its diff from the version it was based on."""
    row = version_row(db, number)
    before = version_row(db, row["based_on"]) if row["based_on"] else None
    scores = version_scores(db, number, expected_answers(db))
    summary = summary_of(row, before, current_version_number(db), scores)
    return VersionDetails(
        **summary.model_dump(),
        instructions=with_contents(db, row["instructions"]),
        diff=diff(before["instructions"], row["instructions"]) if before else None,
    )


@router.get(
    "/api/settings", operation_id="get_settings", dependencies=[SignedInHandler]
)
def get_settings(db: Database) -> SettingsPage:
    """Get the settings in force, every change with who made it, and the models."""
    query = select(settings).order_by(settings.c.number.desc())
    changes = [Settings(**row) for row in db.execute(query).mappings()]
    return SettingsPage(
        current=changes[0], changes=changes, models_allowed=allowed_models(db)
    )


@router.put("/api/settings", operation_id="change_settings")
def change_settings(
    request: SettingsValues,
    handler: ChangesTheSettings,
    db: Database,
) -> SettingsPage:
    """Change the settings, recording every value with the handler and the time."""
    db.execute(
        insert(settings).values(
            number=current_settings(db).number + 1,
            **request.model_dump(),
            changed_by=handler.name,
            changed_at=now(),
        )
    )
    return get_settings(db)
