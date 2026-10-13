"""The agent as an AgentCore app: one entrypoint takes the payload of each operation
the app asks for, checks what it must, answers at once, and hands the work to
agent/work.py on a thread of its own, which the AgentCore app's /ping reports as
busy until it ends. npm run dev serves it on port 8080, and runtime/main.py runs it
on AgentCore Runtime. Nothing happens as it's imported: it gets ready on its first
request."""

import random
import secrets
import threading
from collections.abc import Callable
from functools import partial
from typing import Annotated, Any, Literal

from bedrock_agentcore.runtime import BedrockAgentCoreApp, RequestContext
from bedrock_agentcore.runtime.models import AUTHORIZATION_HEADER
from langgraph.checkpoint.postgres import PostgresSaver
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError
from starlette.exceptions import HTTPException

from agent import api, identity, improver, improver_api
from agent.connection import Refused, api_key
from agent.console import describe, show_reports
from agent.handler_answer import SENT_BACK, answer_of
from agent.harness import (
    Pool,
    claim_graphs,
    open_checkpoint_pool,
    paused,
)
from agent.work import (
    Workers,
    carry_the_round_on,
    resume_telling_the_app,
    work_the_round,
    work_the_run,
)

ACCEPTED = {"accepted": True}
HEALTHY = {"healthy": True}
RUN_NOT_RUNNING = "Run {run_id} isn't running"
ROUND_NOT_OPEN = "Round {number} isn't open"
NO_REVIEW = "Proposal {proposal_id} has no review"
NOT_PAUSED = "Claim {claim_id} isn't paused for a handler"
NO_ANSWER = "Claim {claim_id} has no answer from a handler yet"
NOT_READY = "The agent couldn't get ready: {error}"
NEEDS_THE_KEY = "This needs the agent's API key"
UNKNOWN_OPERATION = "Unknown operation: {operation}"
NO_OPERATION = "The payload names no operation"
NOT_AN_OBJECT = "The payload isn't a JSON object"


app = BedrockAgentCoreApp()


class Operation(BaseModel):
    """A payload: it names its operation and carries every input, each of the right
    type, and no other."""

    model_config = ConfigDict(extra="forbid", strict=True)


class Health(Operation):
    operation: Literal["health"]


class WorkRun(Operation):
    operation: Literal["work_run"]
    run_id: str


class WorkRound(Operation):
    operation: Literal["work_round"]
    round_id: str


class CarryRoundOn(Operation):
    operation: Literal["carry_round_on"]
    round_id: str
    proposal_id: str


class ResumeClaim(Operation):
    operation: Literal["resume_claim"]
    claim_id: str


Payload = Annotated[
    Health | WorkRun | WorkRound | CarryRoundOn | ResumeClaim,
    Field(discriminator="operation"),
]
PAYLOADS: TypeAdapter[Payload] = TypeAdapter(Payload)


class Refusal(Exception):
    """The agent won't take the work, and why."""


def workers_on(pool: Pool) -> Workers:
    """The claim agents and the improver, on the process's checkpoint pool."""
    return Workers(
        partial(claim_graphs, pool=pool),
        improver.improver_model,
        PostgresSaver(pool),
    )


def get_ready() -> Workers:
    """Get ready to work. On Runtime, reseed the random numbers, which every session
    starts with from one snapshot, and fetch the credentials. Then set up the report
    lines, check the agent's key is set, and open the checkpoint pool. It stops no
    work: the app keeps track of that. Raise a 503 that says what went wrong, so
    the next request tries again."""
    try:
        if identity.on_runtime():
            random.seed()
            identity.fetch_credentials()
        show_reports()
        api_key()
        return workers_on(open_checkpoint_pool())
    except Exception as error:  # any failure leaves the agent to get ready again
        raise HTTPException(503, NOT_READY.format(error=describe(error))) from error


class Ready:
    """The agent's workers, made once in its process, on its first request."""

    def __init__(self) -> None:
        self.guard = threading.Lock()
        self.workers: Workers | None = None

    def get(self) -> Workers:
        """Return the workers, getting ready first if no request has yet."""
        with self.guard:
            if self.workers is None:
                self.workers = get_ready()
            return self.workers


ready = Ready()


def read(payload: Any) -> Payload:
    """Read a payload, or refuse it with a 400 that says what's wrong."""
    try:
        return PAYLOADS.validate_python(payload)
    except ValidationError as error:
        raise HTTPException(400, what_is_wrong(error)) from error


def what_is_wrong(error: ValidationError) -> str:
    """Say what's wrong with a payload: an operation the agent doesn't know, or
    each input that's missing, wrong or extra."""
    problems = []
    for problem in error.errors():
        if problem["type"] == "union_tag_invalid":
            operation = problem.get("ctx", {}).get("tag")
            problems.append(UNKNOWN_OPERATION.format(operation=operation))
        elif problem["type"] == "union_tag_not_found":
            problems.append(NO_OPERATION)
        elif not problem["loc"]:
            problems.append(NOT_AN_OBJECT)
        else:
            field = ".".join(str(part) for part in problem["loc"][1:])
            problems.append(f"{field}: {problem['msg']}")
    return "; ".join(problems)


def is_the_health_check(payload: Any) -> bool:
    """Say whether a payload is the health check, which needs no key."""
    try:
        Health.model_validate(payload)
    except ValidationError:
        return False
    return True


def check_key(context: RequestContext) -> None:
    """Off Runtime, refuse a request without the agent's key as its bearer token
    with a 401. On Runtime, AWS has already checked that the caller may invoke the
    agent."""
    if identity.on_runtime():
        return
    given = (context.request_headers or {}).get(AUTHORIZATION_HEADER, "")
    if not secrets.compare_digest(given.encode(), f"Bearer {api_key()}".encode()):
        raise HTTPException(401, NEEDS_THE_KEY)


def in_background(name: str, work: Callable[[], object]) -> None:
    """Register the work with the AgentCore app, so its /ping says HealthyBusy
    until the work ends, however it ends, and run it on a thread of its own."""
    task_id = app.add_async_task(name)

    def run() -> None:
        try:
            work()
        finally:
            app.complete_async_task(task_id)

    threading.Thread(target=run, name=name, daemon=True).start()


def open_round(round_id: str) -> dict[str, Any]:
    """Read a round the app made, or refuse one that isn't open."""
    round = improver_api.get_round(round_id)
    if round["status"] != improver_api.OPEN:
        raise Refusal(ROUND_NOT_OPEN.format(number=round["number"]))
    return round


def take_run(request: WorkRun, workers: Workers) -> None:
    """Work a dispatch or an evaluation the app created, refusing one that isn't
    running."""
    run = api.get_run(request.run_id)
    if run["status"] != api.RUNNING:
        raise Refusal(RUN_NOT_RUNNING.format(run_id=request.run_id))
    in_background("run", partial(work_the_run, run, workers.claim_agents))


def take_round(request: WorkRound, workers: Workers) -> None:
    """Work a round the app created: its first evaluations, then the improver
    until it waits for a handler or ends."""
    round = open_round(request.round_id)
    in_background("round", partial(work_the_round, round, workers))


def carry_round_on(request: CarryRoundOn, workers: Workers) -> None:
    """Carry a round on with the improver after the review the app recorded."""
    round = open_round(request.round_id)
    proposal = improver_api.get_proposal(request.round_id, request.proposal_id)
    if proposal["review"] is None:
        raise Refusal(NO_REVIEW.format(proposal_id=request.proposal_id))
    start = improver.resume(proposal["review"], proposal["rejection_reason"] or "")
    in_background("round", partial(carry_the_round_on, round, start, workers))


def resume_claim(request: ResumeClaim, workers: Workers) -> None:
    """Resume a paused claim with its handler's answer, beside any other work,
    taking a sent-back claim first."""
    claim_id = request.claim_id
    claim = api.get_claim(claim_id)
    agent = workers.claim_agents(api.get_current_version(), None)()
    if not paused(claim, agent):
        raise Refusal(NOT_PAUSED.format(claim_id=claim_id))
    answer = answer_of(claim)
    if answer is None:
        raise Refusal(NO_ANSWER.format(claim_id=claim_id))
    if answer["answer"] == SENT_BACK:
        api.take_claim(claim_id, None)
    in_background("resume", partial(resume_telling_the_app, claim_id, agent))


def start(request: Payload, workers: Workers) -> dict[str, Any]:
    """Hand an operation its work, and answer that the agent took it."""
    match request:
        case Health():
            return HEALTHY
        case WorkRun():
            take_run(request, workers)
        case WorkRound():
            take_round(request, workers)
        case CarryRoundOn():
            carry_round_on(request, workers)
        case ResumeClaim():
            resume_claim(request, workers)
    return ACCEPTED


@app.entrypoint
def invoke(payload: Any, context: RequestContext) -> dict[str, Any]:
    """Take one operation's payload: get ready, check the key unless it's the
    health check, read it, and start its work, or say why the agent won't."""
    workers = ready.get()
    if not is_the_health_check(payload):
        check_key(context)
    request = read(payload)
    try:
        return start(request, workers)
    except Refusal as refusal:
        return {"refused": str(refusal)}
    except Refused as refused:  # the app's refusal, such as a claim it doesn't know
        return {"refused": refused.detail}
