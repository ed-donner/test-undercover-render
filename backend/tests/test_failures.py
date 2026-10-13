from backend.tests.claim_requests import decide, fail, start
from backend.tests.dashboard_reads import steps_of


def test_starting_a_claim_counts_the_attempt(client):
    assert client.get("/api/claims/CLM-1004").json()["attempts"] == 0
    assert start(client, "CLM-1004").json()["attempts"] == 1


def test_a_failed_attempt_goes_back_in_the_queue(client):
    start(client, "CLM-1004")
    claim = fail(client, "CLM-1004").json()
    assert (claim["status"], claim["attempts"]) == ("waiting", 1)
    last = steps_of(client, "CLM-1004")[-1]
    assert (last["kind"], last["content"]) == ("error", "The model timed out")
    assert last["thread_id"] == "t-1"


def test_a_second_failure_leaves_the_claim_for_a_handler(client):
    start(client, "CLM-1004")
    fail(client, "CLM-1004")
    start(client, "CLM-1004")
    claim = fail(client, "CLM-1004", "The agent went round in circles").json()
    assert (claim["status"], claim["attempts"]) == ("left_for_handler", 2)
    assert start(client, "CLM-1004").status_code == 409
    assert decide(client, "CLM-1004", "decline", 0).status_code == 409
    queue = {c["claim_id"]: c for c in client.get("/api/claims").json()}
    assert queue["CLM-1004"]["status"] == "left_for_handler"
    errors = [
        s["content"] for s in steps_of(client, "CLM-1004") if s["kind"] == "error"
    ]
    assert errors == ["The model timed out", "The agent went round in circles"]


def test_failure_needs_a_claim_in_progress_without_a_decision(client):
    assert fail(client, "CLM-1001").status_code == 409
    start(client, "CLM-1001")
    decide(client, "CLM-1001", "approve", 420.0)
    response = fail(client, "CLM-1001")
    assert response.status_code == 409
    assert response.json()["detail"] == "Claim CLM-1001 has already been decided"
    claim = client.get("/api/claims/CLM-1001").json()
    assert (claim["status"], claim["attempts"]) == ("in_progress", 1)
    start(client, "CLM-1003")
    decide(client, "CLM-1003", "decline", 0)
    assert fail(client, "CLM-1003").status_code == 409
    start(client, "CLM-1002")
    decide(client, "CLM-1002", "approve", 1350.0)
    assert fail(client, "CLM-1002").status_code == 409
    assert client.get("/api/claims/CLM-1002").json()["status"] == (
        "waiting_for_sign_off"
    )
    assert steps_of(client, "CLM-1001") == []
    assert fail(client, "CLM-9999").status_code == 404


def test_failure_needs_a_reason(client):
    start(client, "CLM-1001")
    assert fail(client, "CLM-1001", "").status_code == 422
    assert client.get("/api/claims/CLM-1001").json()["status"] == "in_progress"
