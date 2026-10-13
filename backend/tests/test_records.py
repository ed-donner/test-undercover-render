"""A complete decision record, as claims manual section 14 asks: the calculation
of an approval's payout, who or what made the decision, when, and the manual's
version."""

import pytest
import yaml
from sqlalchemy import select

from backend.context_files import CONTEXT
from backend.database import calculations, decisions, engine
from backend.models import Decision
from backend.tests.claim_requests import (
    MAKER,
    decide,
    fail,
    line,
    record_decision,
    sign_off,
    start,
    work_out_payout,
)
from backend.tests.rows import count
from backend.tests.settings_requests import change_settings


def work_out(client, claim_id, amount=293.0):
    """Work out an emergency medical payout on a claim from one bill."""
    bill = line("Hospital bill", amount, "expense")
    return work_out_payout(client, claim_id, "emergency_medical", [bill])


def record(client, claim_id, **changes):
    """Ask to record an approval of $243.00 on a claim, unless told otherwise."""
    approval = {"decision": "approve", "payout": 243.0} | changes
    return record_decision(client, claim_id, **approval)


def kept(claim_id):
    """The calculations kept for a claim: none, or its latest."""
    with engine().connect() as db:
        query = select(calculations).where(calculations.c.claim_id == claim_id)
        return db.execute(query).mappings().all()


def test_the_latest_calculation_is_kept_for_the_claims_attempt(client):
    start(client, "CLM-1005")
    first = work_out(client, "CLM-1005", 293.0).json()
    assert [c["payout"] for c in kept("CLM-1005")] == [first["payout"]] == [243.0]
    work_out(client, "CLM-1005", 393.0)
    [calculation] = kept("CLM-1005")
    assert (calculation["thread_id"], calculation["payout"]) == ("t-1", 343.0)
    assert count(calculations) == 1


def test_a_new_attempt_starts_with_no_calculation(client):
    start(client, "CLM-1005")
    work_out(client, "CLM-1005")
    fail(client, "CLM-1005")
    client.post("/api/claims/CLM-1005/start", json={"thread_id": "t-2"})
    response = record(client, "CLM-1005")
    assert response.status_code == 422
    assert count(decisions) == 0
    assert response.json()["detail"] == (
        "Claims manual section 14: an approval needs the calculation of its payout "
        "for this attempt. Work it out with calculate_payout"
    )


def test_only_a_claim_in_progress_has_its_payout_worked_out(client):
    start(client, "CLM-1005")
    fail(client, "CLM-1005")
    response = work_out(client, "CLM-1005")
    assert response.status_code == 409
    assert response.json()["detail"] == "Claim CLM-1005 is not in progress"


def test_a_repeated_approval_is_returned_before_its_calculation_is_checked(client):
    start(client, "CLM-1005")
    work_out(client, "CLM-1005")
    first = record(client, "CLM-1005").json()
    work_out(client, "CLM-1005", 593.0)
    again = record(client, "CLM-1005")
    assert again.status_code == 200
    assert again.json() == first


def test_a_claim_never_started_has_no_calculation(client):
    response = work_out(client, "CLM-1005")
    assert response.status_code == 409
    assert response.json()["detail"] == "Claim CLM-1005 has not been started"
    assert kept("CLM-1005") == []


@pytest.mark.parametrize(
    ("changes", "missing"),
    [
        ({"reason": " "}, "a decision record needs a reason in plain language"),
        ({"section": ""}, "a decision record needs the section relied on"),
        (
            {"decided_by": ""},
            "a decision record needs who or what made the decision",
        ),
        ({"payout": 0}, "an approval needs a payout above zero"),
        ({"payout": -5}, "an approval needs a payout above zero"),
        ({"payout": 0.004}, "an approval needs a payout above zero"),
        ({"decision": "decline"}, "a decline or a referral has a payout of zero"),
        ({"decision": "refer"}, "a decline or a referral has a payout of zero"),
    ],
)
@pytest.mark.parametrize("claim_id", ["CLM-1005", "CLM-9999"])
def test_a_record_that_falls_short_is_refused_before_the_claim_is_read(
    client, changes, missing, claim_id
):
    start(client, "CLM-1005")
    work_out(client, "CLM-1005")
    response = record(client, claim_id, **changes)
    assert response.status_code == 422
    assert response.json()["detail"] == f"Claims manual section 14: {missing}"
    assert count(decisions) == 0


def test_a_decision_outside_the_three_is_pydantics_refusal(client):
    start(client, "CLM-1005")
    response = record(client, "CLM-1005", decision="maybe")
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)


def test_an_approval_needs_the_calculations_payout(client):
    start(client, "CLM-1005")
    assert (
        record(client, "CLM-1005")
        .json()["detail"]
        .startswith("Claims manual section 14: an approval needs the calculation")
    )
    work_out(client, "CLM-1005")
    other = record(client, "CLM-1005", payout=250.0)
    assert other.status_code == 422
    assert other.json()["detail"] == (
        "Claims manual section 14: the payout must be the calculation's $243.00"
    )
    assert count(decisions) == 0


def test_a_complete_approval(client):
    start(client, "CLM-1005")
    calculation = work_out(client, "CLM-1005").json()
    decision = record(client, "CLM-1005").json()["decision"]
    assert decision["calculation"] == {
        "lines": calculation["calculation"],
        "payout": 243.0,
    }
    assert [line["step"] for line in decision["calculation"]["lines"]][-1] == (
        "Less the deductible"
    )
    assert decision["decided_by"] == MAKER
    assert decision["decided_at"]
    assert decision["manual_version"] == "2026.2"


@pytest.mark.parametrize("kind", ["decline", "refer"])
def test_a_decline_or_a_referral_holds_no_calculation(client, kind):
    start(client, "CLM-1003")
    decision = decide(client, "CLM-1003", kind, 0).json()["decision"]
    assert decision["calculation"] is None
    assert (decision["decided_by"], decision["manual_version"]) == (MAKER, "2026.2")


def test_a_sign_off_adds_who_signed_off_and_when(client):
    change_settings(client, approval_limit=100.0)
    start(client, "CLM-1005")
    work_out(client, "CLM-1005")
    record(client, "CLM-1005")
    decision = sign_off(client, "CLM-1005").json()["decision"]
    assert decision["signed_off_by"] == "Dana Whitfield"
    assert decision["signed_off_at"]
    assert decision["calculation"]["payout"] == 243.0


def test_the_record_holds_every_field_the_data_dictionary_names():
    dictionary = (CONTEXT / "data_dictionary.yaml").read_text(encoding="utf-8")
    [claim] = [
        r for r in yaml.safe_load(dictionary)["records"] if r["record"] == "claim"
    ]
    named = {
        field["field"].removeprefix("decision.")
        for field in claim["fields"]
        if field["field"].startswith("decision.")
    }
    assert named <= set(Decision.model_fields)
    assert {"calculation", "decided_by", "manual_version"} <= named
