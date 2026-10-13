"""The claim agent's configuration in versions."""

import httpx
import pytest
from sqlalchemy import select, update

from backend.database import (
    INSTRUCTIONS,
    engine,
    handler_decisions,
    runs,
    seed,
    versions,
)
from backend.tests.claim_requests import decide, start
from backend.tests.dashboard_reads import (
    configuration,
    evaluations,
    read,
    version_details,
)
from backend.tests.round_requests import create_round, into_round
from backend.tests.run_requests import (
    create_dispatch,
    create_evaluation,
    fail_run,
    finish,
    get_evaluation,
    latest_dispatch,
)
from backend.tests.versions import add_version

CLAIM_MD = (INSTRUCTIONS / "claim.md").read_text(encoding="utf-8")


def version_1():
    with engine().connect() as db:
        query = select(versions).where(versions.c.number == 1)
        return db.execute(query).mappings().one()


def test_version_1_is_the_claim_agent_as_it_was():
    row = version_1()
    assert row["instructions"] == CLAIM_MD
    assert (row["model"], row["reasoning_effort"]) == ("openai/gpt-6-luna", "none")
    assert (row["proposed_by"], row["approved_by"]) == ("The claims team", None)
    assert row["based_on"] is None


def test_version_1_is_the_free_model_for_students_on_free_models(monkeypatch):
    monkeypatch.setenv("MODEL_NAME", "openrouter/free")
    seed(engine())
    row = version_1()
    assert (row["model"], row["reasoning_effort"]) == ("openrouter/free", "default")


def test_the_claim_agent_reads_a_version_with_the_documents_contents(client):
    for path in ("/api/versions/current", "/api/versions/1"):
        version = client.get(path).json()
        assert list(version) == ["number", "instructions", "model", "reasoning_effort"]
        assert version["number"] == 1
        assert version["instructions"].startswith(CLAIM_MD)
        contents = version["instructions"][len(CLAIM_MD) :]
        assert "## Contents of the policy wording" in contents
        assert contents.endswith("14. Records\n")
        assert (version["model"], version["reasoning_effort"]) == (
            "openai/gpt-6-luna",
            "none",
        )
    missing = client.get("/api/versions/9")
    assert (missing.status_code, missing.json()["detail"]) == (
        404,
        "Version 9 not found",
    )


def test_the_current_version_is_the_newest_kept(client):
    add_version(CLAIM_MD + "\nA rule for baggage.\n", verdict="kept")
    add_version(CLAIM_MD + "\nAnother rule.\n", based_on=2)
    assert client.get("/api/versions/current").json()["number"] == 2

    page = configuration(client)
    assert page["current"] == 2
    listed = [
        (v["number"], v["status"], v["lines_added"], v["lines_removed"])
        for v in page["versions"]
    ]
    assert listed == [(3, "under_test", 1, 1), (2, "current", 2, 0), (1, "kept", 0, 0)]
    two = page["versions"][1]
    assert (two["model_before"], two["model"]) == (
        "openai/gpt-6-luna",
        "google/gemini-3.5-flash-lite",
    )
    assert two["scores"] == {"evaluation": None, "held_out": None}


def test_a_rolled_back_version_leaves_the_current_one(client):
    add_version(CLAIM_MD + "\nA rule.\n", verdict="rolled_back")
    assert client.get("/api/versions/current").json()["number"] == 1
    statuses = [v["status"] for v in configuration(client)["versions"]]
    assert statuses == ["rolled_back", "current"]


def test_a_versions_details_hold_its_diff(client):
    add_version(CLAIM_MD.replace("UnderCover Agent", "UnderCover claim agent", 1))
    details = version_details(client, 2)
    assert details["based_on"] == 1
    assert details["instructions"].startswith("# UnderCover claim agent")
    assert (details["diff"]["added"], details["diff"]["removed"]) == (1, 1)
    [hunk] = details["diff"]["hunks"]
    assert [line["kind"] for line in hunk[:2]] == ["removed", "added"]
    first = version_details(client, 1)
    assert (first["diff"], first["status"]) == (None, "current")
    assert read(client, "/api/configuration/versions/9").status_code == 404


def test_runs_record_the_current_version(client):
    add_version("New instructions", verdict="kept")
    dispatch = create_dispatch(client).json()
    finish(client, dispatch["run_id"])
    evaluation = create_evaluation(client).json()
    for run in (dispatch, evaluation):
        assert (run["version"], run["round_id"]) == (2, None)
        assert (run["model"], run["reasoning_effort"]) == (
            "google/gemini-3.5-flash-lite",
            "minimal",
        )
    assert latest_dispatch(client)["version"] == 2
    assert evaluations(client)[0]["version"] == 2
    assert get_evaluation(client, evaluation["run_id"])["version"] == 2


def test_a_version_after_one_rolled_back_changes_the_current_one(client):
    add_version(CLAIM_MD + "\nA rule for baggage.\n", verdict="kept")
    add_version(CLAIM_MD + "\nA rule that failed.\n", verdict="rolled_back", based_on=2)
    add_version(
        CLAIM_MD + "\nA rule for baggage.\nAnother rule.\n",
        model="openai/gpt-6-luna",
        reasoning_effort="medium",
        based_on=2,
    )
    four = version_details(client, 4)
    assert (four["based_on"], four["lines_added"], four["lines_removed"]) == (2, 1, 0)
    assert (four["model_before"], four["reasoning_effort_before"]) == (
        "google/gemini-3.5-flash-lite",
        "minimal",
    )
    [hunk] = four["diff"]["hunks"]
    assert [line["kind"] for line in hunk] == ["context", "context", "added"]


def finished_evaluation(client, tiny):
    """Start an evaluation of the held-out set and finish it at once."""
    evaluation = create_evaluation(client, tiny=tiny).json()
    finish(client, evaluation["run_id"])
    return evaluation


def referred_evaluation(client):
    """Start an evaluation of the held-out set's tiny claims, and refer each copy."""
    evaluation = create_evaluation(client).json()
    for copy in evaluation["claims"]:
        start(client, copy["claim_id"])
        decide(client, copy["claim_id"], "refer", 0)
    return evaluation


def in_a_round(client, *evaluations):
    """Make evaluations a new round's, as if it had run them."""
    into_round(create_round(client).json()["round_id"], *evaluations)


def a_held_out_decline():
    with engine().connect() as db:
        query = select(handler_decisions.c.claim_id).where(
            handler_decisions.c.evaluation_set == "held_out",
            handler_decisions.c.decision == "decline",
        )
        return db.execute(query).scalars().first()


def test_a_versions_scores_average_the_whole_set_evaluations_its_rounds_ran(client):
    first = finished_evaluation(client, tiny=False)
    second = create_evaluation(client, tiny=False).json()
    copy = f"{a_held_out_decline()}-E{second['number']}"
    start(client, copy)
    decide(client, copy, "decline", 0)
    finish(client, second["run_id"])
    finished_evaluation(client, tiny=False)
    tiny = finished_evaluation(client, tiny=True)
    stopped = create_evaluation(client, tiny=False).json()
    fail_run(client, stopped["run_id"])
    in_a_round(client, first, second, tiny, stopped)

    accuracies = [
        get_evaluation(client, e["run_id"])["measures"]["accuracy"]
        for e in (first, second)
    ]
    assert accuracies[1] == pytest.approx(accuracies[0] + 1 / 25)
    scores = configuration(client)["versions"][0]["scores"]
    assert scores["evaluation"] is None
    assert scores["held_out"]["accuracy"] == pytest.approx(sum(accuracies) / 2)


def test_a_run_with_nothing_graded_leaves_the_grade_to_the_others(
    client, judge_answers
):
    graded = referred_evaluation(client)
    finish(client, graded["run_id"])
    judge_answers(lambda request: httpx.Response(500, json={"error": "Down"}))
    ungraded = referred_evaluation(client)
    finish(client, ungraded["run_id"])
    in_a_round(client, graded, ungraded)
    # Count the five tiny claims as a whole set, to keep the test short.
    with engine().begin() as db:
        db.execute(update(runs).values(tiny=False))

    assert get_evaluation(client, ungraded["run_id"])["measures"]["grade"] is None
    held_out = configuration(client)["versions"][0]["scores"]["held_out"]
    assert held_out["grade"] == pytest.approx(2.2)


def test_the_check_runs_on_gpt_6_luna_with_no_reasoning(client, dashboard):
    assert client.get("/api/screening").json() == {
        "model": "openai/gpt-6-luna",
        "reasoning_effort": "none",
    }
    assert dashboard.get("/api/screening").status_code == 401


def test_the_check_runs_on_the_free_model_at_its_default(client, monkeypatch):
    monkeypatch.setenv("MODEL_NAME", "openrouter/free")
    assert client.get("/api/screening").json() == {
        "model": "openrouter/free",
        "reasoning_effort": "default",
    }


def test_no_version_changes_the_checks_model(client):
    add_version("Version 2's instructions", model="openai/gpt-6.1-sol", verdict="kept")
    assert client.get("/api/versions/current").json()["model"] == "openai/gpt-6.1-sol"
    assert client.get("/api/screening").json()["model"] == "openai/gpt-6-luna"
