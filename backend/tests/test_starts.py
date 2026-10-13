"""Starting dispatches and evaluations, which the app creates and asks the agent to
work."""

import pytest

from backend.database import runs
from backend.tests.rows import count, newest_run
from backend.tests.run_requests import (
    latest_dispatch,
    start_dispatch,
    start_evaluation,
)


def test_start_a_dispatch(client, agent_calls):
    response = start_dispatch(client, 7)
    assert response.status_code == 202
    assert response.json() == {"status": "accepted"}
    assert agent_calls == [{"operation": "work_run", "run_id": newest_run()}]
    dispatch = latest_dispatch(client)
    assert (dispatch["status"], dispatch["agents"], dispatch["version"]) == (
        "running",
        7,
        1,
    )


@pytest.mark.parametrize("agents", [0, 26])
def test_a_dispatch_has_1_to_25_claim_agents(client, agent_calls, agents):
    assert start_dispatch(client, agents).status_code == 422
    assert agent_calls == []
    assert count(runs) == 0


def test_start_an_evaluation(client, agent_calls):
    response = start_evaluation(client, "evaluation", False, 25)
    assert response.status_code == 202
    run_id = newest_run()
    assert agent_calls == [{"operation": "work_run", "run_id": run_id}]
    evaluation = client.get(f"/api/runs/{run_id}").json()
    assert (evaluation["kind"], evaluation["status"], evaluation["agents"]) == (
        "evaluation",
        "running",
        25,
    )
    assert len(evaluation["claims"]) == 25


@pytest.mark.parametrize(
    ("evaluation_set", "agents"), [("harder", 5), ("held_out", 0), ("held_out", 26)]
)
def test_an_evaluation_needs_a_known_set_and_1_to_25_agents(
    client, agent_calls, evaluation_set, agents
):
    assert start_evaluation(client, evaluation_set, agents=agents).status_code == 422
    assert agent_calls == []
