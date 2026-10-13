"""The app's two routes to the agent: its AgentCore app's /invocations on the laptop,
with the agent's key, or its runtime on AgentCore Runtime through boto3; and what
the handler gets when the agent takes the work, refuses it, can't be reached, gives
an error answer or doesn't answer in time."""

import json

import httpx
import pytest
from botocore.exceptions import (
    ClientError,
    ConnectionClosedError,
    ConnectTimeoutError,
    EndpointConnectionError,
    IncompleteReadError,
    NoCredentialsError,
    NoRegionError,
    ParamValidationError,
    ProxyConnectionError,
    ReadTimeoutError,
)

from backend import agent_service, runtime_calls
from backend.agent_service import NO_ANSWER, NOT_RUNNING
from backend.tests.agent_answers import answering, raising
from backend.tests.claim_requests import held, sign_off
from backend.tests.rows import newest_run
from backend.tests.run_requests import start_dispatch
from backend.tests.runtime_stand_in import ENDPOINT, runtime_at

ARN = "arn:aws:bedrock-agentcore:us-east-1:123456789012:runtime/undercover_agent-x"
REFUSAL = "A dispatch is running"


@pytest.fixture
def runtime(monkeypatch):
    """Send the agent's work to a stand-in for its runtime on AgentCore Runtime."""
    return runtime_at(monkeypatch, agent_service.RUNTIME, ARN)


def test_the_laptop_route_posts_the_payload_to_invocations_with_the_key(
    client, agent_answers, agent_key
):
    sent = []

    def accept(request):
        sent.append(request)
        return httpx.Response(200, json={"accepted": True})

    agent_answers(accept)
    assert start_dispatch(client).status_code == 202
    [request] = sent
    assert str(request.url) == "http://127.0.0.1:8080/invocations"
    assert request.headers["Authorization"] == f"Bearer {agent_key}"
    assert json.loads(request.content) == {
        "operation": "work_run",
        "run_id": newest_run(),
    }
    assert set(request.extensions["timeout"].values()) == {10}


def test_the_laptop_route_is_at_undercover_agent(client, agent_answers, monkeypatch):
    sent = []

    def accept(request):
        sent.append(str(request.url))
        return httpx.Response(200, json={"accepted": True})

    agent_answers(accept)
    monkeypatch.setenv("UNDERCOVER_AGENT", "http://agent.example.com:9000")
    assert start_dispatch(client).status_code == 202
    assert sent == ["http://agent.example.com:9000/invocations"]


def test_the_runtime_route_sends_the_payload_to_the_runtime_with_no_key(
    client, runtime, agent_calls
):
    assert start_dispatch(client).status_code == 202
    agent_service.resume_claim("CLM-1001")
    first, second = runtime.calls
    assert first["agentRuntimeArn"] == ARN
    assert json.loads(first["payload"]) == {
        "operation": "work_run",
        "run_id": newest_run(),
    }
    assert set(first) == {"agentRuntimeArn", "runtimeSessionId", "payload"}
    assert len(first["runtimeSessionId"]) >= 33
    assert first["runtimeSessionId"] != second["runtimeSessionId"]
    assert agent_calls == []


FOUR_OPERATIONS = [
    {"operation": "work_run", "run_id": "run-1"},
    {"operation": "work_round", "round_id": "round-1"},
    {"operation": "carry_round_on", "round_id": "round-1", "proposal_id": "proposal-1"},
    {"operation": "resume_claim", "claim_id": "CLM-1001"},
]


def ask_all_four():
    agent_service.work_run("run-1")
    agent_service.work_round("round-1")
    agent_service.carry_round_on("round-1", "proposal-1")
    agent_service.resume_claim("CLM-1001")


def test_the_agents_four_operations_on_the_laptop(agent_calls):
    ask_all_four()
    assert agent_calls == FOUR_OPERATIONS


def test_the_agents_four_operations_on_runtime_each_in_a_new_session(runtime):
    ask_all_four()
    assert [json.loads(call["payload"]) for call in runtime.calls] == FOUR_OPERATIONS
    assert len({call["runtimeSessionId"] for call in runtime.calls}) == 4


def test_the_runtime_client_makes_one_attempt_and_waits_2_seconds_and_15():
    runtime_calls.runtime_client.cache_clear()
    try:
        made = runtime_calls.runtime_client()
        assert made.meta.service_model.service_name == "bedrock-agentcore"
        config = made.meta.config
        assert config.retries["total_max_attempts"] == 1
        assert (config.connect_timeout, config.read_timeout) == (2, 15)
    finally:
        runtime_calls.runtime_client.cache_clear()


@pytest.mark.parametrize(
    ("answer", "status", "detail"),
    [
        (answering(200, b'{"accepted": true}'), 202, None),
        (answering(200, json.dumps({"refused": REFUSAL}).encode()), 409, REFUSAL),
        (raising(httpx.ConnectError("Connection refused")), 503, NOT_RUNNING),
        (raising(httpx.ConnectTimeout("Timed out")), 503, NOT_RUNNING),
        (raising(httpx.PoolTimeout("No connection free")), 503, NOT_RUNNING),
        (raising(httpx.ProxyError("The proxy refused")), 503, NOT_RUNNING),
        (
            answering(500, b'{"error": "The agent couldn\'t get ready: Boom"}'),
            502,
            "The agent couldn't take the work: The agent couldn't get ready: Boom",
        ),
        (
            answering(401, b'{"error": "This needs the agent\'s API key"}'),
            502,
            "The agent couldn't take the work: This needs the agent's API key",
        ),
        (raising(httpx.ReadTimeout("Timed out")), 503, NO_ANSWER),
        (raising(httpx.RemoteProtocolError("Cut off")), 503, NO_ANSWER),
    ],
)
def test_on_the_laptop_route(client, agent_answers, answer, status, detail):
    agent_answers(answer)
    response = start_dispatch(client)
    assert response.status_code == status
    if detail:
        assert response.json()["detail"] == detail


@pytest.mark.parametrize(
    ("given", "status", "detail"),
    [
        ({}, 202, None),
        (
            {"answer": (200, json.dumps({"refused": REFUSAL}).encode())},
            409,
            REFUSAL,
        ),
        ({"raises": EndpointConnectionError(endpoint_url=ENDPOINT)}, 503, NOT_RUNNING),
        ({"raises": ConnectTimeoutError(endpoint_url=ENDPOINT)}, 503, NOT_RUNNING),
        ({"raises": ProxyConnectionError(proxy_url=ENDPOINT)}, 503, NOT_RUNNING),
        (
            {
                "raises": ClientError(
                    {"Error": {"Code": "AccessDeniedException", "Message": "Denied"}},
                    "InvokeAgentRuntime",
                )
            },
            502,
            "The agent couldn't take the work: Denied",
        ),
        ({"raises": NoCredentialsError()}, 503, NOT_RUNNING),
        ({"raises": NoRegionError()}, 503, NOT_RUNNING),
        ({"raises": ParamValidationError(report="Bad payload")}, 503, NOT_RUNNING),
        ({"raises": ReadTimeoutError(endpoint_url=ENDPOINT)}, 503, NO_ANSWER),
        ({"raises": ConnectionClosedError(endpoint_url=ENDPOINT)}, 503, NO_ANSWER),
        (
            {"cut_off": IncompleteReadError(actual_bytes=4, expected_bytes=20)},
            503,
            NO_ANSWER,
        ),
    ],
)
def test_on_the_runtime_route(client, runtime, given, status, detail):
    for name, value in given.items():
        setattr(runtime, name, value)
    response = start_dispatch(client)
    assert response.status_code == status
    if detail:
        assert response.json()["detail"] == detail


@pytest.mark.parametrize("status", [400, 500])
@pytest.mark.parametrize(
    "body",
    [
        b'{"error": "agents: Input should be less than or equal to 25"}',
        b'{"accepted": true}',
        json.dumps({"refused": REFUSAL}).encode(),
    ],
)
def test_on_runtime_an_error_status_is_an_error_answer_whatever_the_body(
    client, runtime, status, body
):
    runtime.answer = (status, body)
    response = start_dispatch(client)
    assert response.status_code == 502
    assert response.json()["detail"].startswith("The agent couldn't take the work: ")


NEITHER = [b'{"accepted": false}', b'{"status": "accepted"}', b"Accepted", b"[]"]


@pytest.mark.parametrize("body", NEITHER)
def test_on_the_laptop_an_answer_neither_accepted_nor_refused_is_an_error(
    client, agent_answers, body
):
    agent_answers(answering(200, body))
    response = start_dispatch(client)
    assert response.status_code == 502
    assert response.json()["detail"].startswith("The agent couldn't take the work: ")


@pytest.mark.parametrize("body", NEITHER)
def test_on_runtime_an_answer_neither_accepted_nor_refused_is_an_error(
    client, runtime, body
):
    runtime.answer = (200, body)
    response = start_dispatch(client)
    assert response.status_code == 502
    assert response.json()["detail"].startswith("The agent couldn't take the work: ")


def test_a_sign_off_on_the_runtime_route_asks_to_resume_the_claim(client, runtime):
    held(client, "CLM-1008", 2240.0)
    assert sign_off(client, "CLM-1008").status_code == 200
    [call] = runtime.calls
    assert json.loads(call["payload"]) == {
        "operation": "resume_claim",
        "claim_id": "CLM-1008",
    }
