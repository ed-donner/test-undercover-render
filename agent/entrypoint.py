"""The agent as an AgentCore app: one entrypoint takes the payload of each operation
the app asks for, checks what it must, answers at once, and hands the work to
agent/work.py on a thread of its own, which the AgentCore app's /ping reports as
busy until it ends. npm run dev serves it on port 8080, and runtime/main.py runs it
on AgentCore Runtime. Nothing happens as it's imported: it gets ready on its first
request."""

import random
import secrets
from functools import partial
from typing import Annotated, Any, Literal

from bedrock_agentcore.runtime import BedrockAgentCoreApp, RequestContext
from bedrock_agentcore.runtime.models import AUTHORIZATION_HEADER
from langgraph.checkpoint.postgres import PostgresSaver
from pydantic import Field, TypeAdapter
from starlette.exceptions import HTTPException

from agent import api, app_terms, identity, improver, improver_api
from agent.agentcore_app import (
    ACCEPTED,
    HEALTHY,
    Health,
    Operation,
    Ready,
    Refusal,
    in_background,
    is_the_health_check,
    read,
)
from agent.checkpoints import Pool, open_checkpoint_pool
from agent.connection import Refused, api_key
from agent.console import show_reports
from agent.handler_answer import SENT_BACK, answer_of
from agent.harness import claim_graphs, paused
from agent.work import (
    Workers,
    carry_the_round_on,
    resume_telling_the_app,
    work_the_round,
    work_the_run,
)

RUN_NOT_RUNNING = "Run {run_id} isn't running"
ROUND_NOT_OPEN = "Round {number} isn't open"
NO_REVIEW = "Proposal {proposal_id} has no review"
NOT_PAUSED = "Claim {claim_id} isn't paused for a handler"
NO_ANSWER = "Claim {claim_id} has no answer from a handler yet"
NOT_READY = "The agent couldn't get ready: {error}"
# The agent's credentials in AgentCore Identity on Runtime.
CREDENTIALS = ("OPENROUTER_API_KEY", "UNDERCOVER_API_KEY", "DATABASE_URL")
NEEDS_THE_KEY = "This needs the agent's API key"


app = BedrockAgentCoreApp()


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


def workers_on(pool: Pool) -> Workers:
    """The claim agents and the improver, on the process's checkpoint pool."""
    return Workers(
        partial(claim_graphs, pool=pool),
        improver.improver_model,
        PostgresSaver(pool),
    )


def get_ready() -> Workers:
    """Get ready to work. On Runtime, reseed the random numbers, which every session
    starts with from one snapshot, and fetch the agent's three credentials. Then
    set up the report lines, check the agent's key is set, and open the checkpoint
    pool. It stops no work: the app keeps track of that."""
    if identity.on_runtime():
        random.seed()
        identity.fetch_credentials(*CREDENTIALS)
    show_reports()
    api_key()
    return workers_on(open_checkpoint_pool())


def new_ready() -> Ready[Workers]:
    return Ready(get_ready, NOT_READY)


ready = new_ready()


def check_key(context: RequestContext) -> None:
    """Off Runtime, refuse a request without the agent's key as its bearer token
    with a 401. On Runtime, AWS has already checked that the caller may invoke the
    agent."""
    if identity.on_runtime():
        return
    given = (context.request_headers or {}).get(AUTHORIZATION_HEADER, "")
    if not secrets.compare_digest(given.encode(), f"Bearer {api_key()}".encode()):
        raise HTTPException(401, NEEDS_THE_KEY)


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
    if run["status"] != app_terms.RUNNING:
        raise Refusal(RUN_NOT_RUNNING.format(run_id=request.run_id))
    in_background(app, "run", partial(work_the_run, run, workers.claim_agents))


def take_round(request: WorkRound, workers: Workers) -> None:
    """Work a round the app created: its first evaluations, then the improver
    until it waits for a handler or ends."""
    round = open_round(request.round_id)
    in_background(app, "round", partial(work_the_round, round, workers))


def carry_round_on(request: CarryRoundOn, workers: Workers) -> None:
    """Carry a round on with the improver after the review the app recorded."""
    round = open_round(request.round_id)
    proposal = improver_api.get_proposal(request.round_id, request.proposal_id)
    if proposal["review"] is None:
        raise Refusal(NO_REVIEW.format(proposal_id=request.proposal_id))
    start = improver.resume(proposal["review"], proposal["rejection_reason"] or "")
    in_background(app, "round", partial(carry_the_round_on, round, start, workers))


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
    in_background(app, "resume", partial(resume_telling_the_app, claim_id, agent))


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
    request = read(PAYLOADS, payload)
    try:
        return start(request, workers)
    except Refusal as refusal:
        return {"refused": str(refusal)}
    except Refused as refused:  # the app's refusal, such as a claim it doesn't know
        return {"refused": refused.detail}
