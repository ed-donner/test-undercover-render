"""The agent's work, which the entry point hands on: a run through the dispatcher, a
round through the improver, and a resume through the harness, each telling the app
every minute while it goes on, and the app why it stopped when it fails."""

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import partial
from typing import Any

from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver

from agent import api, app_terms, improver, improver_api
from agent.connection import Refused
from agent.console import describe
from agent.dispatcher import WorkInRun, work_run
from agent.harness import ClaimAgent, NewAgent, resume, work_in_run
from agent.heartbeat import beating

log = logging.getLogger(__name__)

# How to build the claim agents of a version of the claim agent for a kind of run,
# or for no run, each with a saver of its own.
ClaimAgents = Callable[[dict[str, Any], app_terms.RunKind | None], NewAgent]


@dataclass
class Workers:
    """What the agent's work needs: a version's claim agents, the improver's model
    for a round, and the saver of the improver's progress."""

    claim_agents: ClaimAgents
    improver_model: Callable[[dict[str, Any]], BaseChatModel]
    saver: BaseCheckpointSaver[Any]


def claim_work(run: dict[str, Any], claim_agents: ClaimAgents) -> WorkInRun:
    """How to work one of a run's claims, on the claim agents of the run's own
    version, tagged with its round when it has one."""
    new_agent = claim_agents(api.get_version(run["version"]), run["kind"])
    tags = (run["round_id"],) if run["round_id"] else ()
    return partial(work_in_run, new_agent=new_agent, tags=tags)


def evaluate(run: dict[str, Any], claim_agents: ClaimAgents) -> None:
    """Work one of a round's evaluations through the dispatcher."""
    work_run(run, claim_work(run, claim_agents))


def work_the_run(run: dict[str, Any], claim_agents: ClaimAgents) -> None:
    """Work a run the app created, telling the app every minute. A run whose
    dispatcher fails is stopped by its id, with the error."""
    run_id = run["run_id"]
    try:
        with beating(partial(api.record_run_heartbeat, run_id)):
            work_run(run, claim_work(run, claim_agents))
    except ConnectionError as error:  # a route's server isn't answering
        log.error("The run stopped: %s", error)
        api.fail_run(run_id, describe(error))
    except Exception as error:
        log.exception("The run stopped")
        api.fail_run(run_id, describe(error))


def first_evaluations(round: dict[str, Any], workers: Workers) -> bool:
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


def stretch(round: dict[str, Any], start: improver.Start, workers: Workers) -> None:
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


@contextmanager
def working_on(round: dict[str, Any]) -> Iterator[None]:
    """Tell the app every minute while the round's work goes on, which covers the
    evaluation it is working, and stop the round with that evaluation, giving the
    error as the reason, when the work fails."""
    try:
        with beating(partial(improver_api.record_round_heartbeat, round["round_id"])):
            yield
    except Exception as error:  # the round stops, and nothing else
        log.exception("The round stopped")
        improver_api.fail_round(round["round_id"], describe(error))


def work_the_round(round: dict[str, Any], workers: Workers) -> None:
    """Work a round's first evaluations, then the improver's first stretch."""
    with working_on(round):
        if first_evaluations(round, workers):
            stretch(round, improver.begin(), workers)


def carry_the_round_on(
    round: dict[str, Any], start: improver.Start, workers: Workers
) -> None:
    """Carry the improver on after a handler's review."""
    with working_on(round):
        stretch(round, start, workers)


def resume_telling_the_app(claim_id: str, agent: ClaimAgent) -> None:
    """Resume a paused claim, telling the app every minute that the resume is still
    working on it. A resume that fails, such as on a rate limit, is logged, and
    once it has been quiet for five minutes the next dispatch carries the claim
    on."""
    try:
        with beating(partial(api.record_claim_heartbeat, claim_id)):
            resume(claim_id, agent)
    except Exception:  # the resume stops, and nothing else
        log.exception("The resume of %s stopped", claim_id)
