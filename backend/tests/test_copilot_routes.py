"""The app's two routes to the Copilot: its AgentCore app's /invocations on the
laptop, with no key, or its runtime on AgentCore Runtime through boto3, in the
conversation's session; what the handler gets when the Copilot takes a turn,
refuses it, can't be reached, gives an error answer or doesn't answer in time; and
the handler's sign-in kept out of botocore's report lines."""

import io
import json
import logging

import httpx
import pytest
from botocore.awsrequest import AWSResponse
from botocore.exceptions import (
    ClientError,
    EndpointConnectionError,
    IncompleteReadError,
    ReadTimeoutError,
)
from sqlalchemy import select

from backend import copilot_service, runtime_calls
from backend.copilot_service import NO_ANSWER, NOT_RUNNING
from backend.database import copilot_turns, engine
from backend.tests.agent_answers import answering, raising
from backend.tests.copilot_requests import (
    QUESTION,
    conversation_of,
    finish_turn,
    latest,
    list_conversations,
    send_message,
    start_conversation,
    started,
)
from backend.tests.runtime_stand_in import ENDPOINT, runtime_at
from backend.tests.sign_in import DANA, token

ARN = "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/undercover_copilot-x"
REFUSAL = "Turn 1 isn't the conversation's latest working turn"


@pytest.fixture
def runtime(monkeypatch):
    """Send the Copilot's turns to a stand-in for its runtime on AgentCore
    Runtime."""
    return runtime_at(monkeypatch, copilot_service.RUNTIME, ARN)


def test_a_turn_is_committed_then_posted_to_the_copilot_with_no_key(
    dashboard, copilot_answers
):
    sent, found = [], []

    def accept(request):
        sent.append(request)
        payload = json.loads(request.content)
        with engine().connect() as fresh:
            query = select(copilot_turns.c.message).where(
                copilot_turns.c.turn_id == payload["turn_id"]
            )
            found.append(fresh.execute(query).scalar_one_or_none())
        return httpx.Response(200, json={"accepted": True})

    copilot_answers(accept)
    response = start_conversation(dashboard)
    assert response.status_code == 202
    conversation = response.json()
    [request] = sent
    assert str(request.url) == "http://127.0.0.1:8081/invocations"
    assert "Authorization" not in request.headers
    assert "X-API-Key" not in request.headers
    assert set(request.extensions["timeout"].values()) == {10}
    payload = json.loads(request.content)
    assert set(payload) == {"operation", "conversation_id", "turn_id", "sign_in"}
    assert payload["operation"] == "take_turn"
    assert payload["conversation_id"] == conversation["conversation_id"]
    assert payload["turn_id"] == latest(conversation)["turn_id"]
    assert payload["sign_in"].count(".") == 2
    assert found == [QUESTION]


def test_the_sign_in_passed_on_is_the_handlers_own(dashboard, copilot_calls):
    own = token(DANA)
    assert start_conversation(dashboard, access_token=own).status_code == 202
    assert copilot_calls[0]["sign_in"] == own


def test_the_laptop_route_is_at_undercover_copilot(
    dashboard, copilot_answers, monkeypatch
):
    sent = []

    def accept(request):
        sent.append(str(request.url))
        return httpx.Response(200, json={"accepted": True})

    copilot_answers(accept)
    monkeypatch.setenv(copilot_service.COPILOT, "http://copilot.example.com:9001")
    assert start_conversation(dashboard).status_code == 202
    assert sent == ["http://copilot.example.com:9001/invocations"]


@pytest.mark.parametrize(
    ("answer", "outcome"),
    [
        (answering(200, b'{"accepted": true}'), (202, None, "working")),
        (
            answering(200, json.dumps({"refused": REFUSAL}).encode()),
            (409, REFUSAL, "failed"),
        ),
        (raising(httpx.ConnectError("Refused")), (503, NOT_RUNNING, "failed")),
        (
            answering(500, b'{"error": "The Copilot couldn\'t get ready: Boom"}'),
            (
                502,
                "The Copilot couldn't take the message: The Copilot couldn't get "
                "ready: Boom",
                "failed",
            ),
        ),
        (raising(httpx.ReadTimeout("Timed out")), (503, NO_ANSWER, "working")),
    ],
)
def test_on_the_laptop_route(dashboard, copilot_answers, answer, outcome):
    """The handler's answer, and the turn: failed with the reason when the Copilot
    didn't take it, and left working when it may have."""
    status, detail, turn = outcome
    copilot_answers(answer)
    response = start_conversation(dashboard)
    assert response.status_code == status
    if detail:
        assert response.json()["detail"] == detail
    [listed] = list_conversations(dashboard).json()
    read = conversation_of(dashboard, listed["conversation_id"]).json()
    assert latest(read)["status"] == turn
    if turn == "failed":
        assert latest(read)["failure"] == detail


def test_the_runtime_route_sends_each_turn_in_the_conversations_session(
    dashboard, runtime, copilot_calls
):
    conversation = started(dashboard)
    conversation_id = conversation["conversation_id"]
    turn_id = latest(conversation)["turn_id"]
    finish_turn(dashboard, turn_id)
    assert send_message(dashboard, conversation_id).status_code == 202
    first, second = runtime.calls
    for call in (first, second):
        assert call["agentRuntimeArn"] == ARN
        assert call["runtimeSessionId"] == conversation_id
        assert set(call) == {"agentRuntimeArn", "runtimeSessionId", "payload"}
    assert json.loads(first["payload"])["operation"] == "take_turn"
    assert len(conversation_id) == 49
    assert copilot_calls == []


def test_a_conflict_is_retried_after_1_2_and_4_seconds_then_isnt_running(
    dashboard, runtime
):
    runtime.conflicts = 10
    # Each conflict comes back after a fifth of a second, as Runtime's do.
    runtime.conflict_delay = 0.2
    response = start_conversation(dashboard)
    assert (response.status_code, response.json()["detail"]) == (503, NOT_RUNNING)
    assert len(runtime.calls) == 4
    assert runtime.clock.waits == [1, 2, 4]


def test_a_conflict_then_an_answer_takes_the_turn(dashboard, runtime):
    runtime.conflicts = 1
    assert start_conversation(dashboard).status_code == 202
    assert len(runtime.calls) == 2


@pytest.mark.parametrize(("delay", "tries"), [(0.2, 4), (2, 3), (5, 2), (9, 1)])
def test_conflicts_stop_once_another_try_would_pass_the_budget(
    dashboard, runtime, delay, tries
):
    runtime.conflicts = 10
    runtime.conflict_delay = delay
    response = start_conversation(dashboard)
    assert (response.status_code, response.json()["detail"]) == (503, NOT_RUNNING)
    assert len(runtime.calls) == tries
    last_try_began = runtime.called_at[-1]
    assert last_try_began + runtime_calls.LONGEST_TRY <= runtime_calls.BUDGET
    assert runtime.clock.now <= runtime_calls.BUDGET


@pytest.mark.parametrize(
    ("given", "outcome"),
    [
        (
            {"answer": (200, json.dumps({"refused": REFUSAL}).encode())},
            (409, REFUSAL, "failed"),
        ),
        (
            {"raises": EndpointConnectionError(endpoint_url=ENDPOINT)},
            (503, NOT_RUNNING, "failed"),
        ),
        (
            {
                "raises": ClientError(
                    {"Error": {"Code": "AccessDeniedException", "Message": "Denied"}},
                    "InvokeAgentRuntime",
                )
            },
            (502, "The Copilot couldn't take the message: Denied", "failed"),
        ),
        (
            {"raises": ReadTimeoutError(endpoint_url=ENDPOINT)},
            (503, NO_ANSWER, "working"),
        ),
        (
            {"cut_off": IncompleteReadError(actual_bytes=4, expected_bytes=20)},
            (503, NO_ANSWER, "working"),
        ),
    ],
)
def test_on_the_runtime_route(dashboard, runtime, given, outcome):
    """The handler's answer, and the turn: failed with the reason when the Copilot
    didn't take it, and left working when it may have."""
    status, detail, turn = outcome
    for name, value in given.items():
        setattr(runtime, name, value)
    response = start_conversation(dashboard)
    assert (response.status_code, response.json()["detail"]) == (status, detail)
    assert len(runtime.calls) == 1
    [listed] = list_conversations(dashboard).json()
    read = latest(conversation_of(dashboard, listed["conversation_id"]).json())
    assert read["status"] == turn
    assert read["failure"] == (detail if turn == "failed" else None)


class Answer(io.BytesIO):
    """An answer's body as urllib3 hands it to botocore."""

    def stream(self, **_):
        yield self.read()


def test_the_runtime_route_writes_no_payload_to_the_logs_at_debug(
    dashboard, monkeypatch, caplog
):
    """The real boto3 client serializes, signs and handles the request as it would
    on Lambda; only the network send is stubbed, so no AWS request is made."""
    monkeypatch.setenv(copilot_service.RUNTIME, ARN)
    logging.getLogger("botocore").setLevel(logging.NOTSET)
    logging.getLogger("botocore.endpoint").setLevel(logging.DEBUG)
    runtime_calls.runtime_client.cache_clear()
    sent = []

    def send(request, **_):
        sent.append(request.body)
        headers = {"content-type": "application/json"}
        return AWSResponse(request.url, 200, headers, Answer(b'{"accepted": true}'))

    try:
        client = runtime_calls.runtime_client()
        client.meta.events.register(
            "before-send.bedrock-agentcore.InvokeAgentRuntime", send
        )
        caplog.set_level(logging.DEBUG)
        own = token(DANA)
        response = start_conversation(dashboard, access_token=own)
    finally:
        runtime_calls.runtime_client.cache_clear()
    assert response.status_code == 202
    [body] = sent
    assert own in body.decode()
    for name in ("botocore", "botocore.endpoint"):
        assert logging.getLogger(name).getEffectiveLevel() >= logging.INFO
    assert [r for r in caplog.records if own in r.getMessage()] == []
