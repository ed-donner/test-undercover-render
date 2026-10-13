from sqlalchemy import select

from backend import seed
from backend.database import engine, handler_decisions
from backend.tests.run_requests import create_evaluation, finish, queue


def test_list_claims(client):
    claims = client.get("/api/claims").json()
    assert len(claims) == 26
    assert [claim["claim_id"] for claim in claims] == sorted(
        claim["claim_id"] for claim in claims
    )
    assert {claim["status"] for claim in claims} == {"waiting"}
    assert claims[0] == {
        "claim_id": "CLM-1001",
        "customer_name": "Maya Patel",
        "claim_type": "trip_delay",
        "summary": "Flight home canceled by the airline, rebooked the next morning",
        "amount_claimed": 420.0,
        "submitted_on": "2026-06-24",
        "status": "waiting",
        "decision": None,
        "payout": None,
        "resuming": False,
    }


def test_get_claim(client):
    claim = client.get("/api/claims/CLM-1001").json()
    assert claim["customer_name"] == "Maya Patel"
    assert claim["story"].startswith("My flight home from Rome")
    assert len(claim["items"]) == 3
    assert len(claim["documents"]) == 4
    assert claim["status"] == "waiting"
    assert claim["decision"] is None
    assert claim["payment"] is None


def test_get_policy(client):
    policy = client.get("/api/policies/POL-2001").json()
    assert policy["plan"] == "premium"
    assert policy["add_ons"] == []
    assert policy["trip"]["destination"] == "Rome, Italy"
    assert policy["trip"]["returns_on"] == "2026-06-18"


def test_get_claim_history_leaves_out_personal_details(client):
    response = client.get("/api/customers/CUS-3001/claims")
    history = response.json()
    assert [claim["claim_id"] for claim in history] == ["CLM-0412"]
    for field in ("email", "phone", "address", "date_of_birth"):
        assert field not in response.text


def test_unknown_ids(client):
    for path in (
        "/api/claims/CLM-9999",
        "/api/policies/POL-9999",
        "/api/customers/CUS-9999/claims",
    ):
        response = client.get(path)
        assert response.status_code == 404
        assert "9999 not found" in response.json()["detail"]


def test_seed_command(capsys):
    seed.main()
    assert capsys.readouterr().out == (
        "Seeded 26 claims, 51 policies, 50 customers and 3 handlers "
        "into undercover.db, with 25 held-out claims and 50 handlers' decisions "
        "for evaluations, and version 1 of the configuration and of the recipe\n"
    )


def test_the_security_teams_claim_waits_in_the_queue(client):
    claim = client.get("/api/claims/CLM-1901").json()
    assert (claim["status"], claim["policy_id"], claim["customer_id"]) == (
        "waiting",
        "POL-2901",
        "CUS-3901",
    )
    assert client.get("/api/policies/POL-2901").status_code == 200
    assert client.get("/api/customers/CUS-3901/claims").status_code == 200
    [listed] = [c for c in queue(client) if c["claim_id"] == "CLM-1901"]
    assert listed["customer_name"] == "Derek Vance"


def test_the_security_teams_claim_is_in_neither_evaluation_set(client):
    with engine().connect() as db:
        query = select(handler_decisions.c.claim_id)
        assert "CLM-1901" not in set(db.execute(query).scalars())
    for evaluation_set in ("evaluation", "held_out"):
        for tiny in (True, False):
            run = create_evaluation(client, evaluation_set, tiny).json()
            copied = [claim["claim_id"] for claim in run["claims"]]
            assert copied
            assert not [c for c in copied if c.startswith("CLM-1901")]
            finish(client, run["run_id"])
