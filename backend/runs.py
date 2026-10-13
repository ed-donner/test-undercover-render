"""The backend's operations on runs: the dispatches and evaluations the agent's
service works. Only the service writes them, under /api/runs; the dashboard reads
them under /api/dispatches and /api/evaluations."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import Connection, RowMapping, delete, func, insert, select, update

from backend import agent_service, judge, spending
from backend.database import (
    LABELED_SETS,
    claims,
    grades,
    handler_decisions,
    now,
    run_claims,
    runs,
    waiting_claim,
)
from backend.dependencies import AgentKey, Database, SignedInHandler
from backend.free_models import free_model
from backend.lookups import (
    CLAIM_NOT_FOUND,
    RUN_NOT_FOUND,
    allowed_models,
    current_version_number,
    round_number,
    run_row,
    settings_number,
    version_row,
)
from backend.models import (
    Accepted,
    ClaimGrade,
    DecisionKind,
    DispatchSummary,
    Evaluation,
    EvaluationSet,
    HeldPayout,
    Letter,
    RoundStatus,
    Run,
    RunClaimsRequest,
    RunKind,
    RunStatus,
    ScoredEvaluation,
    StartDispatchRequest,
    StartEvaluationRequest,
    Status,
)
from backend.money import dollars
from backend.round_state import (
    EVALUATIONS,
    evaluations_of,
    left_to_spend,
    open_round,
    round_row,
    stop,
    tried_version,
    why_no_claim_starts,
)
from backend.scoreboard import (
    claims_of,
    expected_answers,
    model_cost_of,
    score,
    score_all,
    seconds_between,
    to_run_claim,
)

# A copy's id is its original's with the evaluation's number, such as CLM-1104-E7.
COPY_ID = "{claim_id}-E{number}"
# The grade of a copy the agent didn't decide, which the judge isn't asked about.
UNDECIDED = ClaimGrade(score=0, letter=Letter.F, same_grounds=0, same_section=0, cost=0)
# The record of a copy the judge couldn't grade.
NOT_GRADED = {
    "score": None,
    "letter": None,
    "same_grounds": None,
    "same_section": None,
    "cost": 0,
}
FIRST_EVALUATIONS_CUT_SHORT = "The spending limit cut short its first evaluations"
# Claims a dispatch left that the next one picks up.
UNFINISHED = {Status.IN_PROGRESS, Status.WAITING}

router = APIRouter()


def find_run(db: Connection, run_id: str) -> Run:
    """Return one run with its claims, its model cost and its time, or raise a 404."""
    row = run_row(db, run_id)
    return Run(
        **row,
        model_cost=model_cost_of(db, run_id),
        seconds=seconds_between(row["started_at"], row["finished_at"]),
        round_number=round_number(db, row["round_id"]),
        claims=[to_run_claim(claim) for claim in claims_of(db, run_id)],
    )


def running_run(db: Connection, run_id: str) -> RowMapping:
    """Return a run's row if it is still running, or raise a 404 or a 409."""
    row = run_row(db, run_id)
    if row["status"] != RunStatus.RUNNING:
        raise HTTPException(409, f"Run {run_id} is not running")
    return row


def summarize(rows: list[RowMapping]) -> DispatchSummary:
    """Say what a dispatch left, from its claims as they stand, counting each claim
    once: the decisions, with the payouts waiting for a sign-off counted as
    approved, the claims left for a handler, and those the next dispatch picks up."""
    unfinished = [row["claim_id"] for row in rows if row["status"] in UNFINISHED]
    decided = [row for row in rows if row["status"] not in UNFINISHED]
    decisions = [row["decision"] for row in decided]
    return DispatchSummary(
        approved=decisions.count(DecisionKind.APPROVE),
        declined=decisions.count(DecisionKind.DECLINE),
        referred=decisions.count(DecisionKind.REFER),
        waiting_for_sign_off=[
            HeldPayout(claim_id=row["claim_id"], payout=row["payout"])
            for row in rows
            if row["status"] == Status.WAITING_FOR_SIGN_OFF
        ],
        left_for_handler=[
            row["claim_id"] for row in rows if row["status"] == Status.LEFT_FOR_HANDLER
        ],
        unfinished=unfinished,
    )


def new_run(
    db: Connection, kind: RunKind, fields: dict[str, Any], version: RowMapping
) -> RowMapping:
    """Record a new run, running, on a version of the claim agent with its model
    and reasoning effort, and return its row."""
    run_id = str(uuid.uuid4())
    db.execute(
        insert(runs).values(
            run_id=run_id,
            kind=kind,
            **fields,
            version=version["number"],
            model=version["model"],
            reasoning_effort=version["reasoning_effort"],
            status=RunStatus.RUNNING,
            started_at=now(),
        )
    )
    return run_row(db, run_id)


def put_claims(db: Connection, run_id: str, claim_ids: list[str]) -> None:
    """Record a run's claims in order, in place of any recorded before."""
    db.execute(delete(run_claims).where(run_claims.c.run_id == run_id))
    if claim_ids:
        db.execute(
            insert(run_claims),
            [
                {"run_id": run_id, "position": position, "claim_id": claim_id}
                for position, claim_id in enumerate(claim_ids)
            ],
        )


def originals(
    db: Connection, evaluation_set: EvaluationSet, tiny: bool
) -> list[dict[str, Any]]:
    """Return the records of a labeled set's claims, all or its tiny ones, oldest
    submitted first."""
    chosen = select(handler_decisions.c.claim_id).where(
        handler_decisions.c.evaluation_set == evaluation_set
    )
    if tiny:
        chosen = chosen.where(handler_decisions.c.tiny)
    table = LABELED_SETS[evaluation_set].claims
    records = db.execute(select(table.c.record).where(table.c.claim_id.in_(chosen)))
    return sorted(records.scalars(), key=lambda r: (r["submitted_on"], r["claim_id"]))


def make_copies(
    db: Connection, run: RowMapping, records: list[dict[str, Any]]
) -> list[str]:
    """Copy each claim, waiting, as the evaluation's own, with a new id in its record
    too, and return the copies' ids in order."""
    copies = [
        record
        | {
            "claim_id": COPY_ID.format(
                claim_id=record["claim_id"], number=run["number"]
            )
        }
        for record in records
    ]
    db.execute(
        insert(claims),
        [
            waiting_claim(
                copy, evaluation_id=run["run_id"], copy_of=original["claim_id"]
            )
            for copy, original in zip(copies, records, strict=True)
        ],
    )
    return [copy["claim_id"] for copy in copies]


def evaluation_of(db: Connection, fields: dict[str, Any], version: RowMapping) -> Run:
    """Record a new evaluation on a version, with a waiting copy of each claim."""
    row = new_run(db, RunKind.EVALUATION, fields, version)
    records = originals(db, fields["evaluation_set"], fields["tiny"])
    put_claims(db, row["run_id"], make_copies(db, row, records))
    return find_run(db, row["run_id"])


def set_size(db: Connection, evaluation_set: EvaluationSet) -> int:
    """How many claims a labeled set holds."""
    query = select(func.count()).where(
        handler_decisions.c.evaluation_set == evaluation_set
    )
    return db.execute(query).scalar_one()


def next_evaluation(
    db: Connection, row: RowMapping
) -> tuple[RowMapping, EvaluationSet]:
    """Return the version a round's next evaluation is of, and its set: the
    round's starting version on the sets of its first evaluations, then its
    version under test once on the evaluation set and twice on the held-out set,
    until the verdict. Raise a 409 for any other, so a version's scores never
    change after its verdict."""
    tried = tried_version(db, row["round_id"])
    if tried is not None and tried["verdict"] is not None:
        raise HTTPException(409, f"Version {tried['number']} already has its verdict")
    version = tried or version_row(db, row["starting_version"])
    sets = EVALUATIONS if tried else row["first_evaluations"]
    done = len(evaluations_of(db, row["round_id"], version["number"]))
    if done >= len(sets):
        raise HTTPException(
            409,
            f"Round {row['number']} has run every evaluation version "
            f"{version['number']} needs",
        )
    return version, sets[done]


def refuse_what_the_round_cant_afford(
    db: Connection, row: RowMapping, version: RowMapping
) -> None:
    """Raise a 409 when the evaluations a version still needs are likely to cost
    more than what's left of the round's limit, so the first of the three checks
    all three."""
    done = len(evaluations_of(db, row["round_id"], version["number"]))
    claims_left = sum(set_size(db, s) for s in EVALUATIONS[done:])
    models = {model.model: model for model in allowed_models(db)}
    current = version_row(db, current_version_number(db))
    per_claim = spending.cost_per_claim(
        db, models[version["model"]], models[current["model"]]
    )
    estimate, left = claims_left * per_claim, left_to_spend(db, row)
    if estimate > left:
        raise HTTPException(
            409,
            f"The evaluations could cost about {dollars(estimate)}, and "
            f"{dollars(left)} of the round's limit is left",
        )


def cut_short(db: Connection, row: RowMapping) -> bool:
    """Say whether a round's evaluation was cut short: its round was stopped, or
    spent its limit before every copy started."""
    if row["round_id"] is None:
        return False
    round_ = round_row(db, row["round_id"])
    if why_no_claim_starts(db, round_) is None:
        return False
    unstarted = any(
        claim["status"] == Status.WAITING for claim in claims_of(db, row["run_id"])
    )
    return round_["status"] != RoundStatus.OPEN or unstarted


def stop_a_round_in_its_first_evaluations(db: Connection, row: RowMapping) -> None:
    """Stop an open round whose first evaluation the limit cut short, before its
    improver runs."""
    round_ = round_row(db, row["round_id"])
    first = row["version"] == round_["starting_version"]
    if round_["status"] == RoundStatus.OPEN and first:
        stop(db, round_, None, FIRST_EVALUATIONS_CUT_SHORT)


def evaluation_row(db: Connection, run_id: str) -> RowMapping:
    """Return an evaluation's row, or raise a 404."""
    row = run_row(db, run_id)
    if row["kind"] != RunKind.EVALUATION:
        raise HTTPException(404, RUN_NOT_FOUND.format(run_id=run_id))
    return row


def handler_explanations(
    db: Connection, evaluation_set: EvaluationSet
) -> dict[str, judge.Explanation]:
    """Return the handlers' decisions on a labeled set's claims, with their reasons
    and references, by claim."""
    query = select(handler_decisions).where(
        handler_decisions.c.evaluation_set == evaluation_set
    )
    return {
        d["claim_id"]: judge.Explanation(d["decision"], d["reason"], d["reference"])
        for d in db.execute(query).mappings()
    }


def grade_copy(copy: RowMapping, handler: judge.Explanation) -> ClaimGrade | None:
    """Grade a copy's explanation against the handler's: an F without asking the
    judge for a copy the agent didn't decide."""
    if copy["decision"] is None:
        return UNDECIDED
    agent = judge.Explanation(copy["decision"], copy["reason"], copy["section"])
    return judge.grade(handler, agent)


def grade_copies(db: Connection, row: RowMapping) -> None:
    """Grade an evaluation's copies, in parallel, one thread for each, and record
    the grades. With a free model there's no judge, so nothing is graded."""
    if free_model():
        return
    handlers = handler_explanations(db, row["evaluation_set"])
    copies = claims_of(db, row["run_id"])
    with ThreadPoolExecutor(max_workers=len(copies)) as pool:
        graded = list(
            pool.map(lambda copy: grade_copy(copy, handlers[copy["copy_of"]]), copies)
        )
    db.execute(
        insert(grades),
        [
            {
                "claim_id": copy["claim_id"],
                "run_id": row["run_id"],
                **(grade.model_dump() if grade else NOT_GRADED),
                "graded_at": now(),
            }
            for copy, grade in zip(copies, graded, strict=True)
        ],
    )


@router.post(
    "/api/runs/dispatches", operation_id="create_dispatch", dependencies=[AgentKey]
)
def create_dispatch(request: StartDispatchRequest, db: Database) -> Run:
    """Record a new dispatch on the current version, with its claims to come."""
    current = version_row(db, current_version_number(db))
    row = new_run(db, RunKind.DISPATCH, request.model_dump(), current)
    return find_run(db, row["run_id"])


@router.post(
    "/api/runs/evaluations", operation_id="create_evaluation", dependencies=[AgentKey]
)
def create_evaluation(request: StartEvaluationRequest, db: Database) -> Run:
    """Record a new evaluation on the current version, with a copy of each claim."""
    current = version_row(db, current_version_number(db))
    return evaluation_of(db, request.model_dump(), current)


@router.post(
    "/api/runs/rounds/{round_id}/evaluations",
    operation_id="create_round_evaluation",
    dependencies=[AgentKey],
)
def create_round_evaluation(round_id: str, db: Database) -> Run:
    """Record a round's next whole-set evaluation, on the set it needs next."""
    row = open_round(db, round_id)
    version, evaluation_set = next_evaluation(db, row)
    if version["number"] != row["starting_version"]:
        refuse_what_the_round_cant_afford(db, row, version)
    fields = {
        "evaluation_set": evaluation_set,
        "tiny": False,
        "agents": settings_number(db, row["settings"]).agents,
        "round_id": round_id,
    }
    return evaluation_of(db, fields, version)


@router.put(
    "/api/runs/{run_id}/claims",
    operation_id="record_run_claims",
    dependencies=[AgentKey],
)
def record_run_claims(run_id: str, request: RunClaimsRequest, db: Database) -> Run:
    """Record the claims a running dispatch works, in order."""
    if running_run(db, run_id)["kind"] != RunKind.DISPATCH:
        raise HTTPException(409, f"Run {run_id} is not a dispatch")
    known = select(claims.c.claim_id).where(claims.c.claim_id.in_(request.claim_ids))
    missing = set(request.claim_ids) - set(db.execute(known).scalars())
    if missing:
        raise HTTPException(404, CLAIM_NOT_FOUND.format(claim_id=min(missing)))
    put_claims(db, run_id, request.claim_ids)
    return find_run(db, run_id)


@router.post(
    "/api/runs/{run_id}/finish", operation_id="finish_run", dependencies=[AgentKey]
)
def finish_run(run_id: str, db: Database) -> Run:
    """Finish a run: a dispatch gets its summary, an evaluation its grades or a stop."""
    row = running_run(db, run_id)
    status, summary = RunStatus.FINISHED, None
    if row["kind"] == RunKind.DISPATCH:
        summary = summarize(claims_of(db, run_id)).model_dump()
    elif cut_short(db, row):
        status = RunStatus.STOPPED
        stop_a_round_in_its_first_evaluations(db, row)
    else:
        grade_copies(db, row)
    # A run stopped while its copies were graded stays stopped.
    finished = db.execute(
        update(runs)
        .where(runs.c.run_id == run_id, runs.c.status == RunStatus.RUNNING)
        .values(status=status, finished_at=now(), summary=summary)
    )
    if finished.rowcount == 0:
        raise HTTPException(409, f"Run {run_id} is not running")
    return find_run(db, run_id)


@router.post("/api/runs/stop", operation_id="stop_runs", dependencies=[AgentKey])
def stop_runs(db: Database) -> list[str]:
    """Mark every running run stopped, as the agent's service does when it starts."""
    query = (
        update(runs)
        .where(runs.c.status == RunStatus.RUNNING)
        .values(status=RunStatus.STOPPED)
        .returning(runs.c.run_id)
    )
    return list(db.execute(query).scalars())


@router.get(
    "/api/dispatches/latest",
    operation_id="get_latest_dispatch",
    dependencies=[SignedInHandler],
)
def get_latest_dispatch(db: Database) -> Run | None:
    """Get the newest dispatch with its claims, cost, time and summary, or nothing."""
    query = (
        select(runs.c.run_id)
        .where(runs.c.kind == RunKind.DISPATCH)
        .order_by(runs.c.number.desc())
        .limit(1)
    )
    run_id = db.execute(query).scalar_one_or_none()
    return None if run_id is None else find_run(db, run_id)


@router.post(
    "/api/dispatches",
    operation_id="start_dispatch",
    status_code=202,
    dependencies=[SignedInHandler],
)
def start_dispatch(request: StartDispatchRequest) -> Accepted:
    """Ask the agent's service to start a dispatch with up to N claim agents at once."""
    agent_service.start_dispatch(request.agents)
    return Accepted()


@router.get(
    "/api/evaluations", operation_id="list_evaluations", dependencies=[SignedInHandler]
)
def list_evaluations(db: Database) -> list[Evaluation]:
    """List every evaluation, newest first, with its measures."""
    query = (
        select(runs)
        .where(runs.c.kind == RunKind.EVALUATION)
        .order_by(runs.c.number.desc())
    )
    rows = list(db.execute(query).mappings())
    return [
        Evaluation(**scored.model_dump(exclude={"claims"}))
        for scored in score_all(db, rows, expected_answers(db))
    ]


@router.get(
    "/api/evaluations/{run_id}",
    operation_id="get_evaluation",
    dependencies=[SignedInHandler],
)
def get_evaluation(run_id: str, db: Database) -> ScoredEvaluation:
    """Get one evaluation with its measures and its claims beside the handlers'."""
    return score(db, evaluation_row(db, run_id), expected_answers(db))


@router.post(
    "/api/evaluations",
    operation_id="start_evaluation",
    status_code=202,
    dependencies=[SignedInHandler],
)
def start_evaluation(request: StartEvaluationRequest) -> Accepted:
    """Ask the agent's service to start an evaluation with up to N claim agents."""
    agent_service.start_evaluation(request.evaluation_set, request.tiny, request.agents)
    return Accepted()
