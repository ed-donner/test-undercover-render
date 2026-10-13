"""The agent's service: it works the dispatches, evaluations and rounds of the improver
the backend starts, one at a time, and carries a round on after a handler's review.
npm run dev starts it beside the backend and the dashboard."""

import logging
import threading
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import partial
from typing import Annotated, Any

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres import PostgresSaver
from pydantic import BaseModel, Field

from agent import api, improver, improver_api
from agent.connection import Refused, api_key
from agent.console import describe, show_reports
from agent.dispatcher import WorkInRun, work_run
from agent.harness import NewAgent, checkpoint_pool, claim_graphs, work_in_run

ACCEPTED = {"status": "accepted"}
# The most claim agents at once, as the backend and the dashboard also allow.
MOST_AGENTS = 25
A_DISPATCH = "A dispatch is running"
AN_EVALUATION = "An evaluation is running"
A_ROUND = "Round {number} is running"
A_ROUND_STARTING = "A round is starting"
RESTARTED = "The agent's service restarted"

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Keep the checkpoint pool open while the service runs, after marking the runs
    an earlier service left running as stopped, and its rounds, unless a round
    waits for a handler: the improver's progress is saved. Without the agent's
    API key it doesn't start."""
    show_reports()
    api_key()
    with checkpoint_pool() as pool:
        app.state.pool = pool
        api.stop_runs()
        improver_api.stop_rounds(RESTARTED)
        yield


app = FastAPI(title="UnderCover Agent", lifespan=lifespan)


class OneAtATime:
    """The one dispatch, evaluation or stretch of a round the service works at a
    time, and what it is, which a refusal names."""

    def __init__(self) -> None:
        self.guard = threading.Lock()
        self.what: str | None = None

    def take(self, what: str) -> None:
        """Take the one thing at a time for some work, or refuse with a 409 that
        names what is running."""
        with self.guard:
            if self.what is not None:
                raise HTTPException(409, self.what)
            self.what = what

    def rename(self, what: str) -> None:
        """Say better what is running, once it is known."""
        with self.guard:
            self.what = what

    def release(self) -> None:
        with self.guard:
            self.what = None


one_at_a_time = OneAtATime()


@app.exception_handler(Refused)
def refused(_: Request, error: Refused) -> JSONResponse:
    """Pass on the backend's refusal, such as a claim it doesn't know."""
    return JSONResponse({"detail": error.detail}, status_code=error.status_code)


# How to build the claim agents of a version of the claim agent for a kind of run,
# each with a saver of its own.
ClaimAgents = Callable[[dict[str, Any], api.RunKind], NewAgent]


def claim_agents(request: Request) -> ClaimAgents:
    """Build a version's claim agents on the service's pool."""
    return partial(claim_graphs, pool=request.app.state.pool)


ClaimAgentsDep = Annotated[ClaimAgents, Depends(claim_agents)]


@dataclass
class RoundWorkers:
    """What a round's work needs: a version's claim agents, the improver's model
    for a round, and the saver of the improver's progress."""

    claim_agents: ClaimAgents
    improver_model: Callable[[dict[str, Any]], BaseChatModel]
    saver: BaseCheckpointSaver[Any]


def round_workers(request: Request) -> RoundWorkers:
    """The claim agents and the improver on the service's pool."""
    return RoundWorkers(
        claim_agents(request),
        improver.improver_model,
        PostgresSaver(request.app.state.pool),
    )


RoundWorkersDep = Annotated[RoundWorkers, Depends(round_workers)]


class DispatchRequest(BaseModel):
    agents: int = Field(ge=1, le=MOST_AGENTS, description="Claim agents at once")


class EvaluationRequest(DispatchRequest):
    evaluation_set: api.EvaluationSet
    tiny: bool = Field(description="Only the set's five tiny claims")


class RoundRequest(BaseModel):
    handler_id: str = Field(description="The handler who started the round")


class ReviewRequest(BaseModel):
    review: improver_api.Review
    handler_id: str
    reason: str = Field(description="Why a proposal was rejected, or empty")


def claim_work(run: dict[str, Any], claim_agents: ClaimAgents) -> WorkInRun:
    """How to work one of a run's claims, on the claim agents of the run's own
    version, tagged with its round when it has one."""
    new_agent = claim_agents(api.get_version(run["version"]), run["kind"])
    tags = (run["round_id"],) if run["round_id"] else ()
    return partial(work_in_run, new_agent=new_agent, tags=tags)


def evaluate(run: dict[str, Any], claim_agents: ClaimAgents) -> None:
    """Work one of a round's evaluations through the dispatcher."""
    work_run(run, claim_work(run, claim_agents))


def work_in_background(
    create: Callable[[], dict[str, Any]], claim_agents: ClaimAgents
) -> None:
    """Create a run and work it, then let the next work start. A run whose
    dispatcher fails is marked stopped."""
    try:
        run = create()
        work_run(run, claim_work(run, claim_agents))
    except ConnectionError as error:  # a route's server isn't answering
        log.error("The run stopped: %s", error)
        api.stop_runs()
    except Exception:
        log.exception("The run stopped")
        api.stop_runs()
    finally:
        one_at_a_time.release()


def first_evaluations(round: dict[str, Any], workers: RoundWorkers) -> bool:
    """Work the evaluations the round's starting version still needs, one at a time,
    and say whether the round is still open after them: the spending limit or a
    handler may have stopped it."""
    for _ in round["first_evaluations"]:
        run = improver_api.create_round_evaluation(round["round_id"])
        evaluate(run, workers.claim_agents)
        if not still_open(round):
            return False
    return True


def still_open(round: dict[str, Any]) -> bool:
    """Say whether the round is still open: a handler or the spending limit may
    have stopped it."""
    return improver_api.get_round(round["round_id"])["status"] == improver_api.OPEN


def stretch(
    round: dict[str, Any], start: improver.Start, workers: RoundWorkers
) -> None:
    """Run the improver until it waits for a handler, then record its proposal, or
    until it ends, then finish the round if it is still open. A proposal the
    backend refuses, such as a second change, goes back to the improver as a
    rejection with the backend's reason."""
    while proposal := improver.work_stretch(
        round,
        start,
        partial(evaluate, claim_agents=workers.claim_agents),
        workers.saver,
        workers.improver_model(round),
    ):
        try:
            improver.record_proposal(round["round_id"], proposal)
            return
        except Refused as refusal:
            start = improver.resume(improver_api.REJECTED, refusal.answer)
    if still_open(round):
        improver_api.finish_round(round["round_id"])


def stop_the_round(error: Exception) -> None:
    """Stop a round whose work failed, giving the error as the reason, and an
    evaluation it left running."""
    log.exception("The round stopped")
    api.stop_runs()
    improver_api.stop_rounds(describe(error))


def work_round(handler_id: str, workers: RoundWorkers) -> None:
    """Create a round, work its first evaluations, then the improver's first
    stretch, and let the next work start."""
    try:
        round = improver_api.create_round(handler_id)
    except Exception:  # no round to stop, so the next work may start
        log.exception("The round didn't start")
        one_at_a_time.release()
        return
    one_at_a_time.rename(A_ROUND.format(number=round["number"]))
    try:
        if first_evaluations(round, workers):
            stretch(round, improver.begin(), workers)
    except Exception as error:
        stop_the_round(error)
    finally:
        one_at_a_time.release()


def carry_the_round_on(
    round: dict[str, Any], start: improver.Start, workers: RoundWorkers
) -> None:
    """Carry the improver on after a handler's review, and let the next work start."""
    try:
        stretch(round, start, workers)
    except Exception as error:
        stop_the_round(error)
    finally:
        one_at_a_time.release()


@app.get("/api/health", operation_id="health")
def health() -> dict[str, str]:
    """Check that the agent's service is running."""
    return {"status": "ok"}


@app.post("/api/dispatches", operation_id="start_dispatch", status_code=202)
def start_dispatch(
    request: DispatchRequest, claim_agents: ClaimAgentsDep, background: BackgroundTasks
) -> dict[str, str]:
    """Start a dispatch with up to N claim agents at once."""
    one_at_a_time.take(A_DISPATCH)
    create = partial(api.create_dispatch, request.agents)
    background.add_task(work_in_background, create, claim_agents)
    return ACCEPTED


@app.post("/api/evaluations", operation_id="start_evaluation", status_code=202)
def start_evaluation(
    request: EvaluationRequest,
    claim_agents: ClaimAgentsDep,
    background: BackgroundTasks,
) -> dict[str, str]:
    """Start an evaluation with up to N claim agents at once."""
    one_at_a_time.take(AN_EVALUATION)
    create = partial(
        api.create_evaluation, request.evaluation_set, request.tiny, request.agents
    )
    background.add_task(work_in_background, create, claim_agents)
    return ACCEPTED


@app.post("/api/rounds", operation_id="start_round", status_code=202)
def start_round(
    request: RoundRequest, workers: RoundWorkersDep, background: BackgroundTasks
) -> dict[str, str]:
    """Start a round of the improver for the handler who asked."""
    one_at_a_time.take(A_ROUND_STARTING)
    background.add_task(work_round, request.handler_id, workers)
    return ACCEPTED


@app.post(
    "/api/rounds/{round_id}/proposals/{proposal_id}/review",
    operation_id="review_proposal",
    status_code=202,
)
def review_proposal(
    round_id: str,
    proposal_id: str,
    request: ReviewRequest,
    workers: RoundWorkersDep,
    background: BackgroundTasks,
) -> dict[str, str]:
    """Record a handler's review of a proposal, then carry the improver on."""
    one_at_a_time.take(A_ROUND_STARTING)
    try:
        round = improver_api.get_round(round_id)
        one_at_a_time.rename(A_ROUND.format(number=round["number"]))
        improver_api.record_review(
            round_id, proposal_id, request.review, request.handler_id, request.reason
        )
    except Exception:  # nothing to carry on, so the next work may start
        one_at_a_time.release()
        raise
    start = improver.resume(request.review, request.reason)
    background.add_task(carry_the_round_on, round, start, workers)
    return ACCEPTED
