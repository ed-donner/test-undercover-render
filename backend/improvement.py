"""The backend's operations on the improver's rounds. A senior handler starts a round
and reviews its proposals under /api/improvement, which the app records before it
asks the agent to work the round; the agent records the round's work under
/api/rounds, and the dashboard reads it. The backend keeps a proposal from taking
effect until a handler approves it, keeps or rolls back each version by the
business's rule, and refuses anything a round records once it has finished or been
stopped."""

import uuid
from functools import partial
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import Connection, RowMapping, func, insert, select, update

from backend import agent_service, spending, verdict
from backend.agent_work import clear_the_way
from backend.asking import commit_and_ask
from backend.database import (
    FIRST_VERSION,
    INSTRUCTIONS,
    handler_decisions,
    improver_calls,
    now,
    proposals,
    recipes,
    rounds,
    runs,
    versions,
)
from backend.dependencies import (
    AgentKey,
    Database,
    SignedInHandler,
    senior,
)
from backend.diffs import diff
from backend.free_models import model_or_free
from backend.lookups import (
    allowed_models,
    current_settings,
    current_version_number,
    settings_number,
    version_row,
)
from backend.models import (
    Accepted,
    AgentAnswer,
    ChangeProposalRequest,
    ClaimAgentVersion,
    ClaimBesideHandler,
    Diff,
    EarlierRound,
    Evaluation,
    EvaluationSet,
    EvaluationSetResults,
    FailureRequest,
    Handler,
    HandlerAnswer,
    Improvement,
    ImproverCallRequest,
    ImproverView,
    JudgeAnswer,
    Measures,
    NewNumber,
    Proposal,
    ProposalKind,
    RecipeDetails,
    RecipeProposalRequest,
    RecipeSummary,
    RejectionRequest,
    Review,
    RoundForTheAgent,
    RoundReviewView,
    RoundStatus,
    RoundSummary,
    RoundView,
    RunStatus,
    ScoredClaim,
    Spending,
    Verdict,
    VerdictResult,
    VerdictScores,
    VersionPoint,
    VersionScores,
    WaitingProposal,
)
from backend.round_state import (
    EVALUATIONS,
    evaluations_of,
    finished_of,
    open_round,
    roll_back,
    round_row,
    spending_limits,
    spending_of,
    stage_of,
    stop,
    tried_version,
    tried_versions,
    waiting_proposal,
)
from backend.scoreboard import (
    Expected,
    expected_answers,
    round_evaluations,
    score,
    score_all,
    scores_of_versions,
    version_scores,
)

# The improver's model, unless students on free models have one of their own.
IMPROVER_MODEL = ("openai/gpt-6.1-sol", "medium")
ROUND_OPEN = "Round {number} is open. Finish or stop it first."
NOT_WAITING = "Proposal {proposal_id} isn't waiting for a handler: it was {review}"
# How many of the right claims the improver reads, those the judge graded lowest.
EXPLAINED_LEAST_WELL = 5
YES_FROM = 0.5

router = APIRouter()

StartsRounds = Annotated[Handler, Depends(senior("start a round"))]
StopsRounds = Annotated[Handler, Depends(senior("stop a round"))]
REVIEWING = "approve or reject the improver's proposals"
ReviewsProposals = Annotated[Handler, Depends(senior(REVIEWING))]


# Finding things.


def proposal_in(db: Connection, row: RowMapping, proposal_id: str) -> RowMapping:
    """Return one of a round's proposals, or raise a 404."""
    query = select(proposals).where(
        proposals.c.proposal_id == proposal_id,
        proposals.c.round_id == row["round_id"],
    )
    proposal = db.execute(query).mappings().first()
    if proposal is None:
        raise HTTPException(
            404, f"Proposal {proposal_id} not found in round {row['number']}"
        )
    return proposal


def the_one_waiting(db: Connection, row: RowMapping, proposal_id: str) -> RowMapping:
    """Return a round's proposal if it is the one waiting for a handler, or raise a
    404 or a 409, so a review never lands on a proposal the handler didn't see."""
    proposal = proposal_in(db, row, proposal_id)
    if proposal["review"] is not None:
        raise HTTPException(
            409,
            NOT_WAITING.format(proposal_id=proposal_id, review=proposal["review"]),
        )
    return proposal


def current_recipe(db: Connection) -> RowMapping:
    """Return the recipe the next round follows: the newest approved."""
    query = select(recipes).order_by(recipes.c.number.desc()).limit(1)
    return db.execute(query).mappings().one()


def round_recipe(db: Connection, round_id: str) -> RowMapping | None:
    """Return the recipe a round made from an approved proposal, if any."""
    query = select(recipes).where(recipes.c.round_id == round_id)
    return db.execute(query).mappings().first()


def proposer(row: RowMapping) -> str:
    """Who a round's proposals are recorded as proposed by."""
    return f"Round {row['number']}"


def is_allowed(db: Connection, model: str, reasoning_effort: str) -> bool:
    """Say whether the claim agent may use a model at a reasoning effort."""
    return any(
        allowed.model == model and reasoning_effort in allowed.reasoning_efforts
        for allowed in allowed_models(db)
    )


def refuse_a_model_not_allowed(db: Connection, change: ChangeProposalRequest) -> None:
    """Raise a 422 for a change to a model outside the models allowed."""
    if not is_allowed(db, change.model, change.reasoning_effort):
        raise HTTPException(
            422,
            f"{change.model} at {change.reasoning_effort} isn't allowed. "
            "Choose from the models allowed.",
        )


def refuse_while_a_round_is_open(db: Connection) -> None:
    """Raise a 409 naming the round that's open, if there is one."""
    query = select(rounds.c.number).where(rounds.c.status == RoundStatus.OPEN)
    number = db.execute(query).scalar_one_or_none()
    if number is not None:
        raise HTTPException(409, ROUND_OPEN.format(number=number))


def refuse_while_waiting(db: Connection, row: RowMapping) -> None:
    """Raise a 409 while one of the round's proposals waits for a handler."""
    if waiting_proposal(db, row["round_id"]):
        raise HTTPException(
            409, f"Round {row['number']} has a proposal waiting for a handler"
        )


def first_evaluations(db: Connection, version: int) -> list[EvaluationSet]:
    """Return the sets of the evaluations a version still needs before a round can
    improve on it: one on the evaluation set and two on the held-out set, less the
    whole-set evaluations rounds have finished on it."""
    have = {s: len(runs_) for s, runs_ in round_evaluations(db, version).items()}
    needed = []
    for evaluation_set in EVALUATIONS:
        if have[evaluation_set]:
            have[evaluation_set] -= 1
        else:
            needed.append(evaluation_set)
    return needed


# Shapes.


def to_proposal(row: RowMapping) -> Proposal:
    """A proposal as the agent and the improver read it."""
    proposed: dict[str, Any] = row["proposal"]
    return Proposal(
        **{field: row[field] for field in Proposal.model_fields if field in row},
        reason=proposed["reason"],
        instructions=proposed.get("instructions"),
        model=proposed.get("model"),
        reasoning_effort=proposed.get("reasoning_effort"),
        recipe=proposed.get("recipe"),
    )


def for_the_agent(db: Connection, row: RowMapping) -> RoundForTheAgent:
    """A round as the agent works it, with the improver's instructions around the
    round's recipe."""
    recipe = db.execute(
        select(recipes.c.recipe).where(recipes.c.number == row["recipe"])
    ).scalar_one()
    improver = (INSTRUCTIONS / "improver.md").read_text(encoding="utf-8")
    return RoundForTheAgent(
        **row,
        instructions=f"{improver}\n{recipe}",
        models_allowed=allowed_models(db),
        version_evaluations=EVALUATIONS,
    )


def measures_or_none(stored: dict[str, Any] | None) -> Measures | None:
    return Measures(**stored) if stored else None


# What the improver reads.


def yes_or_no(chance: float) -> Literal["yes", "no"]:
    """A check as the improver reads it: yes from even odds."""
    return "yes" if chance >= YES_FROM else "no"


def beside_handler(claim: ScoredClaim, handler: RowMapping) -> ClaimBesideHandler:
    """An evaluation's copy as the improver reads it: under its original's id, the
    agent's answer beside the handler's, and the judge's grade."""
    grade = claim.grade
    return ClaimBesideHandler(
        claim_id=claim.copy_of,
        summary=claim.summary,
        agent=AgentAnswer(
            decision=claim.decision,
            payout=claim.payout,
            reason=claim.reason,
            section=claim.section,
        ),
        handler=HandlerAnswer(
            decision=handler["decision"],
            payout=handler["payout"],
            reason=handler["reason"],
            reference=handler["reference"],
        ),
        judge=grade
        and JudgeAnswer(
            grade=grade.score,
            letter=grade.letter,
            same_grounds=yes_or_no(grade.same_grounds),
            same_section=yes_or_no(grade.same_section),
        ),
    )


def evaluation_set_results(
    db: Connection, version: int, expected: Expected
) -> EvaluationSetResults:
    """From a version's latest round evaluation on the evaluation set, the claims it
    got wrong and the right ones the judge graded lowest, with the handlers'
    reasons. Nothing from the held-out set."""
    latest = round_evaluations(db, version)[EvaluationSet.EVALUATION][-1:]
    if not latest:
        return EvaluationSetResults(wrong=[], explained_least_well=[])
    claims = score(db, latest[0], expected).claims
    handlers_ = handler_reasons(db)
    right = [c for c in claims if c.right]
    weakest = sorted(right, key=lambda c: c.grade.score if c.grade else 3)
    return EvaluationSetResults(
        wrong=[beside_handler(c, handlers_[c.copy_of]) for c in claims if not c.right],
        explained_least_well=[
            beside_handler(c, handlers_[c.copy_of])
            for c in weakest[:EXPLAINED_LEAST_WELL]
        ],
    )


def handler_reasons(db: Connection) -> dict[str, RowMapping]:
    """The handlers' decisions on the evaluation set, with their reasons."""
    query = select(handler_decisions).where(
        handler_decisions.c.evaluation_set == EvaluationSet.EVALUATION
    )
    return {row["claim_id"]: row for row in db.execute(query).mappings()}


def earlier_round(db: Connection, row: RowMapping) -> EarlierRound:
    """What an earlier round tried and how it came out."""
    version = tried_version(db, row["round_id"])
    tried = dict(version) if version else {}
    return EarlierRound(
        round=row["number"],
        recipe_version=row["recipe"],
        version=tried.get("number"),
        model=tried.get("model"),
        reasoning_effort=tried.get("reasoning_effort"),
        reason=tried.get("reason"),
        held_out_before=measures_or_none(row["held_out_before"]),
        held_out_after=measures_or_none(row["held_out_after"]),
        verdict=tried.get("verdict"),
        why=tried.get("verdict_reason"),
    )


def improver_view(db: Connection, row: RowMapping) -> ImproverView:
    """What the improver reads in a round, as the lab's read_results gives it."""
    current = version_row(db, current_version_number(db))
    expected = expected_answers(db)
    settings = settings_number(db, row["settings"])
    earlier = select(rounds).where(rounds.c.number < row["number"])
    return ImproverView(
        current_version=ClaimAgentVersion(**current),
        scores=version_scores(db, current["number"], expected),
        evaluation_set=evaluation_set_results(db, current["number"], expected),
        earlier_rounds=[
            earlier_round(db, earlier_row)
            for earlier_row in db.execute(earlier.order_by(rounds.c.number)).mappings()
        ],
        objectives_on_the_held_out_set=settings.objectives,
        noise=settings.noise,
        tolerance=settings.tolerance,
        rule=verdict.RULE,
        spending=spending_of(db, row),
        models_allowed=allowed_models(db),
    )


# What the Improvement page shows.


def reviews_in(
    db: Connection, round_ids: list[str]
) -> dict[str, list[RoundReviewView]]:
    """Who approved or rejected each of the rounds' proposals, and when, by round,
    in one query for all the rounds."""
    query = (
        select(proposals)
        .where(proposals.c.round_id.in_(round_ids), proposals.c.review.is_not(None))
        .order_by(proposals.c.reviewed_at)
    )
    reviews: dict[str, list[RoundReviewView]] = {round_id: [] for round_id in round_ids}
    for row in db.execute(query).mappings():
        reviews[row["round_id"]].append(RoundReviewView(**row))
    return reviews


def summaries_of(db: Connection, rows: list[RowMapping]) -> list[RoundSummary]:
    """Rounds: where each has got to, what it tried, how that came out, who
    approved or rejected what, and what it cost, in a few queries for them all."""
    round_ids = [row["round_id"] for row in rows]
    tried = tried_versions(db, round_ids)
    spent = spending.spent_in(db, round_ids)
    reviews = reviews_in(db, round_ids)
    limits = spending_limits(db, round_ids)
    measures = {"held_out_before", "held_out_after"}
    summaries = []
    for row in rows:
        version = tried.get(row["round_id"])
        stage, progress = (
            stage_of(db, row) if row["status"] == RoundStatus.OPEN else (None, None)
        )
        summaries.append(
            RoundSummary(
                **{key: value for key, value in row.items() if key not in measures},
                stage=stage,
                progress=progress,
                spending_limit=limits[row["round_id"]],
                cost=spent[row["round_id"]],
                version=version["number"] if version else None,
                model=version["model"] if version else None,
                reasoning_effort=version["reasoning_effort"] if version else None,
                reason=version["reason"] if version else None,
                verdict=version["verdict"] if version else None,
                verdict_reason=version["verdict_reason"] if version else None,
                held_out_before=measures_or_none(row["held_out_before"]),
                held_out_after=measures_or_none(row["held_out_after"]),
                reviews=reviews[row["round_id"]],
            )
        )
    return summaries


def summary_of(db: Connection, row: RowMapping) -> RoundSummary:
    """A round, as summaries_of gives it."""
    return summaries_of(db, [row])[0]


def waiting_view(db: Connection, row: RowMapping) -> WaitingProposal | None:
    """The proposal waiting for a handler while the round is open, with what it
    changes from the current version or recipe."""
    waiting = waiting_proposal(db, row["round_id"])
    if waiting is None or row["status"] != RoundStatus.OPEN:
        return None
    proposal = to_proposal(waiting)
    if proposal.kind == ProposalKind.RECIPE:
        return WaitingProposal(
            **proposal.model_dump(),
            diff=diff(current_recipe(db)["recipe"], proposal.recipe or ""),
            model_before=None,
            reasoning_effort_before=None,
            model_after=None,
            reasoning_effort_after=None,
        )
    current = version_row(db, current_version_number(db))
    return WaitingProposal(
        **proposal.model_dump(),
        diff=diff(current["instructions"], proposal.instructions or ""),
        model_before=current["model"],
        reasoning_effort_before=current["reasoning_effort"],
        model_after=proposal.model,
        reasoning_effort_after=proposal.reasoning_effort,
    )


def view_of(
    db: Connection, row: RowMapping, summary: RoundSummary, expected: Expected
) -> RoundView:
    """A round in full: its summary, the proposal waiting and its evaluations."""
    query = (
        select(runs).where(runs.c.round_id == row["round_id"]).order_by(runs.c.number)
    )
    scored = score_all(db, list(db.execute(query).mappings()), expected)
    return RoundView(
        **summary.model_dump(),
        waiting=waiting_view(db, row),
        evaluations=[Evaluation(**s.model_dump(exclude={"claims"})) for s in scored],
    )


def version_point(row: RowMapping, scores: VersionScores) -> VersionPoint:
    """A version's held-out accuracy and grade, for the chart."""
    held_out = scores.held_out
    return VersionPoint(
        number=row["number"],
        verdict=row["verdict"] if row["round_id"] else None,
        accuracy=held_out.accuracy if held_out else None,
        grade=held_out.grade if held_out else None,
    )


def version_points(
    db: Connection, expected: Expected
) -> tuple[VersionPoint, list[VersionPoint]]:
    """Version 1's held-out accuracy and grade, and each tried version's, for the
    chart."""
    first = version_row(db, FIRST_VERSION["number"])
    query = select(versions).where(versions.c.round_id.is_not(None))
    tried = list(db.execute(query.order_by(versions.c.number)).mappings())
    numbers = [first["number"], *(row["number"] for row in tried)]
    scores = scores_of_versions(db, numbers, expected)
    return version_point(first, scores[first["number"]]), [
        version_point(row, scores[row["number"]]) for row in tried
    ]


def recipes_newest_first(db: Connection) -> list[RowMapping]:
    """Return every version of the recipe, newest first."""
    query = select(recipes).order_by(recipes.c.number.desc())
    return list(db.execute(query).mappings())


def recipe_changes(all_recipes: list[RowMapping]) -> dict[int, Diff | None]:
    """What each recipe changed from the one before it, or none for the first."""
    texts = {row["number"]: row["recipe"] for row in all_recipes}
    return {
        number: diff(texts[number - 1], text) if number - 1 in texts else None
        for number, text in texts.items()
    }


def recipe_summary(
    row: RowMapping, current: int, changes: Diff | None
) -> RecipeSummary:
    """A recipe with how many lines it changed from the one before."""
    return RecipeSummary(
        **row,
        current=row["number"] == current,
        lines_added=changes.added if changes else 0,
        lines_removed=changes.removed if changes else 0,
    )


def recipe_summaries(db: Connection) -> list[RecipeSummary]:
    """Every version of the recipe, newest first, with what each changed."""
    all_recipes = recipes_newest_first(db)
    changes = recipe_changes(all_recipes)
    current = current_recipe(db)["number"]
    return [recipe_summary(row, current, changes[row["number"]]) for row in all_recipes]


def improvement_page(db: Connection) -> Improvement:
    """Everything the Improvement page shows, in a few queries however many rounds
    there have been, since the page asks for it every two seconds."""
    expected = expected_answers(db)
    all_rounds = list(
        db.execute(select(rounds).order_by(rounds.c.number.desc())).mappings()
    )
    summaries = summaries_of(db, all_rounds)
    first_version, versions_tried = version_points(db, expected)
    return Improvement(
        round=view_of(db, all_rounds[0], summaries[0], expected)
        if all_rounds
        else None,
        rounds=summaries,
        first_version=first_version,
        versions_tried=versions_tried,
        recipes=recipe_summaries(db),
    )


# The agent's operations on a round.


def new_round(db: Connection, handler: Handler) -> RowMapping:
    """Record a new round for a handler, to the settings, recipe and version in
    force, and return its row."""
    version = current_version_number(db)
    model, reasoning_effort = model_or_free(*IMPROVER_MODEL)
    round_id = str(uuid.uuid4())
    db.execute(
        insert(rounds).values(
            round_id=round_id,
            thread_id=str(uuid.uuid4()),
            status=RoundStatus.OPEN,
            settings=current_settings(db).number,
            recipe=current_recipe(db)["number"],
            starting_version=version,
            first_evaluations=first_evaluations(db, version),
            improver_model=model,
            improver_reasoning_effort=reasoning_effort,
            started_by=handler.name,
            started_at=now(),
            heard_at=now(),
        )
    )
    return round_row(db, round_id)


def record_the_review(
    db: Connection, row: RowMapping, proposal: str, by: Handler, rejection: str | None
) -> None:
    """Record a handler's review of the proposal waiting: an approval, or a
    rejection with its reason. It counts as hearing of the round's work."""
    review = Review.APPROVED if rejection is None else Review.REJECTED
    db.execute(
        update(proposals)
        .where(proposals.c.proposal_id == proposal)
        .values(
            review=review,
            reviewed_by=by.name,
            reviewed_at=now(),
            rejection_reason=rejection,
        )
    )
    db.execute(
        update(rounds)
        .where(rounds.c.round_id == row["round_id"])
        .values(heard_at=now())
    )


def clear_the_review(db: Connection, proposal_id: str) -> None:
    """Clear a review the agent didn't take, so the proposal waits for a handler
    again."""
    db.execute(
        update(proposals)
        .where(proposals.c.proposal_id == proposal_id)
        .values(review=None, reviewed_by=None, reviewed_at=None, rejection_reason=None)
    )


def carry_on_after(db: Connection, row: RowMapping, proposal_id: str) -> None:
    """Ask the agent to carry the round on after a review, which is cleared when
    the agent didn't take it."""
    commit_and_ask(
        db,
        partial(agent_service.carry_round_on, row["round_id"], proposal_id),
        lambda reason: clear_the_review(db, proposal_id),
    )


@router.get("/api/rounds/{round_id}", operation_id="get_round", dependencies=[AgentKey])
def get_round(round_id: str, db: Database) -> RoundForTheAgent:
    """Get a round as the agent works it, with the improver's model."""
    return for_the_agent(db, round_row(db, round_id))


@router.get(
    "/api/rounds/{round_id}/results",
    operation_id="get_improver_view",
    dependencies=[AgentKey],
)
def get_improver_view(round_id: str, db: Database) -> ImproverView:
    """Get what the improver reads in a round: no held-out claim, only scores."""
    return improver_view(db, round_row(db, round_id))


@router.get(
    "/api/rounds/{round_id}/proposals/{proposal_id}",
    operation_id="get_proposal",
    dependencies=[AgentKey],
)
def get_proposal(round_id: str, proposal_id: str, db: Database) -> Proposal:
    """Get one of a round's proposals, with its review and the reason for it."""
    return to_proposal(proposal_in(db, round_row(db, round_id), proposal_id))


@router.post(
    "/api/rounds/{round_id}/heartbeat",
    operation_id="record_round_heartbeat",
    dependencies=[AgentKey],
)
def record_round_heartbeat(round_id: str, db: Database) -> RoundForTheAgent:
    """Record that the agent is still working a round, and its evaluation."""
    round_row(db, round_id)
    db.execute(
        update(rounds).where(rounds.c.round_id == round_id).values(heard_at=now())
    )
    return for_the_agent(db, round_row(db, round_id))


@router.post(
    "/api/rounds/{round_id}/failure", operation_id="fail_round", dependencies=[AgentKey]
)
def fail_round(
    round_id: str, request: FailureRequest, db: Database
) -> RoundForTheAgent:
    """Stop a round whose work failed, with its running evaluation, if it's open."""
    stop(db, round_row(db, round_id), None, request.reason)
    return for_the_agent(db, round_row(db, round_id))


def propose(
    db: Connection, row: RowMapping, kind: ProposalKind, proposed: dict[str, Any]
) -> Proposal:
    """Record a proposal from the improver, waiting for a handler."""
    refuse_while_waiting(db, row)
    proposal_id = str(uuid.uuid4())
    db.execute(
        insert(proposals).values(
            proposal_id=proposal_id,
            round_id=row["round_id"],
            kind=kind,
            proposal=proposed,
            proposed_at=now(),
        )
    )
    return to_proposal(proposal_in(db, row, proposal_id))


@router.post(
    "/api/rounds/{round_id}/proposals/change",
    operation_id="record_change_proposal",
    dependencies=[AgentKey],
)
def record_change_proposal(
    round_id: str, request: ChangeProposalRequest, db: Database
) -> Proposal:
    """Record the improver's proposed change, which changes nothing until approved."""
    row = open_round(db, round_id)
    tried = tried_version(db, round_id)
    if tried:
        raise HTTPException(
            409, f"Round {row['number']} has already tried version {tried['number']}"
        )
    if has_approved(db, row, ProposalKind.CHANGE):
        raise HTTPException(409, f"Round {row['number']} has a change approved")
    refuse_a_model_not_allowed(db, request)
    return propose(db, row, ProposalKind.CHANGE, request.model_dump())


@router.post(
    "/api/rounds/{round_id}/proposals/recipe",
    operation_id="record_recipe_proposal",
    dependencies=[AgentKey],
)
def record_recipe_proposal(
    round_id: str, request: RecipeProposalRequest, db: Database
) -> Proposal:
    """Record the improver's proposed recipe, which changes nothing until approved."""
    row = open_round(db, round_id)
    if round_recipe(db, round_id):
        raise HTTPException(409, f"Round {row['number']} has already made a recipe")
    return propose(db, row, ProposalKind.RECIPE, request.model_dump())


def approved_query(row: RowMapping, kind: ProposalKind):
    return select(proposals).where(
        proposals.c.round_id == row["round_id"],
        proposals.c.kind == kind,
        proposals.c.review == Review.APPROVED,
    )


def has_approved(db: Connection, row: RowMapping, kind: ProposalKind) -> bool:
    return db.execute(approved_query(row, kind)).first() is not None


def approved(db: Connection, row: RowMapping, kind: ProposalKind) -> RowMapping:
    """Return the round's approved proposal of a kind, or raise a 409. A round
    approves at most one of each."""
    proposal = db.execute(approved_query(row, kind)).mappings().first()
    if proposal is None:
        raise HTTPException(
            409, f"No {kind} has been approved in round {row['number']}"
        )
    return proposal


@router.post(
    "/api/rounds/{round_id}/version",
    operation_id="create_version",
    dependencies=[AgentKey],
)
def create_version(round_id: str, db: Database) -> NewNumber:
    """Make the approved change a version under test; a repeat returns it."""
    row = open_round(db, round_id)
    tried = tried_version(db, round_id)
    if tried:
        return NewNumber(number=tried["number"])
    proposal = approved(db, row, ProposalKind.CHANGE)
    change = ChangeProposalRequest(**proposal["proposal"])
    refuse_a_model_not_allowed(db, change)
    number = db.execute(select(func.max(versions.c.number))).scalar_one() + 1
    db.execute(
        insert(versions).values(
            number=number,
            **change.model_dump(),
            proposed_by=proposer(row),
            based_on=current_version_number(db),
            round_id=round_id,
            approved_by=proposal["reviewed_by"],
            approved_at=proposal["reviewed_at"],
            created_at=now(),
        )
    )
    return NewNumber(number=number)


@router.post(
    "/api/rounds/{round_id}/recipe",
    operation_id="create_recipe",
    dependencies=[AgentKey],
)
def create_recipe(round_id: str, db: Database) -> NewNumber:
    """Make the approved recipe the one the next round follows; a repeat returns it."""
    row = open_round(db, round_id)
    made = round_recipe(db, round_id)
    if made:
        return NewNumber(number=made["number"])
    proposal = approved(db, row, ProposalKind.RECIPE)
    recipe = RecipeProposalRequest(**proposal["proposal"])
    number = current_recipe(db)["number"] + 1
    db.execute(
        insert(recipes).values(
            number=number,
            **recipe.model_dump(),
            proposed_by=proposer(row),
            round_id=round_id,
            approved_by=proposal["reviewed_by"],
            approved_at=proposal["reviewed_at"],
            created_at=now(),
        )
    )
    return NewNumber(number=number)


def decide(
    db: Connection,
    row: RowMapping,
    version: RowMapping,
    new: Measures | None,
    old: Measures | None,
) -> verdict.Decided:
    """Keep or roll back a round's version by the rule, from its held-out scores
    against the current version's, to the round's settings."""
    evaluations = evaluations_of(db, row["round_id"], version["number"])
    if any(run["status"] == RunStatus.STOPPED for run in evaluations):
        return verdict.Decided(Verdict.ROLLED_BACK, verdict.EVALUATIONS_STOPPED)
    if finished_of(evaluations) < len(EVALUATIONS):
        return verdict.Decided(Verdict.ROLLED_BACK, verdict.CANT_AFFORD)
    settings = settings_number(db, row["settings"])
    return verdict.keep_or_roll_back(new, old, settings)


@router.post(
    "/api/rounds/{round_id}/verdict",
    operation_id="record_verdict",
    dependencies=[AgentKey],
)
def record_verdict(round_id: str, db: Database) -> VerdictResult:
    """Keep or roll back the round's version under test by the business's rule."""
    row = open_round(db, round_id)
    version = tried_version(db, round_id)
    if version is None or version["verdict"] is not None:
        raise HTTPException(409, f"Round {row['number']} has no version under test")
    expected = expected_answers(db)
    before = version_scores(db, current_version_number(db), expected).held_out
    tried = version_scores(db, version["number"], expected)
    decided = decide(db, row, version, tried.held_out, before)
    db.execute(
        update(versions)
        .where(versions.c.number == version["number"])
        .values(verdict=decided.verdict, verdict_reason=decided.reason)
    )
    db.execute(
        update(rounds)
        .where(rounds.c.round_id == round_id)
        .values(
            held_out_before=before and before.model_dump(),
            held_out_after=tried.held_out and tried.held_out.model_dump(),
        )
    )
    current = current_version_number(db)
    kept = "Kept" if decided.verdict == Verdict.KEPT else "Rolled back"
    return VerdictResult(
        version=version["number"],
        verdict=decided.verdict,
        reason=decided.reason,
        current_version=current,
        summary=f"{kept} version {version['number']}: {decided.reason}. "
        f"Version {current} is now the current version.",
        scores=VerdictScores(
            held_out_before=before,
            held_out_after=tried.held_out,
            evaluation_after=tried.evaluation,
        ),
    )


@router.post(
    "/api/rounds/{round_id}/model-calls",
    operation_id="record_improver_call",
    dependencies=[AgentKey],
)
def record_improver_call(
    round_id: str, request: ImproverCallRequest, db: Database
) -> Spending:
    """Record one of the improver's model calls, and say what's left to spend."""
    row = open_round(db, round_id)
    db.execute(
        insert(improver_calls).values(
            round_id=round_id, **request.model_dump(), created_at=now()
        )
    )
    return spending_of(db, row)


@router.post(
    "/api/rounds/{round_id}/finish",
    operation_id="finish_round",
    dependencies=[AgentKey],
)
def finish_round(round_id: str, db: Database) -> RoundForTheAgent:
    """Finish an open round with nothing waiting for a handler."""
    row = open_round(db, round_id)
    refuse_while_waiting(db, row)
    version = tried_version(db, round_id)
    if version and version["verdict"] is None:
        roll_back(db, version["number"], verdict.NOT_EVALUATED)
    db.execute(
        update(rounds)
        .where(rounds.c.round_id == round_id)
        .values(status=RoundStatus.FINISHED, finished_at=now())
    )
    return for_the_agent(db, round_row(db, round_id))


# The dashboard's operations.


@router.get(
    "/api/improvement", operation_id="get_improvement", dependencies=[SignedInHandler]
)
def get_improvement(db: Database) -> Improvement:
    """Get the open or newest round in full, every round, and the recipe's versions."""
    return improvement_page(db)


@router.get(
    "/api/improvement/recipes/{number}",
    operation_id="get_recipe",
    dependencies=[SignedInHandler],
)
def get_recipe(number: int, db: Database) -> RecipeDetails:
    """Get one version of the improver's recipe, with its diff from the one before."""
    all_recipes = recipes_newest_first(db)
    row = next((r for r in all_recipes if r["number"] == number), None)
    if row is None:
        raise HTTPException(404, f"Recipe {number} not found")
    changes = recipe_changes(all_recipes)[number]
    return RecipeDetails(
        **recipe_summary(row, current_recipe(db)["number"], changes).model_dump(),
        recipe=row["recipe"],
        diff=changes,
    )


@router.post("/api/improvement/rounds", operation_id="start_round", status_code=202)
def start_round(handler: StartsRounds, db: Database) -> Accepted:
    """Start a round of the improver, which the agent works."""
    clear_the_way(db)
    refuse_while_a_round_is_open(db)
    row = new_round(db, handler)
    commit_and_ask(
        db,
        partial(agent_service.work_round, row["round_id"]),
        lambda reason: stop(db, row, None, reason),
    )
    return Accepted()


@router.post("/api/improvement/rounds/{round_id}/stop", operation_id="stop_round")
def stop_round(round_id: str, handler: StopsRounds, db: Database) -> RoundSummary:
    """Stop an open round; a version it hadn't given a verdict is rolled back."""
    row = open_round(db, round_id)
    if not stop(db, row, handler.name, f"Stopped by {handler.name}"):
        # It finished or stopped since it was read, so it says how it ended.
        open_round(db, round_id)
    return summary_of(db, round_row(db, round_id))


@router.post(
    "/api/improvement/rounds/{round_id}/proposals/{proposal_id}/approval",
    operation_id="approve_proposal",
    status_code=202,
)
def approve_proposal(
    round_id: str, proposal_id: str, handler: ReviewsProposals, db: Database
) -> Accepted:
    """Approve the proposal waiting, and have the agent carry the round on."""
    clear_the_way(db)
    row = open_round(db, round_id)
    the_one_waiting(db, row, proposal_id)
    record_the_review(db, row, proposal_id, handler, None)
    carry_on_after(db, row, proposal_id)
    return Accepted()


@router.post(
    "/api/improvement/rounds/{round_id}/proposals/{proposal_id}/rejection",
    operation_id="reject_proposal",
    status_code=202,
)
def reject_proposal(
    round_id: str,
    proposal_id: str,
    request: RejectionRequest,
    handler: ReviewsProposals,
    db: Database,
) -> Accepted:
    """Reject the proposal waiting, with the reason the improver reads."""
    clear_the_way(db)
    row = open_round(db, round_id)
    the_one_waiting(db, row, proposal_id)
    record_the_review(db, row, proposal_id, handler, request.reason)
    carry_on_after(db, row, proposal_id)
    return Accepted()
