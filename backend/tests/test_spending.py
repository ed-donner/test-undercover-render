"""A round's spending limit: its improver's calls, its evaluations' model calls and
the judge, an estimate before a version's evaluations, and no new claim once the
limit is spent."""

from backend.tests.claim_requests import record_call, start
from backend.tests.round_requests import (
    approved_change,
    create_round,
    improvement,
    improver_call,
    round_evaluation,
    round_path,
)
from backend.tests.run_requests import create_evaluation, finish, get_evaluation


def luna_at_two_tenths_of_a_cent_a_claim(client):
    """A finished evaluation on GPT-6 Luna whose claims cost $0.002 each."""
    run = create_evaluation(client).json()
    for copy in run["claims"]:
        start(client, copy["claim_id"])
        record_call(client, copy["claim_id"], run["run_id"], cost=0.002)
    finish(client, run["run_id"])


def test_an_evaluation_the_round_cant_afford_is_refused(client):
    luna_at_two_tenths_of_a_cent_a_claim(client)
    round_id = create_round(client).json()["round_id"]
    approved_change(client, round_id)
    improver_call(client, round_id, 0.40)

    refused = round_evaluation(client, round_id)
    assert (refused.status_code, refused.json()["detail"]) == (
        409,
        "The evaluations could cost about $0.15, and $0.10 of the round's limit "
        "is left",
    )
    verdict = client.post(f"{round_path(round_id)}/verdict").json()
    assert (verdict["verdict"], verdict["reason"]) == (
        "rolled_back",
        "the round couldn't afford to evaluate it",
    )


def test_a_model_with_no_runs_is_estimated_by_its_prices(client):
    luna_at_two_tenths_of_a_cent_a_claim(client)
    round_id = create_round(client).json()["round_id"]
    approved_change(
        client,
        round_id,
        model="google/gemini-3.5-flash-lite",
        reasoning_effort="minimal",
    )
    refused = round_evaluation(client, round_id)
    # Five times Luna's cost a claim: Gemini's output price is five times Luna's.
    assert refused.json()["detail"] == (
        "The evaluations could cost about $0.75, and $0.50 of the round's limit is left"
    )


def test_no_new_claim_starts_once_the_limit_is_spent(client):
    round_id = create_round(client).json()["round_id"]
    approved_change(client, round_id)
    run = round_evaluation(client, round_id).json()
    first, second = (copy["claim_id"] for copy in run["claims"][:2])
    start(client, first)
    improver_call(client, round_id, 0.30)
    record_call(client, first, run["run_id"], cost=0.20)

    refused = start(client, second)
    assert (refused.status_code, refused.json()["detail"]) == (
        409,
        "Round 1 has spent its limit of $0.50",
    )
    assert client.get(f"/api/claims/{second}").json()["status"] == "waiting"
    assert finish(client, run["run_id"]).json()["status"] == "stopped"
    assert get_evaluation(client, run["run_id"])["status"] == "stopped"
    verdict = client.post(f"{round_path(round_id)}/verdict").json()
    assert (verdict["verdict"], verdict["reason"]) == (
        "rolled_back",
        "its evaluations were stopped",
    )


def test_a_first_evaluation_cut_short_stops_the_round(client):
    round_id = create_round(client).json()["round_id"]
    run = round_evaluation(client, round_id).json()
    improver_call(client, round_id, 0.50)
    cut = finish(client, run["run_id"]).json()
    assert (cut["status"], cut["stopped_because"]) == (
        "stopped",
        "The spending limit cut short its first evaluations",
    )
    round_ = client.get(round_path(round_id)).json()
    assert round_["status"] == "stopped"
    [listed] = improvement(client)["rounds"]
    assert listed["stopped_because"] == (
        "The spending limit cut short its first evaluations"
    )
    assert listed["cost"] == 0.5
