"""Starting dispatches and evaluations, which the backend asks the agent's service for
and records nothing of."""

import httpx
import pytest

from backend.agent_service import NO_ANSWER
from backend.database import runs
from backend.tests.rows import count
from backend.tests.sign_in import MARCUS, signed_in

RUNNING = "A dispatch is running"


def start_dispatch(client, agents):
    return client.post(
        "/api/dispatches", json={"agents": agents}, headers=signed_in(MARCUS)
    )


def test_start_a_dispatch(client, agent_calls):
    response = start_dispatch(client, 7)
    assert response.status_code == 202
    assert response.json() == {"status": "accepted"}
    assert agent_calls == [("/api/dispatches", {"agents": 7})]
    assert count(runs) == 0


def test_the_services_refusal_is_passed_on(client, agent_answers):
    agent_answers(lambda request: httpx.Response(409, json={"detail": RUNNING}))
    response = start_dispatch(client, 3)
    assert response.status_code == 409
    assert response.json()["detail"] == RUNNING


def test_a_service_that_isnt_running(client, agent_answers):
    def unreachable(request):
        raise httpx.ConnectError("Connection refused")

    agent_answers(unreachable)
    response = start_dispatch(client, 3)
    assert response.status_code == 503
    assert response.json()["detail"] == "The agent's service isn't running"
    assert count(runs) == 0


@pytest.mark.parametrize("agents", [0, 26])
def test_a_dispatch_has_1_to_25_claim_agents(client, agent_calls, agents):
    assert start_dispatch(client, agents).status_code == 422
    assert agent_calls == []


def test_any_other_failure_of_the_service_is_an_error(client, agent_answers):
    agent_answers(lambda request: httpx.Response(500, text="Internal Server Error"))
    with pytest.raises(httpx.HTTPStatusError):
        start_dispatch(client, 3)


def test_a_service_that_took_the_start_but_didnt_answer_isnt_said_to_be_down(
    client, agent_answers
):
    def slow(request):
        raise httpx.ReadTimeout("Timed out")

    agent_answers(slow)
    refused = start_dispatch(client, 3)
    assert (refused.status_code, refused.json()["detail"]) == (503, NO_ANSWER)
    assert "isn't running" not in NO_ANSWER


def start_evaluation(client, evaluation_set="held_out", tiny=True, agents=5):
    return client.post(
        "/api/evaluations",
        json={"evaluation_set": evaluation_set, "tiny": tiny, "agents": agents},
        headers=signed_in(MARCUS),
    )


def test_start_an_evaluation(client, agent_calls):
    response = start_evaluation(client, "evaluation", False, 25)
    assert response.status_code == 202
    assert agent_calls == [
        (
            "/api/evaluations",
            {"evaluation_set": "evaluation", "tiny": False, "agents": 25},
        )
    ]
    assert count(runs) == 0


def test_an_evaluation_is_refused_as_a_dispatch_is(client, agent_answers):
    agent_answers(lambda request: httpx.Response(409, json={"detail": RUNNING}))
    refused = start_evaluation(client)
    assert (refused.status_code, refused.json()["detail"]) == (409, RUNNING)

    def unreachable(request):
        raise httpx.ConnectError("Connection refused")

    agent_answers(unreachable)
    down = start_evaluation(client)
    assert down.status_code == 503
    assert down.json()["detail"] == "The agent's service isn't running"


@pytest.mark.parametrize(
    ("evaluation_set", "agents"), [("harder", 5), ("held_out", 0), ("held_out", 26)]
)
def test_an_evaluation_needs_a_known_set_and_1_to_25_agents(
    client, agent_calls, evaluation_set, agents
):
    assert start_evaluation(client, evaluation_set, agents=agents).status_code == 422
    assert agent_calls == []
