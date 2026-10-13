"""The UnderCover backend."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException
from mangum import Mangum
from sqlalchemy import Connection, RowMapping, delete, insert, select, update

from backend import agent_api, agent_service, dashboard
from backend.calculation import (
    attempts_calculation,
    clear_calculation,
    keep_calculation,
)
from backend.configuration import router as configuration
from backend.database import (
    claim_view,
    claims,
    customers,
    decisions,
    engine,
    is_seeded,
    model_calls,
    now,
    payments,
    payout_rules,
    policies,
    seed,
    stamp,
    steps,
    work_times,
)
from backend.dependencies import (
    AgentKey,
    Database,
    HandlerOrAgent,
    SignedIn,
    SignedInHandler,
    senior,
)
from backend.documents import manual_version
from backend.improvement import router as improvement
from backend.lookups import CLAIM_NOT_FOUND, current_settings, run_row
from backend.models import (
    Claim,
    ClaimSummary,
    DecisionKind,
    DecisionRequest,
    FailureRequest,
    Handler,
    HoldRequest,
    ModelCall,
    ModelCallRequest,
    NewStep,
    PaymentRequest,
    Payout,
    PayoutRequest,
    Plans,
    Policy,
    PreviousClaim,
    SendBackRequest,
    StartRequest,
    Status,
    Step,
    StepRequest,
    TakeRequest,
    WorkTime,
    WorkTimeRequest,
)
from backend.money import dollars
from backend.payout import needs_sign_off, work_out_payout
from backend.records import check_calculation, check_request
from backend.round_state import round_row, why_no_claim_starts
from backend.runs import router as runs
from backend.sent_back import keep, sent_back_of
from backend.views import to_claim, to_summary

ATTEMPTS = 2
NOT_APPROVED = "Claim {claim_id} has not been approved"
ALREADY_PAID = "Claim {claim_id} has already been paid"
NOT_STARTED = "Claim {claim_id} has not been started"
NOT_IN_PROGRESS = "Claim {claim_id} is not in progress"
ALREADY_DECIDED = "Claim {claim_id} has already been decided"
NOT_WAITING = "Claim {claim_id} is not waiting"
NOT_WAITING_FOR_SIGN_OFF = "Claim {claim_id} is not waiting for sign-off"
NOT_SENT_BACK = "Claim {claim_id} isn't sent back"
A_COPY = "Claim {claim_id} is a copy in an evaluation and can't be {answered}"

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Seed the database on startup if it has no tables yet."""
    if not is_seeded(engine()):
        seed(engine())
    yield


app = FastAPI(title="UnderCover", lifespan=lifespan)
app.include_router(runs)
app.include_router(configuration)
app.include_router(improvement)

SignsOffOverTheLimit = Annotated[Handler, Depends(senior("sign this off"))]
SendsBack = Annotated[Handler, Depends(senior("send this back"))]


def approval_limit(db: Connection) -> float:
    """Return the largest payout that can be paid without a handler's sign-off, as
    the settings in force have it."""
    return current_settings(db).approval_limit


def plans(db: Connection) -> Plans:
    """Return the plans and add-ons, and the benefits the deductible applies to."""
    return Plans(**db.execute(select(payout_rules.c.plans)).scalar_one())


def find_claim(db: Connection, claim_id: str) -> RowMapping:
    """Return one claim's row, or raise a 404."""
    query = claim_view.where(claims.c.claim_id == claim_id)
    row = db.execute(query).mappings().first()
    if row is None:
        raise HTTPException(404, CLAIM_NOT_FOUND.format(claim_id=claim_id))
    return row


def claim_in_full(db: Connection, claim_id: str) -> Claim:
    """Return one claim in full, as the API shows it, or raise a 404."""
    return to_claim(find_claim(db, claim_id), sent_back_of(db, claim_id))


def find_policy(db: Connection, policy_id: str) -> Policy:
    """Return one policy, or raise a 404."""
    query = select(policies.c.record).where(policies.c.policy_id == policy_id)
    record = db.execute(query).scalar_one_or_none()
    if record is None:
        raise HTTPException(404, f"Policy {policy_id} not found")
    return Policy(**record)


def over_the_limit(limit: float) -> str:
    """Say that a payout over a limit needs a handler's sign-off."""
    return f"A payout over {dollars(limit)} needs a handler's sign-off"


def record_payment(db: Connection, claim: RowMapping) -> None:
    """Pay an approved claim its payout."""
    db.execute(
        insert(payments).values(
            claim_id=claim["claim_id"], amount=claim["payout"], paid_at=now()
        )
    )


def set_status(db: Connection, claim_id: str, status: Status) -> None:
    """Move a claim to a new status."""
    db.execute(
        update(claims).where(claims.c.claim_id == claim_id).values(status=status)
    )


def move_claim(
    db: Connection, claim_id: str, old: Status, new: Status, **columns: Any
) -> bool:
    """Move a claim from one status to another, setting any other columns given, and
    say whether it moved: only the first of two requests at the same moment finds
    it in the old status."""
    moved = db.execute(
        update(claims)
        .where(claims.c.claim_id == claim_id, claims.c.status == old)
        .values(status=new, **columns)
    )
    return moved.rowcount == 1


def answer_held(
    db: Connection, claim_id: str, answer: Status, answered: str
) -> RowMapping:
    """Move a claim held for sign-off on with a handler's answer, and return its row
    as the move found it, with the decision that was held, or raise a 404, or a 409
    for an evaluation's copy, which nobody answers, or for a claim no longer
    waiting, as when another answer came first."""
    if find_claim(db, claim_id)["evaluation_id"] is not None:
        raise HTTPException(409, A_COPY.format(claim_id=claim_id, answered=answered))
    if not move_claim(db, claim_id, Status.WAITING_FOR_SIGN_OFF, answer):
        raise HTTPException(409, NOT_WAITING_FOR_SIGN_OFF.format(claim_id=claim_id))
    return find_claim(db, claim_id)


def record_send_back(db: Connection, claim: RowMapping, note: str, by: str) -> None:
    """Keep a held decision sent back with its note, clear it from the claim with
    its calculation, so nothing can pay it, and record the note as a step."""
    keep(db, claim, note, by)
    db.execute(delete(decisions).where(decisions.c.claim_id == claim["claim_id"]))
    clear_calculation(db, claim["claim_id"])
    step = NewStep(kind="sent_back", content=f"Sent back by {by}: {note}", sources=[])
    add_step(db, claim["claim_id"], claim["thread_id"], step)


def ask_to_resume(claim_id: str) -> None:
    """Ask the agent to resume a claim after a handler's answer, which stands
    whatever happens to the call: a failure is logged as a warning."""
    try:
        agent_service.resume_claim(claim_id)
    except Exception as error:  # the handler's answer stands whatever happens
        log.warning("%s wasn't resumed: %s", claim_id, error)


def started_thread(db: Connection, claim_id: str) -> str:
    """Return the thread of a claim that has been started, or raise a 404 or a 409."""
    thread_id = find_claim(db, claim_id)["thread_id"]
    if thread_id is None:
        raise HTTPException(409, NOT_STARTED.format(claim_id=claim_id))
    return thread_id


def refuse_a_round_that_cant_go_on(db: Connection, run_id: str) -> None:
    """Raise a 409 when an evaluation belongs to a round that was stopped or has
    spent its limit, so no new claim starts in it."""
    round_id = run_row(db, run_id)["round_id"]
    if round_id is None:
        return
    reason = why_no_claim_starts(db, round_row(db, round_id))
    if reason:
        raise HTTPException(409, reason)


def check_run(db: Connection, run_id: str | None) -> None:
    """Check that the run named, if any, exists, or raise a 404."""
    if run_id is not None:
        run_row(db, run_id)


def add_step(db: Connection, claim_id: str, thread_id: str, step: NewStep) -> Step:
    """Add one step of the agent's work to a claim."""
    query = (
        insert(steps)
        .values(
            claim_id=claim_id,
            thread_id=thread_id,
            **step.model_dump(),
            created_at=now(),
        )
        .returning(steps)
    )
    return Step(**db.execute(query).mappings().one())


@app.get("/api/health", operation_id="health")
def health() -> dict[str, str]:
    """Check that the backend is running."""
    return {"status": "ok"}


@app.get("/api/claims", operation_id="list_claims", dependencies=[HandlerOrAgent])
def list_claims(db: Database) -> list[ClaimSummary]:
    """List every claim in the queue, in id order, leaving out evaluations' copies."""
    query = claim_view.where(claims.c.evaluation_id.is_(None))
    rows = db.execute(query.order_by(claims.c.claim_id)).mappings()
    return [to_summary(row) for row in rows]


@app.get(
    "/api/claims/{claim_id}", operation_id="get_claim", dependencies=[HandlerOrAgent]
)
def get_claim(claim_id: str, db: Database) -> Claim:
    """Get one claim in full: the story, the items claimed and the documents."""
    return claim_in_full(db, claim_id)


@app.get(
    "/api/policies/{policy_id}",
    operation_id="get_policy",
    dependencies=[HandlerOrAgent],
)
def get_policy(policy_id: str, db: Database) -> Policy:
    """Get a policy: the plan, add-ons, purchase date, trip and travelers."""
    return find_policy(db, policy_id)


@app.get(
    "/api/customers/{customer_id}/claims",
    operation_id="get_claim_history",
    dependencies=[HandlerOrAgent],
)
def get_claim_history(customer_id: str, db: Database) -> list[PreviousClaim]:
    """Get a customer's earlier claims, with the outcome and the amount paid."""
    query = select(customers.c.record).where(customers.c.customer_id == customer_id)
    record = db.execute(query).scalar_one_or_none()
    if record is None:
        raise HTTPException(404, f"Customer {customer_id} not found")
    return [PreviousClaim(**claim) for claim in record["previous_claims"]]


@app.get(
    "/api/agent/openapi.json",
    operation_id="get_agent_api",
    dependencies=[HandlerOrAgent],
)
def get_agent_api() -> dict[str, Any]:
    """Get the OpenAPI document of the claim agent's own operations, for the Gateway."""
    return agent_api.document(app)


@app.get("/api/me", operation_id="get_signed_in_handler")
def get_signed_in_handler(handler: SignedIn) -> Handler:
    """Get the handler signed in, with what they may sign off."""
    return handler


@app.post(
    "/api/claims/{claim_id}/start", operation_id="start_claim", dependencies=[AgentKey]
)
def start_claim(claim_id: str, request: StartRequest, db: Database) -> Claim:
    """Start work on a waiting claim, which moves it to in progress, only once."""
    claim = find_claim(db, claim_id)
    if claim["status"] != Status.WAITING:
        raise HTTPException(409, NOT_WAITING.format(claim_id=claim_id))
    if claim["evaluation_id"]:
        refuse_a_round_that_cant_go_on(db, claim["evaluation_id"])
    started = move_claim(
        db,
        claim_id,
        Status.WAITING,
        Status.IN_PROGRESS,
        thread_id=request.thread_id,
        attempts=claims.c.attempts + 1,
        resume_heard_at=None,
    )
    if not started:
        raise HTTPException(409, NOT_WAITING.format(claim_id=claim_id))
    return claim_in_full(db, claim_id)


@app.post(
    "/api/claims/{claim_id}/steps", operation_id="record_step", dependencies=[AgentKey]
)
def record_step(claim_id: str, request: StepRequest, db: Database) -> Step:
    """Record one step of the agent's work on a claim."""
    thread_id = started_thread(db, claim_id)
    return add_step(db, claim_id, thread_id, NewStep(**request.model_dump()))


@app.post(
    "/api/claims/{claim_id}/model-calls",
    operation_id="record_model_call",
    dependencies=[AgentKey],
)
def record_model_call(
    claim_id: str, request: ModelCallRequest, db: Database
) -> ModelCall:
    """Record the tokens and the cost of one model call on a started claim."""
    thread_id = started_thread(db, claim_id)
    check_run(db, request.run_id)
    query = (
        insert(model_calls)
        .values(
            claim_id=claim_id,
            thread_id=thread_id,
            **request.model_dump(),
            created_at=now(),
        )
        .returning(model_calls)
    )
    return ModelCall(**db.execute(query).mappings().one())


@app.post(
    "/api/claims/{claim_id}/work-times",
    operation_id="record_work_time",
    dependencies=[AgentKey],
)
def record_work_time(claim_id: str, request: WorkTimeRequest, db: Database) -> WorkTime:
    """Record one spell of the agent's work on a started claim, ending now."""
    thread_id = started_thread(db, claim_id)
    check_run(db, request.run_id)
    started = datetime.now(UTC) - timedelta(seconds=request.seconds)
    query = (
        insert(work_times)
        .values(
            claim_id=claim_id,
            thread_id=thread_id,
            run_id=request.run_id,
            started_at=stamp(started),
            seconds=request.seconds,
        )
        .returning(work_times)
    )
    return WorkTime(**db.execute(query).mappings().one())


@app.get(
    "/api/claims/{claim_id}/steps",
    operation_id="list_steps",
    dependencies=[SignedInHandler],
)
def list_steps(claim_id: str, db: Database) -> list[Step]:
    """List the steps of the agent's work on a claim, in order."""
    find_claim(db, claim_id)
    query = select(steps).where(steps.c.claim_id == claim_id).order_by(steps.c.step_id)
    return [Step(**row) for row in db.execute(query).mappings()]


@app.post(
    "/api/claims/{claim_id}/decision",
    operation_id="record_decision",
    dependencies=[AgentKey],
)
def record_decision(claim_id: str, request: DecisionRequest, db: Database) -> Claim:
    """Record a claim's decision once, as section 14 asks; approvals await payment."""
    check_request(request)
    claim = find_claim(db, claim_id)
    payout = request.payout
    if claim["decision"] is not None:
        if (claim["decision"], claim["payout"]) == (request.decision, payout):
            return claim_in_full(db, claim_id)
        raise HTTPException(409, ALREADY_DECIDED.format(claim_id=claim_id))
    if claim["status"] != Status.IN_PROGRESS:
        raise HTTPException(409, NOT_IN_PROGRESS.format(claim_id=claim_id))
    calculation = None
    if request.decision == DecisionKind.APPROVE:
        calculation = check_calculation(payout, attempts_calculation(db, claim))
    limit = approval_limit(db)
    db.execute(
        insert(decisions).values(
            claim_id=claim_id,
            decision=request.decision,
            payout=payout,
            section=request.section,
            reason=request.reason,
            decided_by=request.decided_by,
            decided_at=now(),
            manual_version=manual_version(db),
            calculation=calculation and calculation.model_dump(),
            approval_limit=limit,
        )
    )
    if request.decision != DecisionKind.APPROVE:
        set_status(db, claim_id, Status.DECIDED)
    elif needs_sign_off(payout, limit):
        set_status(db, claim_id, Status.WAITING_FOR_SIGN_OFF)
    return claim_in_full(db, claim_id)


@app.post(
    "/api/claims/{claim_id}/payout",
    operation_id="calculate_payout",
    dependencies=[AgentKey],
)
def calculate_payout(claim_id: str, request: PayoutRequest, db: Database) -> Payout:
    """Work out and keep an approval's payout with UnderCover's payout rules."""
    claim = claim_in_full(db, claim_id)
    if claim.thread_id is None:
        raise HTTPException(409, NOT_STARTED.format(claim_id=claim_id))
    if claim.status != Status.IN_PROGRESS:
        raise HTTPException(409, NOT_IN_PROGRESS.format(claim_id=claim_id))
    policy = find_policy(db, claim.policy_id)
    payout = work_out_payout(policy, plans(db), request, approval_limit(db))
    keep_calculation(db, claim_id, claim.thread_id, payout)
    return payout


@app.post(
    "/api/claims/{claim_id}/payment", operation_id="pay_claim", dependencies=[AgentKey]
)
def pay_claim(claim_id: str, request: PaymentRequest, db: Database) -> Claim:
    """Pay an approved claim its payout once, unless it is over the limit."""
    amount = round(request.amount, 2)
    limit = approval_limit(db)
    if needs_sign_off(amount, limit):
        raise HTTPException(403, over_the_limit(limit))
    claim = find_claim(db, claim_id)
    if claim["decision"] != DecisionKind.APPROVE:
        raise HTTPException(409, NOT_APPROVED.format(claim_id=claim_id))
    if claim["paid_at"] is not None:
        if amount == claim["amount"]:
            return claim_in_full(db, claim_id)
        raise HTTPException(409, ALREADY_PAID.format(claim_id=claim_id))
    if claim["status"] == Status.WAITING_FOR_SIGN_OFF:
        raise HTTPException(403, over_the_limit(claim["approval_limit"]))
    if amount != claim["payout"]:
        raise HTTPException(
            422, f"The amount must be the approved payout of {dollars(claim['payout'])}"
        )
    record_payment(db, claim)
    set_status(db, claim_id, Status.DECIDED)
    return claim_in_full(db, claim_id)


@app.post(
    "/api/claims/{claim_id}/hold", operation_id="hold_payment", dependencies=[AgentKey]
)
def hold_payment(claim_id: str, request: HoldRequest, db: Database) -> Claim:
    """Hold an approval the Gateway refused to pay for a handler's sign-off."""
    claim = find_claim(db, claim_id)
    if claim["decision"] != DecisionKind.APPROVE:
        raise HTTPException(409, NOT_APPROVED.format(claim_id=claim_id))
    if claim["paid_at"] is not None:
        raise HTTPException(409, ALREADY_PAID.format(claim_id=claim_id))
    if claim["status"] == Status.WAITING_FOR_SIGN_OFF:
        return claim_in_full(db, claim_id)
    db.execute(
        update(decisions)
        .where(decisions.c.claim_id == claim_id)
        .values(gateway_refusal=request.reason)
    )
    set_status(db, claim_id, Status.WAITING_FOR_SIGN_OFF)
    return claim_in_full(db, claim_id)


@app.post("/api/claims/{claim_id}/sign-off", operation_id="sign_off_claim")
def sign_off_claim(claim_id: str, handler: SignsOffOverTheLimit, db: Database) -> Claim:
    """Sign off a held payout as the handler signed in, which pays it."""
    claim = answer_held(db, claim_id, Status.DECIDED, "signed off")
    db.execute(
        update(decisions)
        .where(decisions.c.claim_id == claim_id)
        .values(signed_off_by=handler.name, signed_off_at=now())
    )
    record_payment(db, claim)
    db.commit()
    ask_to_resume(claim_id)
    return claim_in_full(db, claim_id)


@app.post("/api/claims/{claim_id}/send-back", operation_id="send_back_claim")
def send_back_claim(
    claim_id: str, request: SendBackRequest, handler: SendsBack, db: Database
) -> Claim:
    """Send a held decision back to the agent with a note, as the handler signed in."""
    claim = answer_held(db, claim_id, Status.SENT_BACK, "sent back")
    record_send_back(db, claim, request.note, handler.name)
    db.commit()
    ask_to_resume(claim_id)
    return claim_in_full(db, claim_id)


@app.post(
    "/api/claims/{claim_id}/take", operation_id="take_claim", dependencies=[AgentKey]
)
def take_claim(claim_id: str, request: TakeRequest, db: Database) -> Claim:
    """Take a sent-back claim back into work, once, for a dispatch or a resume."""
    find_claim(db, claim_id)
    check_run(db, request.run_id)
    heard = now() if request.run_id is None else None
    sent_back, in_progress = Status.SENT_BACK, Status.IN_PROGRESS
    if not move_claim(db, claim_id, sent_back, in_progress, resume_heard_at=heard):
        raise HTTPException(409, NOT_SENT_BACK.format(claim_id=claim_id))
    return claim_in_full(db, claim_id)


@app.post(
    "/api/claims/{claim_id}/heartbeat",
    operation_id="record_claim_heartbeat",
    dependencies=[AgentKey],
)
def record_claim_heartbeat(claim_id: str, db: Database) -> Claim:
    """Record that a resume is still working on a claim."""
    heard = db.execute(
        update(claims)
        .where(claims.c.claim_id == claim_id)
        .values(resume_heard_at=now())
    )
    if heard.rowcount == 0:
        raise HTTPException(404, CLAIM_NOT_FOUND.format(claim_id=claim_id))
    return claim_in_full(db, claim_id)


@app.post(
    "/api/claims/{claim_id}/failure", operation_id="fail_claim", dependencies=[AgentKey]
)
def fail_claim(claim_id: str, request: FailureRequest, db: Database) -> Claim:
    """Put a failed claim back in the queue, or leave it for a handler after two."""
    claim = find_claim(db, claim_id)
    if claim["status"] != Status.IN_PROGRESS:
        raise HTTPException(409, NOT_IN_PROGRESS.format(claim_id=claim_id))
    if claim["decision"] is not None:
        raise HTTPException(409, ALREADY_DECIDED.format(claim_id=claim_id))
    error = NewStep(kind="error", content=request.reason, sources=[])
    add_step(db, claim_id, claim["thread_id"], error)
    status = (
        Status.LEFT_FOR_HANDLER if claim["attempts"] >= ATTEMPTS else Status.WAITING
    )
    set_status(db, claim_id, status)
    return claim_in_full(db, claim_id)


# After every route, so the dashboard's build only answers what no route does.
app.router.routes.append(dashboard.mount)

# AWS Lambda's entry point. Nothing seeds the database there.
handler = Mangum(app, lifespan="off")
