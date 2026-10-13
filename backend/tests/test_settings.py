"""The platform's settings, kept as a history of changes."""

import pytest

from backend.database import (
    engine,
    load,
    models_allowed,
    payments,
    payout_rules,
    seed,
    settings,
)
from backend.tests.claim_requests import decide, pay, sign_off, start
from backend.tests.dashboard_reads import settings_page
from backend.tests.rows import count
from backend.tests.settings_requests import STARTING, change_settings
from backend.tests.sign_in import MARCUS


def test_seeding_makes_the_first_settings_and_the_models_allowed(client):
    page = settings_page(client)
    current = page["current"]
    assert {key: current[key] for key in STARTING} == STARTING
    assert (current["number"], current["changed_by"]) == (1, None)
    assert [c["number"] for c in page["changes"]] == [1]
    assert page["models_allowed"] == load("models.json")
    assert (count(payout_rules), count(models_allowed)) == (1, 3)


def test_a_student_on_a_free_model_has_only_that_model(client, monkeypatch):
    monkeypatch.setenv("MODEL_NAME", "openrouter/free")
    seed(engine())
    assert settings_page(client)["models_allowed"] == [
        {
            "model": "openrouter/free",
            "reasoning_efforts": ["default"],
            "input_price": 0.0,
            "output_price": 0.0,
        }
    ]


def test_a_senior_handler_changes_the_settings(client):
    response = change_settings(client, spending_limit=0.75)
    assert response.status_code == 200
    page = settings_page(client)
    current = page["current"]
    assert (current["number"], current["spending_limit"]) == (2, 0.75)
    assert current["changed_by"] == "Dana Whitfield"
    assert current["changed_at"]
    assert [c["number"] for c in page["changes"]] == [2, 1]
    assert page["changes"][1]["spending_limit"] == 0.5


def test_a_handler_who_cant_sign_off_over_the_limit_cant_change_them(client):
    response = change_settings(client, MARCUS, spending_limit=0.75)
    assert response.status_code == 403
    assert response.json()["detail"] == (
        "Only a handler who can sign off payouts over $1,000.00 can change the "
        "settings. Marcus Oyelaran can't."
    )
    assert count(settings) == 1
    unsigned = client.put("/api/settings", json=STARTING)
    assert unsigned.status_code == 401


@pytest.mark.parametrize(
    "values",
    [
        {"approval_limit": 0},
        {"objectives": {"accuracy": 1.5, "grade": 1.0}},
        {"objectives": {"accuracy": 0.6, "grade": 4}},
        {"noise": STARTING["noise"] | {"grade": -0.1}},
        {"spending_limit": 0},
        {"agents": 26},
    ],
)
def test_settings_out_of_range_are_refused(client, values):
    assert change_settings(client, **values).status_code == 422
    assert count(settings) == 1


def test_a_new_approval_limit_applies_to_the_decisions_after_it(client):
    start(client, "CLM-1002")
    held = decide(client, "CLM-1002", "approve", 1350.0).json()
    assert held["status"] == "waiting_for_sign_off"
    change_settings(client, approval_limit=1500.0)

    start(client, "CLM-1003")
    assert decide(client, "CLM-1003", "approve", 1350.0).json()["status"] == (
        "in_progress"
    )
    assert pay(client, "CLM-1003", 1350.0).json()["status"] == "decided"
    assert client.get("/api/claims/CLM-1002").json()["status"] == (
        "waiting_for_sign_off"
    )


def test_a_lower_approval_limit_holds_smaller_payouts(client):
    change_settings(client, approval_limit=500.0)
    start(client, "CLM-1001")
    held = decide(client, "CLM-1001", "approve", 600.0).json()
    assert held["status"] == "waiting_for_sign_off"
    refused = pay(client, "CLM-1001", 600.0)
    assert refused.status_code == 403
    assert refused.json()["detail"] == (
        "A payout over $500.00 needs a handler's sign-off"
    )


def test_a_payout_held_names_the_limit_it_was_held_under(client):
    start(client, "CLM-1002")
    decide(client, "CLM-1002", "approve", 1350.0)
    change_settings(client, approval_limit=1500.0)
    refused = pay(client, "CLM-1002", 1350.0)
    assert refused.json()["detail"] == (
        "A payout over $1,000.00 needs a handler's sign-off"
    )
    paid = sign_off(client, "CLM-1002").json()
    assert (paid["status"], paid["payment"]["amount"]) == ("decided", 1350.0)
    assert count(payments) == 1


def test_a_lower_limit_holds_an_approval_not_yet_paid(client):
    """A known gap: the payment checks the limit in force before it reads the
    claim, and only a payout held when it was decided can be signed off, so an
    approval left unpaid when the limit drops below it waits for a handler."""
    start(client, "CLM-1001")
    decide(client, "CLM-1001", "approve", 420.0)
    change_settings(client, approval_limit=300.0)
    assert pay(client, "CLM-1001", 420.0).status_code == 403
    assert sign_off(client, "CLM-1001").status_code == 409
    assert client.get("/api/claims/CLM-1001").json()["status"] == "in_progress"
