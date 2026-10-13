"""The agent's service, as the backend calls it: to start a dispatch, an evaluation
or a round, and to pass on a review of a proposal."""

import os
from http import HTTPStatus
from typing import Any

import httpx
from fastapi import HTTPException

AGENT_URL = os.getenv("UNDERCOVER_AGENT", "http://127.0.0.1:8002")
NOT_RUNNING = "The agent's service isn't running"
NO_ANSWER = (
    "The agent's service didn't answer in time. Reload the page to see whether "
    "it went through."
)

agent = httpx.Client(base_url=f"{AGENT_URL}/api", timeout=10)


def send(path: str, body: dict[str, Any]) -> None:
    """Send the agent's service some work, passing on its refusal while something
    else is running, or say it isn't running when it can't be reached, or that
    it didn't answer in time."""
    try:
        response = agent.post(path, json=body)
    except (httpx.ConnectError, httpx.ConnectTimeout) as error:
        raise HTTPException(HTTPStatus.SERVICE_UNAVAILABLE, NOT_RUNNING) from error
    except httpx.TimeoutException as error:
        raise HTTPException(HTTPStatus.SERVICE_UNAVAILABLE, NO_ANSWER) from error
    if response.status_code == HTTPStatus.CONFLICT:
        raise HTTPException(HTTPStatus.CONFLICT, response.json()["detail"])
    response.raise_for_status()


def start_dispatch(agents: int) -> None:
    """Ask the agent's service to start a dispatch with up to N claim agents."""
    send("/dispatches", {"agents": agents})


def start_evaluation(evaluation_set: str, tiny: bool, agents: int) -> None:
    """Ask the agent's service to start an evaluation with up to N claim agents."""
    body = {"evaluation_set": evaluation_set, "tiny": tiny, "agents": agents}
    send("/evaluations", body)


def start_round(handler_id: str) -> None:
    """Ask the agent's service to start a round of the improver."""
    send("/rounds", {"handler_id": handler_id})


def review_proposal(
    round_id: str, proposal_id: str, review: str, handler_id: str, reason: str
) -> None:
    """Pass a handler's review of a proposal to the agent's service, which records
    it and carries the improver on."""
    body = {"review": review, "handler_id": handler_id, "reason": reason}
    send(f"/rounds/{round_id}/proposals/{proposal_id}/review", body)
