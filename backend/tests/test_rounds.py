"""A round of the improver as the agent's service records it, and the business's
rules the backend keeps whatever the improver does."""

import pytest
from sqlalchemy import select

from backend.database import INSTRUCTIONS, engine, recipes
from backend.tests.dashboard_reads import configuration, version_details
from backend.tests.round_requests import (
    ALL,
    CHANGE,
    approved_change,
    create_round,
    decide_copies,
    improvement,
    improver_call,
    play_out,
    propose_change,
    propose_recipe,
    review,
    round_evaluation,
    round_path,
    stop_round,
)
from backend.tests.run_requests import create_evaluation, finish, get_evaluation
from backend.tests.settings_requests import change_settings

RECIPE_MD = (INSTRUCTIONS / "recipe.md").read_text(encoding="utf-8")
IMPROVER_MD = (INSTRUCTIONS / "improver.md").read_text(encoding="utf-8")


def test_seeding_makes_the_first_recipe():
    with engine().connect() as db:
        rows = db.execute(select(recipes)).mappings().all()
    assert [(row["number"], row["recipe"]) for row in rows] == [(1, RECIPE_MD)]


def test_a_round_is_recorded_to_what_is_in_force(client):
    created = create_round(client)
    assert created.status_code == 200
    round_ = created.json()
    assert (round_["number"], round_["status"]) == (1, "open")
    assert (round_["improver_model"], round_["improver_reasoning_effort"]) == (
        "openai/gpt-6.1-sol",
        "medium",
    )
    assert round_["first_evaluations"] == ["evaluation", "held_out", "held_out"]
    assert round_["instructions"] == f"{IMPROVER_MD}\n{RECIPE_MD}"
    assert [m["model"] for m in round_["models_allowed"]][0] == "openai/gpt-6-luna"
    assert client.get(round_path(round_["round_id"])).json() == round_


def test_a_student_on_a_free_model_has_it_for_the_improver(client, monkeypatch):
    monkeypatch.setenv("MODEL_NAME", "openrouter/free")
    round_ = create_round(client).json()
    assert (round_["improver_model"], round_["improver_reasoning_effort"]) == (
        "openrouter/free",
        "default",
    )


def test_one_round_is_open_at_a_time(client):
    create_round(client)
    refused = create_round(client)
    assert (refused.status_code, refused.json()["detail"]) == (
        409,
        "Round 1 is open. Finish or stop it first.",
    )


def test_a_proposal_changes_nothing_until_a_handler_approves_it(client):
    round_id = create_round(client).json()["round_id"]
    before = configuration(client)
    proposal = propose_change(client, round_id).json()
    assert proposal["review"] is None
    assert configuration(client) == before
    refused = client.post(f"{round_path(round_id)}/version")
    assert (refused.status_code, refused.json()["detail"]) == (
        409,
        "No change has been approved in round 1",
    )

    reviewed = review(client, round_id, proposal["proposal_id"]).json()
    assert (reviewed["review"], reviewed["reviewed_by"]) == (
        "approved",
        "Dana Whitfield",
    )
    made = client.post(f"{round_path(round_id)}/version").json()
    assert made == {"number": 2}
    two = version_details(client, 2)
    assert (two["status"], two["reason"]) == ("under_test", CHANGE["reason"])
    assert (two["proposed_by"], two["approved_by"]) == ("Round 1", "Dana Whitfield")
    assert client.get("/api/versions/current").json()["number"] == 1
    assert client.post(f"{round_path(round_id)}/version").json() == {"number": 2}


def test_a_model_outside_the_models_allowed_is_never_proposed(client):
    round_id = create_round(client).json()["round_id"]
    refused = propose_change(
        client, round_id, model="openai/gpt-7", reasoning_effort="high"
    )
    assert (refused.status_code, refused.json()["detail"]) == (
        422,
        "openai/gpt-7 at high isn't allowed. Choose from the models allowed.",
    )
    assert improvement(client)["round"]["waiting"] is None


def test_a_second_change_waits_for_the_approved_one_to_become_a_version(client):
    round_id = create_round(client).json()["round_id"]
    proposal = propose_change(client, round_id).json()
    review(client, round_id, proposal["proposal_id"])
    refused = propose_change(client, round_id)
    assert (refused.status_code, refused.json()["detail"]) == (
        409,
        "Round 1 has a change approved",
    )


def test_a_round_chooses_each_evaluations_set(client):
    change_settings(client, spending_limit=10.0)
    round_id = create_round(client).json()["round_id"]
    first = [play_out(client, round_id)["evaluation_set"] for _ in range(3)]
    approved_change(client, round_id)
    tried = [play_out(client, round_id)["evaluation_set"] for _ in range(3)]
    assert first == tried == ["evaluation", "held_out", "held_out"]


def test_only_a_senior_handler_reviews_a_proposal(client):
    round_id = create_round(client).json()["round_id"]
    proposal = propose_change(client, round_id).json()
    refused = review(client, round_id, proposal["proposal_id"], handler_id="HND-02")
    assert (refused.status_code, refused.json()["detail"]) == (
        403,
        "Only a handler who can sign off payouts over $1,000.00 can approve or "
        "reject the improver's proposals. Marcus Oyelaran can't.",
    )


def test_one_proposal_waits_at_a_time_and_a_rejection_needs_a_reason(client):
    round_id = create_round(client).json()["round_id"]
    proposal = propose_change(client, round_id).json()
    assert propose_change(client, round_id).status_code == 409
    no_reason = client.post(
        f"{round_path(round_id)}/proposals/{proposal['proposal_id']}/review",
        json={"review": "rejected", "handler_id": "HND-01", "reason": " "},
    )
    assert no_reason.status_code == 422
    rejected = review(client, round_id, proposal["proposal_id"], "rejected").json()
    assert rejected["rejection_reason"] == "Keep each rule general"
    assert propose_change(client, round_id).status_code == 200


def test_a_round_keeps_its_settings_when_they_change(client):
    round_id = create_round(client).json()["round_id"]
    change_settings(client, spending_limit=0.75, agents=5)
    run = round_evaluation(client, round_id).json()
    assert run["agents"] == 25
    [listed] = improvement(client)["rounds"]
    assert (listed["settings"], listed["spending_limit"]) == (1, 0.5)


def test_a_round_stopped_before_its_verdict_leaves_the_current_version(client):
    round_id = create_round(client).json()["round_id"]
    copy = round_evaluation(client, round_id).json()["claims"][0]["claim_id"]
    approved_change(client, round_id)
    stopped = stop_round(client, round_id)
    assert stopped.status_code == 200
    assert (stopped.json()["status"], stopped.json()["stopped_by"]) == (
        "stopped",
        "Dana Whitfield",
    )
    assert client.get("/api/versions/current").json()["number"] == 1
    two = version_details(client, 2)
    assert (two["status"], two["verdict_reason"]) == (
        "rolled_back",
        "the round was stopped before its verdict",
    )

    refusals = [
        propose_change(client, round_id),
        propose_recipe(client, round_id),
        review(client, round_id, "any-proposal"),
        client.post(f"{round_path(round_id)}/version"),
        client.post(f"{round_path(round_id)}/recipe"),
        round_evaluation(client, round_id),
        client.post(f"{round_path(round_id)}/verdict"),
        improver_call(client, round_id, 0.01),
        client.post(f"{round_path(round_id)}/finish"),
        client.post(f"/api/claims/{copy}/start", json={"thread_id": "late"}),
    ]
    assert [r.status_code for r in refusals] == [409] * len(refusals)
    assert {r.json()["detail"] for r in refusals} == {"Round 1 is stopped"}


def kept_version_2(client, round_id):
    """Play a round out to a verdict that keeps version 2: version 1 gets every
    held-out claim wrong, and version 2 decides each as the handlers did."""
    for _ in range(3):
        play_out(client, round_id)
    approved_change(client, round_id)
    for _ in range(3):
        play_out(client, round_id, right=ALL)
    return client.post(f"{round_path(round_id)}/verdict")


def test_a_kept_version_becomes_the_current_version(client):
    change_settings(client, spending_limit=10.0)
    round_id = create_round(client).json()["round_id"]
    verdict = kept_version_2(client, round_id)
    assert verdict.status_code == 200
    result = verdict.json()
    assert (result["verdict"], result["reason"]) == ("kept", "accuracy improved")
    assert result["summary"] == (
        "Kept version 2: accuracy improved. Version 2 is now the current version."
    )
    assert result["scores"]["held_out_after"]["accuracy"] == 1.0
    assert result["scores"]["held_out_before"]["accuracy"] < 0.5
    assert client.get("/api/versions/current").json()["number"] == 2

    stop_round(client, round_id)
    assert client.get("/api/versions/current").json()["number"] == 2


def test_a_round_that_proposes_nothing_finishes_with_no_version(client):
    round_id = create_round(client).json()["round_id"]
    finished = client.post(f"{round_path(round_id)}/finish").json()
    assert finished["status"] == "finished"
    [listed] = improvement(client)["rounds"]
    assert (listed["status"], listed["version"]) == ("finished", None)


def test_a_version_the_improver_never_evaluated_is_rolled_back(client):
    round_id = create_round(client).json()["round_id"]
    approved_change(client, round_id)
    client.post(f"{round_path(round_id)}/finish")
    two = version_details(client, 2)
    assert (two["status"], two["verdict_reason"]) == (
        "rolled_back",
        "the improver didn't evaluate it",
    )


def test_stopping_rounds_leaves_one_waiting_for_a_handler(client):
    round_id = create_round(client).json()["round_id"]
    proposal = propose_change(client, round_id).json()
    assert client.post("/api/rounds/stop", json={"reason": "Restarted"}).json() == []
    assert client.get(round_path(round_id)).json()["status"] == "open"

    review(client, round_id, proposal["proposal_id"], "rejected")
    stopped = client.post("/api/rounds/stop", json={"reason": "Restarted"}).json()
    assert stopped == [round_id]
    [listed] = improvement(client)["rounds"]
    assert (listed["status"], listed["stopped_because"]) == ("stopped", "Restarted")


def test_a_versions_held_out_scores_average_only_its_rounds_finished_evaluations(
    client,
):
    change_settings(client, spending_limit=10.0)
    first = create_round(client).json()["round_id"]
    play_out(client, first)
    at_60 = play_out(client, first, right=15)
    stopped = play_out(client, first, finish=False)
    stop_round(client, first)
    assert finish(client, stopped["run_id"]).json()["status"] == "stopped"
    scoreboard = create_evaluation(client, tiny=False).json()
    decide_copies(client, scoreboard, 5)
    finish(client, scoreboard["run_id"])

    second = create_round(client).json()
    assert second["first_evaluations"] == ["held_out"]
    at_72 = play_out(client, second["round_id"], right=18)

    accuracies = [
        get_evaluation(client, run["run_id"])["measures"]["accuracy"]
        for run in (at_60, at_72, scoreboard)
    ]
    assert accuracies == [0.6, 0.72, 0.2]
    [version_1] = configuration(client)["versions"]
    assert version_1["scores"]["held_out"]["accuracy"] == pytest.approx(0.66)


def test_a_round_runs_only_the_evaluations_its_versions_need(client):
    change_settings(client, spending_limit=10.0)
    round_id = create_round(client).json()["round_id"]
    for _ in range(3):
        play_out(client, round_id)
    refused = round_evaluation(client, round_id)
    assert (refused.status_code, refused.json()["detail"]) == (
        409,
        "Round 1 has run every evaluation version 1 needs",
    )

    approved_change(client, round_id)
    for _ in range(3):
        play_out(client, round_id, right=ALL)
    refused = round_evaluation(client, round_id)
    assert refused.json()["detail"] == (
        "Round 1 has run every evaluation version 2 needs"
    )
    client.post(f"{round_path(round_id)}/verdict")
    refused = round_evaluation(client, round_id)
    assert (refused.status_code, refused.json()["detail"]) == (
        409,
        "Version 2 already has its verdict",
    )


def test_a_round_whose_version_already_has_evaluations_runs_none_first(client):
    change_settings(client, spending_limit=10.0)
    first = create_round(client).json()["round_id"]
    for _ in range(3):
        play_out(client, first)
    client.post(f"{round_path(first)}/finish")
    second = create_round(client).json()
    assert second["first_evaluations"] == []
    assert round_evaluation(client, second["round_id"]).status_code == 409


def test_a_stopped_round_shows_no_proposal_waiting(client):
    round_id = create_round(client).json()["round_id"]
    propose_change(client, round_id)
    stop_round(client, round_id)
    assert improvement(client)["round"]["waiting"] is None
