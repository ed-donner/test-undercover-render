"""Calling an AgentCore app, which the agent's service and the Copilot's share: a
JSON payload posted to the app's /invocations on the laptop, or sent to its runtime
on AgentCore Runtime in the session given, retrying a conflict while the call has
time, and the answer read: whether the app took the work. Each service words its
failures for the handler."""

import json
import logging
import time
from dataclasses import dataclass
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

INVOCATIONS = "/invocations"
LAPTOP_TIMEOUT = 10
CONNECT_TIMEOUT = 2
READ_TIMEOUT = 15
ACCEPTED = {"accepted": True}
# While Runtime starts or stops a session, a call to it gets a conflict before it
# reaches the app, so it is safe to retry, after each of these waits in turn.
CONFLICT = "ConflictException"
CONFLICT_WAITS = (1, 2, 4)
# The longest a call to Runtime may take, inside the app's 30 seconds on Lambda: a
# conflict is retried only while the time spent, the wait and a whole try, its
# connection and its read, still fit it. A try's read is short enough that all
# three waits fit when conflicts come back quickly, so a call makes four tries at
# most, over about seven seconds.
BUDGET = 25
LONGEST_TRY = CONNECT_TIMEOUT + READ_TIMEOUT

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
# botocore's DEBUG lines hold each request's payload, and the Copilot's payload
# holds a handler's sign-in.
BOTOCORE = "botocore"


@dataclass(frozen=True)
class Wording:
    """How a service's failures read to the handler: it isn't running, it couldn't
    take the work, with {reason}, or it didn't answer in time."""

    not_running: str
    couldnt_take: str
    no_answer: str


class NotTaken(HTTPException):
    """The app didn't take the work, with the status and the reason the handler
    gets: it was never reached, it refused, or it gave an error answer."""


class MayHaveStarted(HTTPException):
    """The request reached the app, then timed out or its answer was cut off, so
    the work may have started."""

    def __init__(self, wording: Wording) -> None:
        super().__init__(HTTPStatus.SERVICE_UNAVAILABLE, wording.no_answer)


class Conflict(Exception):
    """Runtime was starting or stopping the session, so the call didn't reach the
    app."""


@cache
def runtime_client() -> Any:
    """The client for AgentCore Runtime, in the region the app runs in: one attempt
    at each call, since a retried call could start the same work twice, and
    CONNECT_TIMEOUT seconds to connect and READ_TIMEOUT to read."""
    config = Config(
        retries={"total_max_attempts": 1},
        connect_timeout=CONNECT_TIMEOUT,
        read_timeout=READ_TIMEOUT,
    )
    return boto3.client("bedrock-agentcore", config=config)


def not_running(wording: Wording) -> NotTaken:
    return NotTaken(HTTPStatus.SERVICE_UNAVAILABLE, wording.not_running)


def error_answer(wording: Wording, reason: str) -> NotTaken:
    return NotTaken(HTTPStatus.BAD_GATEWAY, wording.couldnt_take.format(reason=reason))


def error_in(body: bytes) -> str:
    """The reason in an error answer: the app's error, or the answer itself."""
    try:
        return json.loads(body)["error"]
    except (ValueError, TypeError, KeyError):
        return body.decode(errors="replace") or "it gave no answer"


def take_answer(wording: Wording, status: int, body: bytes) -> None:
    """Read the app's whole answer: return when it took the work, or raise NotTaken
    when it refused or gave an error answer, which is any status of 400 or more, or
    an answer that is neither an acceptance nor a refusal."""
    if status >= HTTPStatus.BAD_REQUEST:
        raise error_answer(wording, error_in(body))
    try:
        answer = json.loads(body)
    except ValueError as error:
        raise error_answer(wording, f"its answer isn't JSON: {body[:200]!r}") from error
    if answer == ACCEPTED:
        return
    if isinstance(answer, dict) and isinstance(answer.get("refused"), str):
        raise NotTaken(HTTPStatus.CONFLICT, answer["refused"])
    raise error_answer(wording, f"it answered {json.dumps(answer)}")


def post(
    client: httpx.Client,
    url: str,
    payload: Payload,
    headers: dict[str, str],
    wording: Wording,
) -> None:
    """Post the payload to an AgentCore app's /invocations at its address on the
    laptop, with the headers given."""
    try:
        response = client.post(
            url + INVOCATIONS, json=payload, headers=headers, timeout=LAPTOP_TIMEOUT
        )
    except NEVER_SENT as error:
        raise not_running(wording) from error
    except httpx.TransportError as error:  # sent, then timed out or cut off
        raise MayHaveStarted(wording) from error
    take_answer(wording, response.status_code, response.content)


def keep_botocore_quiet() -> None:
    """Keep botocore's report lines, and every one of its loggers', at INFO or
    above, whatever the app's own logging, so no request's payload is ever
    written."""
    names = [
        name for name in logging.root.manager.loggerDict if name.startswith(BOTOCORE)
    ]
    for logger in map(logging.getLogger, [BOTOCORE, *names]):
        if logger.getEffectiveLevel() < logging.INFO:
            logger.setLevel(logging.INFO)


def invoke_once(arn: str, session_id: str, payload: Payload, wording: Wording) -> None:
    """Send the payload to a runtime in the session given, once. A request that
    never connected wasn't sent, nor was one botocore refused to send, such as for
    want of credentials or a region, which is logged."""
    keep_botocore_quiet()
    try:
        response = runtime_client().invoke_agent_runtime(
            agentRuntimeArn=arn,
            runtimeSessionId=session_id,
            payload=json.dumps(payload),
        )
        status, body = response["statusCode"], response["response"].read()
    except NeverConnected as error:
        raise not_running(wording) from error
    except ClientError as error:
        if error.response["Error"]["Code"] == CONFLICT:
            raise Conflict() from error
        raise error_answer(wording, error.response["Error"]["Message"]) from error
    except SENT_THEN_LOST as error:
        raise MayHaveStarted(wording) from error
    except BotoCoreError as error:
        log.warning("The runtime wasn't asked: %s", error)
        raise not_running(wording) from error
    take_answer(wording, status, body)


def invoke(arn: str, session_id: str, payload: Payload, wording: Wording) -> None:
    """Send the payload to a runtime in the session given, retrying a conflict
    after each of CONFLICT_WAITS while the wait and another whole try still fit
    within BUDGET of the first try. A conflict that can't be retried counts as never
    reached, since the call didn't reach the app."""
    started, waits = time.monotonic(), iter(CONFLICT_WAITS)
    while True:
        try:
            return invoke_once(arn, session_id, payload, wording)
        except Conflict as conflict:
            wait = next(waits, None)
            if wait is None or time.monotonic() - started + wait + LONGEST_TRY > BUDGET:
                raise not_running(wording) from conflict
            time.sleep(wait)
