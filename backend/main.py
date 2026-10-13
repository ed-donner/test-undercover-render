"""The UnderCover backend."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Query
from mangum import Mangum
from sqlalchemy import Connection, RowMapping, insert, select, update

from backend import agent_api, dashboard
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
from backend.documents import search, sections, titles
from backend.improvement import router as improvement
from backend.lookups import CLAIM_NOT_FOUND, current_settings, run_row
from backend.models import (
    Claim,
    ClaimSummary,
    DecisionKind,
    DecisionRequest,
    DocumentName,
    FailureRequest,
    Handler,
    ModelCall,
    ModelCallRequest,
    PaymentRequest,
    Payout,
    PayoutRequest,
    Plans,
    Policy,
    PreviousClaim,
    Section,
    SectionMatch,
    StartRequest,
    Status,
    Step,
    StepRequest,
    WorkTime,
    WorkTimeRequest,
)
from backend.money import dollars
from backend.payout import needs_sign_off, work_out_payout
from backend.round_state import round_row, why_no_claim_starts
from backend.runs import router as runs
from backend.views import to_claim, to_summary

ATTEMPTS = 2


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
    """Pay an approved claim its payout, which decides it."""
    claim_id = claim["claim_id"]
    db.execute(
        insert(payments).values(
            claim_id=claim_id, amount=claim["payout"], paid_at=now()
        )
    )
    set_status(db, claim_id, Status.DECIDED)


def set_status(db: Connection, claim_id: str, status: Status) -> None:
    """Move a claim to a new status."""
    db.execute(
        update(claims).where(claims.c.claim_id == claim_id).values(status=status)
    )


def started_thread(db: Connection, claim_id: str) -> str:
    """Return the thread of a claim that has been started, or raise a 404 or a 409."""
    thread_id = find_claim(db, claim_id)["thread_id"]
    if thread_id is None:
        raise HTTPException(409, f"Claim {claim_id} has not been started")
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


def add_step(
    db: Connection, claim_id: str, thread_id: str, kind: str, content: str
) -> Step:
    """Add one step of the agent's work to a claim."""
    query = (
        insert(steps)
        .values(
            claim_id=claim_id,
            thread_id=thread_id,
            kind=kind,
            content=content,
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
    return to_claim(find_claim(db, claim_id))


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
    "/api/documents/search", operation_id="search_documents", dependencies=[AgentKey]
)
def search_documents(
    query: Annotated[str, Query(min_length=1)], db: Database
) -> list[SectionMatch]:
    """Find the sections of the wording and the manual that mention a word or phrase."""
    return search(db, query)


@app.get(
    "/api/documents/{document}/sections/{number}",
    operation_id="read_section",
    dependencies=[AgentKey],
)
def read_section(document: DocumentName, number: int, db: Database) -> Section:
    """Read one section of the policy wording or the claims manual in full."""
    for section in sections(db, document):
        if section.number == number:
            return section
    title = titles(db)[document].lower()
    raise HTTPException(404, f"Section {number} of the {title} not found")


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
    """Start work on a waiting claim, which moves it to in progress."""
    claim = find_claim(db, claim_id)
    if claim["status"] != Status.WAITING:
        raise HTTPException(409, f"Claim {claim_id} is not waiting")
    if claim["evaluation_id"]:
        refuse_a_round_that_cant_go_on(db, claim["evaluation_id"])
    db.execute(
        update(claims)
        .where(claims.c.claim_id == claim_id)
        .values(
            status=Status.IN_PROGRESS,
            thread_id=request.thread_id,
            attempts=claims.c.attempts + 1,
        )
    )
    return to_claim(find_claim(db, claim_id))


@app.post(
    "/api/claims/{claim_id}/steps", operation_id="record_step", dependencies=[AgentKey]
)
def record_step(claim_id: str, request: StepRequest, db: Database) -> Step:
    """Record one step of the agent's work on a claim."""
    thread_id = started_thread(db, claim_id)
    return add_step(db, claim_id, thread_id, request.kind, request.content)


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
    """Record a claim's decision once; an approval waits to be paid or signed off."""
    claim = find_claim(db, claim_id)
    payout = round(request.payout, 2)
    if claim["decision"] is not None:
        if (claim["decision"], claim["payout"]) == (request.decision, payout):
            return to_claim(claim)
        raise HTTPException(409, f"Claim {claim_id} has already been decided")
    if claim["status"] != Status.IN_PROGRESS:
        raise HTTPException(409, f"Claim {claim_id} is not in progress")
    limit = approval_limit(db)
    db.execute(
        insert(decisions).values(
            claim_id=claim_id,
            decision=request.decision,
            payout=payout,
            section=request.section,
            reason=request.reason,
            decided_at=now(),
            approval_limit=limit,
        )
    )
    if request.decision != DecisionKind.APPROVE:
        set_status(db, claim_id, Status.DECIDED)
    elif needs_sign_off(payout, limit):
        set_status(db, claim_id, Status.WAITING_FOR_SIGN_OFF)
    return to_claim(find_claim(db, claim_id))


@app.post(
    "/api/claims/{claim_id}/payout",
    operation_id="calculate_payout",
    dependencies=[AgentKey],
)
def calculate_payout(claim_id: str, request: PayoutRequest, db: Database) -> Payout:
    """Work out an approval's payout with UnderCover's payout rules; records nothing."""
    policy = find_policy(db, to_claim(find_claim(db, claim_id)).policy_id)
    return work_out_payout(policy, plans(db), request, approval_limit(db))


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
        raise HTTPException(409, f"Claim {claim_id} has not been approved")
    if claim["paid_at"] is not None:
        if amount == claim["amount"]:
            return to_claim(claim)
        raise HTTPException(409, f"Claim {claim_id} has already been paid")
    if claim["status"] == Status.WAITING_FOR_SIGN_OFF:
        raise HTTPException(403, over_the_limit(claim["approval_limit"]))
    if amount != claim["payout"]:
        raise HTTPException(
            422, f"The amount must be the approved payout of {dollars(claim['payout'])}"
        )
    record_payment(db, claim)
    return to_claim(find_claim(db, claim_id))


@app.post("/api/claims/{claim_id}/sign-off", operation_id="sign_off_claim")
def sign_off_claim(claim_id: str, handler: SignsOffOverTheLimit, db: Database) -> Claim:
    """Sign off a held payout as the handler signed in, which pays it."""
    claim = find_claim(db, claim_id)
    if claim["evaluation_id"] is not None:
        raise HTTPException(
            409, f"Claim {claim_id} is a copy in an evaluation and can't be signed off"
        )
    if claim["status"] != Status.WAITING_FOR_SIGN_OFF:
        raise HTTPException(409, f"Claim {claim_id} is not waiting for sign-off")
    db.execute(
        update(decisions)
        .where(decisions.c.claim_id == claim_id)
        .values(signed_off_by=handler.name, signed_off_at=now())
    )
    record_payment(db, claim)
    return to_claim(find_claim(db, claim_id))


@app.post(
    "/api/claims/{claim_id}/failure", operation_id="fail_claim", dependencies=[AgentKey]
)
def fail_claim(claim_id: str, request: FailureRequest, db: Database) -> Claim:
    """Put a failed claim back in the queue, or leave it for a handler after two."""
    claim = find_claim(db, claim_id)
    if claim["status"] != Status.IN_PROGRESS:
        raise HTTPException(409, f"Claim {claim_id} is not in progress")
    if claim["decision"] is not None:
        raise HTTPException(409, f"Claim {claim_id} has already been decided")
    add_step(db, claim_id, claim["thread_id"], "error", request.reason)
    status = (
        Status.LEFT_FOR_HANDLER if claim["attempts"] >= ATTEMPTS else Status.WAITING
    )
    set_status(db, claim_id, status)
    return to_claim(find_claim(db, claim_id))


# After every route, so the dashboard's build only answers what no route does.
app.router.routes.append(dashboard.mount)

# AWS Lambda's entry point. Nothing seeds the database there.
handler = Mangum(app, lifespan="off")
