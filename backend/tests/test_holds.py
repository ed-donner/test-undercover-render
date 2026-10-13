"""Holding an approval the Gateway refused to pay, for a handler's sign-off."""

import pytest

from backend.agent_api import OPERATIONS
from backend.tests.claim_requests import (
    GATEWAY_REFUSAL,
    decide,
    hold,
    pay,
    sign_off,
    start,
)
from backend.tests.settings_requests import change_settings


@pytest.fixture
def approved(client):
    """CLM-1002 approved at $1,500.00 under a limit raised to $2,000, unpaid."""
    change_settings(client, approval_limit=2000.0)
    start(client, "CLM-1002")
    decide(client, "CLM-1002", "approve", 1500.0)


@pytest.mark.usefixtures("approved")
def test_a_hold_waits_for_sign_off_with_the_gateways_reason(client):
    response = hold(client, "CLM-1002")
    assert response.status_code == 200
    claim = response.json()
    assert (claim["status"], claim["payment"]) == ("waiting_for_sign_off", None)
    assert claim["decision"]["gateway_refusal"] == GATEWAY_REFUSAL
    assert hold(client, "CLM-1002").json() == claim


@pytest.mark.usefixtures("approved")
def test_a_held_payment_is_paid_by_the_sign_off(client):
    hold(client, "CLM-1002")
    claim = sign_off(client, "CLM-1002").json()
    assert claim["status"] == "decided"
    assert claim["payment"]["amount"] == 1500.0
    assert claim["payment"]["signed_off_by"] == "Dana Whitfield"


def test_only_an_approved_unpaid_claim_is_held(client):
    waiting = hold(client, "CLM-1001")
    assert waiting.json()["detail"] == "Claim CLM-1001 has not been approved"
    start(client, "CLM-1001")
    assert hold(client, "CLM-1001").status_code == 409
    decide(client, "CLM-1001", "approve", 420.0)
    pay(client, "CLM-1001", 420.0)
    paid = hold(client, "CLM-1001")
    assert paid.json()["detail"] == "Claim CLM-1001 has already been paid"
    start(client, "CLM-1003")
    decide(client, "CLM-1003", "refer", 0)
    referred = hold(client, "CLM-1003")
    assert referred.status_code == 409
    assert referred.json()["detail"] == "Claim CLM-1003 has not been approved"
    assert hold(client, "CLM-9999").status_code == 404


def test_a_decision_with_no_hold_has_no_gateway_refusal(client):
    start(client, "CLM-1001")
    claim = decide(client, "CLM-1001", "decline", 0).json()
    assert claim["decision"]["gateway_refusal"] is None


def test_a_hold_needs_the_agents_key(dashboard):
    assert hold(dashboard, "CLM-1002").status_code == 401


def test_the_hold_stays_off_the_gateway():
    assert "hold_payment" not in OPERATIONS
