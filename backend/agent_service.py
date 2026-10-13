"""The agent, as the app calls it: one JSON payload for each operation, posted to its
AgentCore app's /invocations on the laptop, with the agent's key, or sent to its
runtime on AgentCore Runtime when UNDERCOVER_AGENT_RUNTIME names one. Each answer
says whether the agent took the work."""

import json
import logging
import os
import uuid
from functools import cache
from http import HTTPStatus
from typing import Any

import boto3
import httpx
from botocore.config import Config
from botocore.exceptions import (
    BotoCoreError,
    ClientError,
    HTTPClientError,
    IncompleteReadError,
    ResponseStreamingError,
)
from botocore.exceptions import ConnectionError as NeverConnected
from fastapi import HTTPException

from backend.api_key import the_agents_key

AGENT = "UNDERCOVER_AGENT"
# The agent's AgentCore app on the laptop, as npm run dev serves it.
LOCAL_AGENT = "http://127.0.0.1:8080"
INVOCATIONS = "/invocations"
TIMEOUT = 10
RUNTIME = "UNDERCOVER_AGENT_RUNTIME"
NOT_RUNNING = "The agent's service isn't running"
NO_ANSWER = (
    "The agent's service didn't answer in time. Reload the page to see whether "
    "it went through."
)
COULDNT_TAKE = "The agent couldn't take the work: {reason}"
ACCEPTED = {"accepted": True}

Payload = dict[str, Any]

# On the laptop: a request that never connected wasn't sent, and any other failure
# once it was may have started the work.
NEVER_SENT = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.PoolTimeout,
    httpx.ProxyError,
    httpx.UnsupportedProtocol,
)
# On Runtime: an answer lost once the request was sent.
SENT_THEN_LOST = (HTTPClientError, ResponseStreamingError, IncompleteReadError)

log = logging.getLogger(__name__)

agent = httpx.Client()


class NotTaken(HTTPException):
    """The agent didn't take the work, with the status and the reason the handler
    gets: it was never reached, it refused, or it gave an error answer."""


class MayHaveStarted(HTTPException):
    """The request reached the agent, then timed out or its answer was cut off, so
    the work may have started."""

    def __init__(self) -> None:
        super().__init__(HTTPStatus.SERVICE_UNAVAILABLE, NO_ANSWER)


@cache
def runtime_client() -> Any:
    """The client for AgentCore Runtime, in the region the app runs in: one attempt
    at each call, since a retried call could start the same work twice, 5 seconds
    to connect and 20 to read."""
    config = Config(
        retries={"total_max_attempts": 1}, connect_timeout=5, read_timeout=20
    )
    return boto3.client("bedrock-agentcore", config=config)


def error_answer(reason: str) -> NotTaken:
    return NotTaken(HTTPStatus.BAD_GATEWAY, COULDNT_TAKE.format(reason=reason))


def error_in(body: bytes) -> str:
    """The reason in an error answer: the agent's error, or the answer itself."""
    try:
        return json.loads(body)["error"]
    except (ValueError, TypeError, KeyError):
        return body.decode(errors="replace") or "it gave no answer"


def take_answer(status: int, body: bytes) -> None:
    """Read the agent's whole answer: return when it took the work, or raise
    NotTaken when it refused or gave an error answer, which is any status of 400
    or more, or an answer that is neither an acceptance nor a refusal."""
    if status >= HTTPStatus.BAD_REQUEST:
        raise error_answer(error_in(body))
    try:
        answer = json.loads(body)
    except ValueError as error:
        raise error_answer(f"its answer isn't JSON: {body[:200]!r}") from error
    if answer == ACCEPTED:
        return
    if isinstance(answer, dict) and isinstance(answer.get("refused"), str):
        raise NotTaken(HTTPStatus.CONFLICT, answer["refused"])
    raise error_answer(f"it answered {json.dumps(answer)}")


def post_to_the_laptop(payload: Payload) -> None:
    """Post the payload to the agent's AgentCore app at UNDERCOVER_AGENT, read now,
    or on the laptop, with the agent's key."""
    url = os.getenv(AGENT, LOCAL_AGENT) + INVOCATIONS
    headers = {"Authorization": f"Bearer {the_agents_key()}"}
    try:
        response = agent.post(url, json=payload, headers=headers, timeout=TIMEOUT)
    except NEVER_SENT as error:
        raise NotTaken(HTTPStatus.SERVICE_UNAVAILABLE, NOT_RUNNING) from error
    except httpx.TransportError as error:  # sent, then timed out or cut off
        raise MayHaveStarted() from error
    take_answer(response.status_code, response.content)


def invoke_on_runtime(arn: str, payload: Payload) -> None:
    """Send the payload to the agent's runtime, in a session of its own. A request
    that never connected wasn't sent, nor was one botocore refused to send, such as
    for want of credentials or a region, which is logged."""
    try:
        response = runtime_client().invoke_agent_runtime(
            agentRuntimeArn=arn,
            runtimeSessionId=str(uuid.uuid4()),
            payload=json.dumps(payload),
        )
        status, body = response["statusCode"], response["response"].read()
    except NeverConnected as error:
        raise NotTaken(HTTPStatus.SERVICE_UNAVAILABLE, NOT_RUNNING) from error
    except ClientError as error:
        raise error_answer(error.response["Error"]["Message"]) from error
    except SENT_THEN_LOST as error:
        raise MayHaveStarted() from error
    except BotoCoreError as error:
        log.warning("The agent's runtime wasn't asked: %s", error)
        raise NotTaken(HTTPStatus.SERVICE_UNAVAILABLE, NOT_RUNNING) from error
    take_answer(status, body)


def ask(payload: Payload) -> None:
    """Ask the agent to take some work, on Runtime when UNDERCOVER_AGENT_RUNTIME
    names its runtime, read now, or else on the laptop. Raise NotTaken or
    MayHaveStarted when it didn't, or may not have."""
    if arn := os.getenv(RUNTIME):
        invoke_on_runtime(arn, payload)
    else:
        post_to_the_laptop(payload)


def work_run(run_id: str) -> None:
    """Ask the agent to work a dispatch or an evaluation the app created."""
    ask({"operation": "work_run", "run_id": run_id})


def work_round(round_id: str) -> None:
    """Ask the agent to work a round of the improver the app created."""
    ask({"operation": "work_round", "round_id": round_id})


def carry_round_on(round_id: str, proposal_id: str) -> None:
    """Ask the agent to carry a round on after the review the app recorded."""
    ask(
        {
            "operation": "carry_round_on",
            "round_id": round_id,
            "proposal_id": proposal_id,
        }
    )


def resume_claim(claim_id: str) -> None:
    """Ask the agent to resume a paused claim with its handler's answer, which it
    reads from the claim."""
    ask({"operation": "resume_claim", "claim_id": claim_id})
