"""The Improvement page's reads and actions, and what the improver reads."""

import json

import httpx
import pytest
from sqlalchemy import event, select

from backend.database import engine, handler_decisions, held_out_claims
from backend.tests.agent_answers import unreachable
from backend.tests.dashboard_reads import read, recipe
from backend.tests.judging import answer
from backend.tests.round_requests import (
    ALL,
    approved_change,
    create_round,
    handler_reasons,
    improvement,
    improver_call,
    play_out,
    propose_change,
    propose_recipe,
    review,
    round_path,
    stop_round,
)
from backend.tests.rows import newest_round
from backend.tests.settings_requests import change_settings
from backend.tests.sign_in import MARCUS, signed_in

ROUNDS = "/api/improvement/rounds"


def act(client, path, email=None, **body):
    headers = signed_in(email) if email else signed_in()
    return client.post(path, json=body or None, headers=headers)


def approval(round_id, proposal_id):
    return f"{ROUNDS}/{round_id}/proposals/{proposal_id}/approval"


def rejection(round_id, proposal_id):
    return f"{ROUNDS}/{round_id}/proposals/{proposal_id}/rejection"


def test_with_no_rounds_the_page_has_version_1_and_the_first_recipe(client):
    page = improvement(client)
    assert (page["round"], page["rounds"], page["versions_tried"]) == (None, [], [])
    assert page["first_version"] == {
        "number": 1,
        "verdict": None,
        "accuracy": None,
        "grade": None,
    }
    assert [r["number"] for r in page["recipes"]] == [1]
    assert page["recipes"][0]["current"] is True


def test_start_a_round(client, agent_calls):
    response = act(client, ROUNDS)
    assert response.status_code == 202
    round_id = newest_round()
    assert agent_calls == [{"operation": "work_round", "round_id": round_id}]
    round_ = client.get(f"/api/rounds/{round_id}").json()
    assert (round_["number"], round_["status"]) == (1, "open")
    assert improvement(client)["round"]["started_by"] == "Dana Whitfield"


def test_a_round_starts_only_when_none_is_open(client, agent_calls):
    round_id = create_round(client).json()["round_id"]
    propose_change(client, round_id)
    asked = list(agent_calls)
    refused = act(client, ROUNDS)
    assert (refused.status_code, refused.json()["detail"]) == (
        409,
        "Round 1 is open. Finish or stop it first.",
    )
    assert agent_calls == asked


@pytest.mark.parametrize(
    ("path", "action"),
    [
        (ROUNDS, "start a round"),
        (f"{ROUNDS}/round-1/stop", "stop a round"),
        (approval("round-1", "p-1"), "approve or reject the improver's proposals"),
        (rejection("round-1", "p-1"), "approve or reject the improver's proposals"),
    ],
)
def test_a_handler_who_cant_sign_off_over_the_limit_cant_run_the_improver(
    client, agent_calls, path, action
):
    refused = act(client, path, MARCUS, reason="Too broad")
    assert (refused.status_code, refused.json()["detail"]) == (
        403,
        f"Only a handler who can sign off payouts over $1,000.00 can {action}. "
        "Marcus Oyelaran can't.",
    )
    assert agent_calls == []


def test_an_approval_names_the_proposal_waiting(client, agent_calls):
    round_id = create_round(client).json()["round_id"]
    first = propose_change(client, round_id).json()["proposal_id"]
    review(client, round_id, first, "rejected")
    second = propose_change(client, round_id).json()["proposal_id"]
    agent_calls.clear()

    for path in (approval(round_id, first), rejection(round_id, first)):
        refused = act(client, path, reason="Too broad")
        assert (refused.status_code, refused.json()["detail"]) == (
            409,
            f"Proposal {first} isn't waiting for a handler: it was rejected",
        )
    assert agent_calls == []
    assert review(client, round_id, first).status_code == 409
    page = improvement(client)
    assert page["round"]["waiting"]["proposal_id"] == second

    approved = act(client, approval(round_id, second))
    assert approved.status_code == 202
    assert agent_calls == [
        {"operation": "carry_round_on", "round_id": round_id, "proposal_id": second}
    ]
    approved = client.get(f"/api/rounds/{round_id}/proposals/{second}").json()
    assert (approved["review"], approved["reviewed_by"]) == (
        "approved",
        "Dana Whitfield",
    )


def test_a_rejection_passes_its_reason_on(client, agent_calls):
    round_id = create_round(client).json()["round_id"]
    proposal = propose_change(client, round_id).json()["proposal_id"]
    path = rejection(round_id, proposal)
    assert act(client, path, reason="").status_code == 422
    assert act(client, path, reason="  ").status_code == 422
    assert act(client, path, reason=" Keep each rule general ").status_code == 202
    assert agent_calls[-1] == {
        "operation": "carry_round_on",
        "round_id": round_id,
        "proposal_id": proposal,
    }
    rejected = client.get(f"/api/rounds/{round_id}/proposals/{proposal}").json()
    assert (rejected["review"], rejected["rejection_reason"]) == (
        "rejected",
        "Keep each rule general",
    )


def test_a_proposal_of_another_round_isnt_found(client):
    first_round = create_round(client).json()["round_id"]
    proposal = propose_change(client, first_round).json()["proposal_id"]
    stop_round(client, first_round)
    second_round = create_round(client).json()["round_id"]
    propose_change(client, second_round)
    refused = act(client, approval(second_round, proposal))
    assert (refused.status_code, refused.json()["detail"]) == (
        404,
        f"Proposal {proposal} not found in round 2",
    )


def test_an_approval_with_the_agents_service_down(client, agent_answers):
    round_id = create_round(client).json()["round_id"]
    proposal = propose_change(client, round_id).json()["proposal_id"]
    agent_answers(unreachable)
    refused = act(client, approval(round_id, proposal))
    assert (refused.status_code, refused.json()["detail"]) == (
        503,
        "The agent's service isn't running",
    )


def stage(client):
    open_round = improvement(client)["round"]
    return open_round["stage"], open_round["progress"]


def whole_round(client, right, improver_cost, rejected=False):
    """Play out a round from start to finish: the improver's spending, the first
    evaluations the current version needs, a change rejected first if asked, an
    approved change whose evaluations get `right` claims right, a verdict and an
    approved recipe. Return the round's id."""
    round_ = create_round(client).json()
    round_id = round_["round_id"]
    improver_call(client, round_id, improver_cost)
    for _ in round_["first_evaluations"]:
        play_out(client, round_id)
    if rejected:
        proposal = propose_change(client, round_id).json()
        review(client, round_id, proposal["proposal_id"], "rejected")
    proposal = propose_change(client, round_id).json()
    review(client, round_id, proposal["proposal_id"])
    client.post(f"{round_path(round_id)}/version")
    for _ in range(3):
        play_out(client, round_id, right=right)
    client.post(f"{round_path(round_id)}/verdict")
    recipe = propose_recipe(client, round_id).json()
    review(client, round_id, recipe["proposal_id"])
    client.post(f"{round_path(round_id)}/recipe")
    client.post(f"{round_path(round_id)}/finish")
    return round_id


def queries_for_the_page(client):
    """Count the queries one load of the Improvement page makes."""
    statements = []

    def count(*_):
        statements.append(1)

    event.listen(engine(), "before_cursor_execute", count)
    try:
        improvement(client)
    finally:
        event.remove(engine(), "before_cursor_execute", count)
    return len(statements)


def test_each_round_on_the_page_is_its_own_in_as_many_queries_after_three(client):
    change_settings(client, spending_limit=10.0)
    first = whole_round(client, right=ALL, improver_cost=0.01)
    after_one = queries_for_the_page(client)
    change_settings(client, spending_limit=11.0)
    second = whole_round(client, right=0, improver_cost=0.02, rejected=True)
    change_settings(client, spending_limit=12.0)
    third = whole_round(client, right=ALL, improver_cost=0.03)

    assert queries_for_the_page(client) == after_one
    page = improvement(client)
    shown = {r["round_id"]: r for r in page["rounds"]}
    approved = [("change", "approved"), ("recipe", "approved")]
    expected = [
        (first, 10.0, 2, "kept", approved),
        (second, 11.0, 3, "rolled_back", [("change", "rejected"), *approved]),
        (third, 12.0, 4, "rolled_back", approved),
    ]
    for round_id, limit, version, verdict, reviews in expected:
        one = shown[round_id]
        assert (one["spending_limit"], one["version"], one["verdict"]) == (
            limit,
            version,
            verdict,
        )
        assert [(r["kind"], r["review"]) for r in one["reviews"]] == reviews
        # What the improver reads of the round's spending, one round at a time.
        spent = client.get(f"{round_path(round_id)}/results").json()["spending"]
        assert one["cost"] == pytest.approx(spent["spent"])
    assert [
        (v["number"], v["verdict"], v["accuracy"]) for v in page["versions_tried"]
    ] == [
        (2, "kept", 1.0),
        (3, "rolled_back", 0.0),
        (4, "rolled_back", 1.0),
    ]
    assert page["round"]["round_id"] == third


def test_the_page_follows_a_round_through_its_stages(client):
    change_settings(client, spending_limit=10.0)
    round_id = create_round(client).json()["round_id"]
    assert stage(client) == ("first_evaluations", "0 of 3")
    play_out(client, round_id)
    play_out(client, round_id)
    assert stage(client) == ("first_evaluations", "2 of 3")
    play_out(client, round_id)
    assert stage(client) == ("improving", None)

    proposal = propose_change(client, round_id).json()
    assert stage(client) == ("change_waiting", None)
    waiting = improvement(client)["round"]["waiting"]
    assert waiting["proposal_id"] == proposal["proposal_id"]
    assert (waiting["model_before"], waiting["model_after"]) == (
        "openai/gpt-6-luna",
        "openai/gpt-6-luna",
    )
    assert waiting["diff"]["added"] > 0

    review(client, round_id, proposal["proposal_id"])
    client.post(f"{round_path(round_id)}/version")
    assert stage(client) == ("evaluating", "0 of 3")
    play_out(client, round_id, right=ALL)
    assert stage(client) == ("evaluating", "1 of 3")
    play_out(client, round_id, right=ALL)
    play_out(client, round_id, right=ALL)
    client.post(f"{round_path(round_id)}/verdict")
    assert stage(client) == ("verdict", None)

    proposal = propose_recipe(client, round_id).json()
    assert stage(client) == ("recipe_waiting", None)
    assert improvement(client)["round"]["waiting"]["kind"] == "recipe"
    review(client, round_id, proposal["proposal_id"])
    assert client.post(f"{round_path(round_id)}/recipe").json() == {"number": 2}
    client.post(f"{round_path(round_id)}/finish")

    page = improvement(client)
    finished = page["round"]
    assert (finished["status"], finished["stage"], finished["verdict"]) == (
        "finished",
        None,
        "kept",
    )
    assert finished["held_out_after"]["accuracy"] == 1.0
    assert [r["kind"] for r in finished["reviews"]] == ["change", "recipe"]
    assert len(finished["evaluations"]) == 6
    assert [v["number"] for v in page["versions_tried"]] == [2]
    assert page["first_version"]["accuracy"] < 0.5
    assert [(r["number"], r["current"]) for r in page["recipes"]] == [
        (2, True),
        (1, False),
    ]
    two = recipe(client, 2)
    assert (two["proposed_by"], two["approved_by"]) == ("Round 1", "Dana Whitfield")
    assert two["diff"]["removed"] > 0
    assert read(client, "/api/improvement/recipes/9").status_code == 404


def held_out_texts():
    """Every held-out claim's id and summary, and the handlers' reasons on them.
    Their references, such as "Policy wording, section 5", are shared with the
    evaluation set."""
    with engine().connect() as db:
        claims = db.execute(select(held_out_claims)).mappings().all()
        reasons = db.execute(
            select(handler_decisions.c.reason).where(
                handler_decisions.c.evaluation_set == "held_out"
            )
        ).scalars()
        return (
            [c["claim_id"] for c in claims]
            + [c["record"]["summary"] for c in claims]
            + list(reasons)
        )


def test_the_improver_reads_nothing_from_the_held_out_set_but_scores(client):
    change_settings(client, spending_limit=10.0)
    round_id = create_round(client).json()["round_id"]
    play_out(client, round_id)
    play_out(client, round_id)
    play_out(client, round_id)
    view = client.get(f"{round_path(round_id)}/results").json()

    assert view["current_version"]["number"] == 1
    assert (
        "## Contents of the claims manual"
        not in view["current_version"]["instructions"]
    )
    assert view["scores"]["held_out"]["accuracy"] is not None
    wrong = view["evaluation_set"]["wrong"]
    assert wrong
    assert set(wrong[0]) == {"claim_id", "summary", "agent", "handler", "judge"}
    assert wrong[0]["handler"]["reason"]
    assert wrong[0]["judge"]["same_grounds"] in {"yes", "no"}
    assert len(view["evaluation_set"]["explained_least_well"]) <= 5
    assert view["rule"].startswith("A new version is kept when it meets")
    assert view["spending"]["limit"] == 10.0
    assert [m["model"] for m in view["models_allowed"]] == [
        "openai/gpt-6-luna",
        "google/gemini-3.5-flash-lite",
        "deepseek/deepseek-v4.1-flash",
    ]
    seen = json.dumps(view)
    assert not [text for text in held_out_texts() if text in seen]


def test_the_improver_reads_the_earlier_rounds(client):
    change_settings(client, spending_limit=10.0)
    first = create_round(client).json()["round_id"]
    approved_change(client, first)
    stop_round(client, first)
    second = create_round(client).json()["round_id"]
    [earlier] = client.get(f"{round_path(second)}/results").json()["earlier_rounds"]
    assert (earlier["round"], earlier["version"], earlier["verdict"]) == (
        1,
        2,
        "rolled_back",
    )
    assert earlier["why"] == "the round was stopped before its verdict"


def test_the_improver_reads_the_five_right_claims_the_judge_graded_lowest(
    client, judge_answers
):
    reasons = handler_reasons("evaluation")
    rank = {reason: n for n, reason in enumerate(sorted(set(reasons.values())))}

    def by_reason(request: httpx.Request) -> httpx.Response:
        reason = json.loads(request.content)["state"]["handler"]["reason"]
        return httpx.Response(200, json=answer(score=rank[reason] / 10))

    judge_answers(by_reason)
    change_settings(client, spending_limit=10.0)
    round_id = create_round(client).json()["round_id"]
    evaluation = play_out(client, round_id, right=10)
    play_out(client, round_id)
    play_out(client, round_id)

    right = [c["copy_of"] for c in evaluation["claims"] if c["right"]]
    assert len(right) == 10
    lowest = sorted(right, key=lambda claim_id: rank[reasons[claim_id]])[:5]
    view = client.get(f"{round_path(round_id)}/results").json()
    weakest = view["evaluation_set"]["explained_least_well"]
    assert [c["claim_id"] for c in weakest] == lowest
    assert [c["handler"]["reason"] for c in weakest] == [reasons[c] for c in lowest]
    assert len(view["evaluation_set"]["wrong"]) == 15
