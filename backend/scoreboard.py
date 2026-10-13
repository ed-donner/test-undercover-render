"""Reading runs: a run's claims with their cost and time, an evaluation scored
against the handlers' decisions, and a version's scores from the evaluations its
rounds ran on it."""

from datetime import datetime
from statistics import fmean

from sqlalchemy import Connection, RowMapping, and_, func, select

from backend import scoring
from backend.database import (
    claim_view,
    claims,
    grades,
    handler_decisions,
    model_calls,
    run_claims,
    runs,
    work_times,
)
from backend.lookups import round_numbers
from backend.models import (
    ClaimGrade,
    EvaluationSet,
    Measures,
    RunClaim,
    RunKind,
    RunStatus,
    ScoredClaim,
    ScoredEvaluation,
    VersionScores,
)
from backend.views import to_summary

Expected = dict[tuple[str, str], scoring.Answer]


def claims_of_runs(db: Connection, run_ids: list[str]) -> dict[str, list[RowMapping]]:
    """Return the rows of each run's claims, in order, with each one's model cost,
    its seconds of work, the start of its first spell in the run and its grade, in
    one query for all the runs."""
    cost = (
        select(
            model_calls.c.run_id,
            model_calls.c.claim_id,
            func.sum(model_calls.c.cost).label("cost"),
        )
        .where(model_calls.c.run_id.in_(run_ids))
        .group_by(model_calls.c.run_id, model_calls.c.claim_id)
        .subquery()
    )
    spells = (
        select(
            work_times.c.run_id,
            work_times.c.claim_id,
            func.min(work_times.c.started_at).label("first_started_at"),
            func.sum(work_times.c.seconds).label("seconds"),
        )
        .where(work_times.c.run_id.in_(run_ids))
        .group_by(work_times.c.run_id, work_times.c.claim_id)
        .subquery()
    )
    query = (
        claim_view.add_columns(
            run_claims.c.run_id,
            func.coalesce(cost.c.cost, 0).label("model_cost"),
            spells.c.first_started_at,
            func.coalesce(spells.c.seconds, 0).label("seconds"),
            grades.c.score.label("grade_score"),
            grades.c.letter,
            grades.c.same_grounds,
            grades.c.same_section,
            func.coalesce(grades.c.cost, 0).label("judge_cost"),
        )
        .join(run_claims, run_claims.c.claim_id == claims.c.claim_id)
        .outerjoin(
            cost,
            and_(
                cost.c.run_id == run_claims.c.run_id,
                cost.c.claim_id == claims.c.claim_id,
            ),
        )
        .outerjoin(
            spells,
            and_(
                spells.c.run_id == run_claims.c.run_id,
                spells.c.claim_id == claims.c.claim_id,
            ),
        )
        .outerjoin(grades, grades.c.claim_id == claims.c.claim_id)
        .where(run_claims.c.run_id.in_(run_ids))
        .order_by(run_claims.c.run_id, run_claims.c.position)
    )
    by_run: dict[str, list[RowMapping]] = {run_id: [] for run_id in run_ids}
    for row in db.execute(query).mappings():
        by_run[row["run_id"]].append(row)
    return by_run


def claims_of(db: Connection, run_id: str) -> list[RowMapping]:
    """Return the rows of a run's claims, in order, as claims_of_runs does."""
    return claims_of_runs(db, [run_id])[run_id]


def to_run_claim(row: RowMapping) -> RunClaim:
    """Build a run's claim: its line in the queue, and its cost and time in the run."""
    return RunClaim(
        **to_summary(row).model_dump(),
        started_at=row["first_started_at"],
        seconds=row["seconds"],
        model_cost=row["model_cost"],
    )


def seconds_between(started_at: str, finished_at: str | None) -> float | None:
    """Return the seconds from a start to a finish, or nothing before the finish."""
    if finished_at is None:
        return None
    start, finish = map(datetime.fromisoformat, (started_at, finished_at))
    return (finish - start).total_seconds()


def model_costs(db: Connection, run_ids: list[str]) -> dict[str, float]:
    """Return each run's model cost in all, in one query for all the runs."""
    query = (
        select(model_calls.c.run_id, func.sum(model_calls.c.cost))
        .where(model_calls.c.run_id.in_(run_ids))
        .group_by(model_calls.c.run_id)
    )
    costs = dict.fromkeys(run_ids, 0.0)
    costs.update({run_id: cost for run_id, cost in db.execute(query)})
    return costs


def model_cost_of(db: Connection, run_id: str) -> float:
    """Return one run's model cost in all, as model_costs does."""
    return model_costs(db, [run_id])[run_id]


def grade_of(row: RowMapping) -> ClaimGrade | None:
    """Return the judge's grade of a copy, or nothing when it wasn't graded."""
    if row["grade_score"] is None:
        return None
    return ClaimGrade(
        score=row["grade_score"],
        letter=row["letter"],
        same_grounds=row["same_grounds"],
        same_section=row["same_section"],
        cost=row["judge_cost"],
    )


def scored_claim(row: RowMapping, expected: scoring.Answer) -> ScoredClaim:
    """Put an evaluation's copy beside the handler's decision on its original."""
    answer = scoring.answer_of(row["decision"], row["payout"])
    return ScoredClaim(
        **to_run_claim(row).model_dump(),
        copy_of=row["copy_of"],
        reason=row["reason"],
        section=row["section"],
        grade=grade_of(row),
        handler_decision=expected.decision,
        handler_payout=expected.payout,
        right=scoring.is_right(answer, expected),
        mistake_cost=scoring.mistake_cost(answer, expected),
    )


def expected_answers(db: Connection) -> Expected:
    """Return the handlers' decisions on every labeled claim, by set and claim."""
    rows = db.execute(select(handler_decisions)).mappings()
    return {
        (d["evaluation_set"], d["claim_id"]): scoring.Answer(d["decision"], d["payout"])
        for d in rows
    }


def scored_evaluation(
    row: RowMapping,
    copies: list[RowMapping],
    model_cost: float,
    round_number: int | None,
    expected: Expected,
) -> ScoredEvaluation:
    """Score an evaluation from its copies as they stand and the handlers'
    decisions on their originals."""
    scored = [
        scored_claim(claim, expected[row["evaluation_set"], claim["copy_of"]])
        for claim in copies
    ]
    seconds = seconds_between(row["started_at"], row["finished_at"])
    return ScoredEvaluation(
        **row,
        model_cost=model_cost,
        seconds=seconds,
        round_number=round_number,
        judge_cost=sum(copy["judge_cost"] for copy in copies),
        size=len(scored),
        measures=scoring.measures(scored, model_cost, seconds),
        claims=scored,
    )


def score_all(
    db: Connection, rows: list[RowMapping], expected: Expected
) -> list[ScoredEvaluation]:
    """Score evaluations, in three queries for them all."""
    run_ids = [row["run_id"] for row in rows]
    copies, costs = claims_of_runs(db, run_ids), model_costs(db, run_ids)
    numbers = round_numbers(db, [row["round_id"] for row in rows])
    return [
        scored_evaluation(
            row,
            copies[row["run_id"]],
            costs[row["run_id"]],
            numbers.get(row["round_id"]),
            expected,
        )
        for row in rows
    ]


def score(db: Connection, row: RowMapping, expected: Expected) -> ScoredEvaluation:
    """Score one evaluation, as score_all does."""
    return score_all(db, [row], expected)[0]


def average(measures: list[Measures]) -> Measures | None:
    """Average the measures of several runs, or nothing when there are none. A run
    with no graded claims leaves the grade to the others."""
    if not measures:
        return None
    averaged = {}
    for name in Measures.model_fields:
        values = [getattr(m, name) for m in measures if getattr(m, name) is not None]
        averaged[name] = fmean(values) if values else None
    return Measures(**averaged)


# A version's evaluations, on each set.
BySet = dict[str, list[RowMapping]]


def round_evaluations_of(db: Connection, numbers: list[int]) -> dict[int, BySet]:
    """Return the finished whole-set evaluations rounds ran on each version, oldest
    first, on each set, in one query for all the versions. The Scoreboard's own
    evaluations and any stopped evaluation don't count."""
    query = select(runs).where(
        runs.c.version.in_(numbers),
        runs.c.kind == RunKind.EVALUATION,
        runs.c.round_id.is_not(None),
        runs.c.status == RunStatus.FINISHED,
        runs.c.tiny.is_(False),
    )
    by_version: dict[int, BySet] = {
        number: {s: [] for s in EvaluationSet} for number in numbers
    }
    for row in db.execute(query.order_by(runs.c.number)).mappings():
        by_version[row["version"]][row["evaluation_set"]].append(row)
    return by_version


def round_evaluations(db: Connection, number: int) -> BySet:
    """Return the finished whole-set evaluations rounds ran on a version, as
    round_evaluations_of does."""
    return round_evaluations_of(db, [number])[number]


def scores_of_versions(
    db: Connection, numbers: list[int], expected: Expected
) -> dict[int, VersionScores]:
    """Each version's scores on each set: the averages of the evaluations rounds
    ran on it, in a few queries for all the versions."""
    by_version = round_evaluations_of(db, numbers)
    rows = [
        row
        for by_set in by_version.values()
        for runs_ in by_set.values()
        for row in runs_
    ]
    measures = {s.run_id: s.measures for s in score_all(db, rows, expected)}

    def averaged(by_set: BySet, evaluation_set: EvaluationSet) -> Measures | None:
        return average([measures[row["run_id"]] for row in by_set[evaluation_set]])

    return {
        number: VersionScores(
            evaluation=averaged(by_set, EvaluationSet.EVALUATION),
            held_out=averaged(by_set, EvaluationSet.HELD_OUT),
        )
        for number, by_set in by_version.items()
    }


def version_scores(db: Connection, number: int, expected: Expected) -> VersionScores:
    """A version's scores on each set, as scores_of_versions gives them."""
    return scores_of_versions(db, [number], expected)[number]
