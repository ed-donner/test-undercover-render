import pytest

from backend import runs
from backend.tests.claim_requests import (
    decide,
    fail,
    pay,
    record_call,
    record_time,
    sign_off,
    start,
)
from backend.tests.dashboard_reads import read
from backend.tests.run_requests import (
    create_dispatch,
    dispatch_of,
    finish,
    latest_dispatch,
    record_claims,
)


def test_no_dispatch_yet(client):
    response = read(client, "/api/dispatches/latest")
    assert response.status_code == 200
    assert response.json() is None


def test_create_a_dispatch(client):
    dispatch = create_dispatch(client, 7).json()
    assert (dispatch["kind"], dispatch["status"], dispatch["agents"]) == (
        "dispatch",
        "running",
        7,
    )
    assert (dispatch["model"], dispatch["reasoning_effort"]) == (
        "openai/gpt-6-luna",
        "none",
    )
    assert (dispatch["evaluation_set"], dispatch["tiny"]) == (None, None)
    assert dispatch["number"] == 1
    assert dispatch["started_at"]
    assert (dispatch["finished_at"], dispatch["seconds"], dispatch["summary"]) == (
        None,
        None,
        None,
    )
    assert (dispatch["claims"], dispatch["model_cost"]) == ([], 0)
    assert latest_dispatch(client) == dispatch


@pytest.mark.parametrize("agents", [0, 26])
def test_a_dispatch_has_1_to_25_claim_agents(client, agents):
    assert create_dispatch(client, agents).status_code == 422
    assert latest_dispatch(client) is None


def test_record_the_claims_of_a_dispatch_in_order(client):
    run_id = create_dispatch(client).json()["run_id"]
    record_claims(client, run_id, "CLM-1008", "CLM-1001")
    dispatch = record_claims(client, run_id, "CLM-1011", "CLM-1001", "CLM-1008").json()
    assert [c["claim_id"] for c in dispatch["claims"]] == [
        "CLM-1011",
        "CLM-1001",
        "CLM-1008",
    ]
    assert latest_dispatch(client)["claims"] == dispatch["claims"]


def test_recording_claims_needs_a_running_dispatch_and_known_claims(client):
    unknown = record_claims(client, "run-9", "CLM-1001")
    assert unknown.status_code == 404
    assert unknown.json()["detail"] == "Run run-9 not found"
    run_id = create_dispatch(client).json()["run_id"]
    missing = record_claims(client, run_id, "CLM-1001", "CLM-9999")
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Claim CLM-9999 not found"
    finish(client, run_id)
    finished = record_claims(client, run_id, "CLM-1001")
    assert finished.status_code == 409
    assert finished.json()["detail"] == f"Run {run_id} is not running"


def test_each_claim_shows_where_it_stands_with_its_cost_and_time(client):
    run_id = dispatch_of(client, "CLM-1001", "CLM-1003")
    start(client, "CLM-1001")
    record_call(client, "CLM-1001", run_id, cost=0.004)
    record_call(client, "CLM-1001", run_id, cost=0.006)
    record_call(client, "CLM-1001", None, cost=0.5)
    record_time(client, "CLM-1001", run_id, seconds=20)
    record_time(client, "CLM-1001", run_id, seconds=21.5)
    decide(client, "CLM-1001", "approve", 420.0)
    pay(client, "CLM-1001", 420.0)

    dispatch = latest_dispatch(client)
    first, second = dispatch["claims"]
    assert (first["claim_id"], first["customer_name"], first["status"]) == (
        "CLM-1001",
        "Maya Patel",
        "decided",
    )
    assert (first["decision"], first["payout"]) == ("approve", 420.0)
    assert (first["seconds"], first["model_cost"]) == (41.5, pytest.approx(0.01))
    assert first["started_at"]
    assert (second["status"], second["decision"], second["started_at"]) == (
        "waiting",
        None,
        None,
    )
    assert (second["seconds"], second["model_cost"]) == (0, 0)
    assert dispatch["model_cost"] == pytest.approx(0.01)


def test_finishing_a_dispatch_sums_up_its_claims(client):
    started = ["CLM-1001", "CLM-1003", "CLM-1004", "CLM-1008", "CLM-1016"]
    started += ["CLM-1012", "CLM-1002", "CLM-1006"]
    run_id = dispatch_of(client, *started, "CLM-1005")
    for claim_id in started:
        start(client, claim_id)
    decide(client, "CLM-1001", "approve", 420.0)
    pay(client, "CLM-1001", 420.0)
    decide(client, "CLM-1003", "decline", 0)
    decide(client, "CLM-1004", "refer", 0)
    decide(client, "CLM-1008", "approve", 2240.0)
    fail(client, "CLM-1016")
    start(client, "CLM-1016")
    fail(client, "CLM-1016")
    decide(client, "CLM-1002", "approve", 1350.0)
    sign_off(client, "CLM-1002")
    decide(client, "CLM-1006", "approve", 300.0)

    dispatch = finish(client, run_id).json()
    assert dispatch["status"] == "finished"
    assert dispatch["finished_at"]
    assert dispatch["seconds"] >= 0
    # CLM-1002's sign-off paid it; CLM-1006's approval isn't paid yet.
    assert dispatch["summary"] == {
        "approved": 3,
        "declined": 1,
        "referred": 1,
        "waiting_for_sign_off": [{"claim_id": "CLM-1008", "payout": 2240.0}],
        "left_for_handler": ["CLM-1016"],
        "unfinished": ["CLM-1012", "CLM-1006", "CLM-1005"],
    }
    assert latest_dispatch(client) == dispatch
    again = finish(client, run_id)
    assert again.status_code == 409
    assert again.json()["detail"] == f"Run {run_id} is not running"


def test_finish_needs_a_known_run(client):
    unknown = finish(client, "run-9")
    assert unknown.status_code == 404
    assert unknown.json()["detail"] == "Run run-9 not found"


def test_stop_every_running_run(client):
    finished = create_dispatch(client).json()["run_id"]
    finish(client, finished)
    running = [create_dispatch(client).json()["run_id"] for _ in range(2)]
    response = client.post("/api/runs/stop")
    assert response.status_code == 200
    assert response.json() == running
    stopped = latest_dispatch(client)
    assert (stopped["run_id"], stopped["status"]) == (running[1], "stopped")
    assert (stopped["finished_at"], stopped["seconds"]) == (None, None)
    assert finish(client, running[0]).status_code == 409
    assert client.post("/api/runs/stop").json() == []


def test_runs_started_in_the_same_second_keep_their_order(client, monkeypatch):
    monkeypatch.setattr(runs, "now", lambda: "2026-10-02T12:00:00+00:00")
    first = create_dispatch(client).json()
    finish(client, first["run_id"])
    second = create_dispatch(client).json()
    assert second["number"] == first["number"] + 1
    assert latest_dispatch(client)["run_id"] == second["run_id"]
