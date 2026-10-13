"""One piece of the agent's work at a time, which the app keeps: it creates the runs
and the rounds and records the reviews, then asks the agent to work them, undoing
what it did when the agent didn't take the work, and marks stopped the work the
agent went quiet on."""

import json
import threading
import time
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import delete, event, select

from backend import agent_work
from backend.database import engine, locks, proposals, rounds, runs
from backend.round_state import round_row, stop
from backend.tests.agent_answers import broken, refusing_with, slow, unreachable
from backend.tests.claim_requests import NOTE, held, send_back, sign_off
from backend.tests.round_requests import (
    approve,
    create_round,
    improvement,
    propose_change,
    reject,
    round_evaluation,
    start_round,
    stop_round,
)
from backend.tests.rows import (
    committed_claim,
    count,
    newest_run,
    round_heard,
    run_heard,
)
from backend.tests.run_requests import (
    another_running_dispatch,
    create_dispatch,
    finish,
    latest_dispatch,
    start_dispatch,
    start_evaluation,
)

QUIET = timedelta(minutes=6)
GONE_QUIET = "The agent stopped answering"


def run_of(client, run_id):
    return client.get(f"/api/runs/{run_id}").json()


def as_seen(payload):
    """A round's status and its newest proposal's review, as another connection
    reads them when the agent is asked to work the round."""
    with engine().connect() as db:
        status = db.execute(
            select(rounds.c.status).where(rounds.c.round_id == payload["round_id"])
        ).scalar_one()
        reviews = db.execute(
            select(proposals.c.review)
            .where(proposals.c.round_id == payload["round_id"])
            .order_by(proposals.c.proposed_at.desc())
        ).scalars()
        return status, next(iter(reviews), None)


def as_committed(run_id):
    """A run's status as another connection reads it: what has been committed."""
    with engine().connect() as db:
        query = select(runs.c.status).where(runs.c.run_id == run_id)
        return db.execute(query).scalar_one()


def test_a_dispatch_is_created_and_committed_before_the_agent_is_asked(
    client, agent_answers
):
    seen = []

    def accept(request):
        seen.append(as_committed(newest_run()))
        return httpx.Response(200, json={"accepted": True})

    agent_answers(accept)
    assert start_dispatch(client, 7).status_code == 202
    assert seen == ["running"]
    dispatch = latest_dispatch(client)
    assert (dispatch["agents"], dispatch["version"], dispatch["status"]) == (
        7,
        1,
        "running",
    )


def test_an_evaluation_is_created_with_its_copies(client, agent_calls):
    assert start_evaluation(client).status_code == 202
    [asked] = agent_calls
    evaluation = run_of(client, asked["run_id"])
    assert (evaluation["kind"], evaluation["status"]) == ("evaluation", "running")
    assert [c["claim_id"][-3:] for c in evaluation["claims"]] == ["-E1"] * 5


def test_a_round_is_created_and_a_review_recorded_before_the_agent_is_asked(
    client, agent_answers
):
    asked, seen = [], []

    def accept(request):
        payload = json.loads(request.content)
        asked.append(payload)
        seen.append(as_seen(payload))
        return httpx.Response(200, json={"accepted": True})

    agent_answers(accept)
    assert start_round(client).status_code == 202
    [started] = asked
    assert started["operation"] == "work_round"
    round_id = started["round_id"]
    assert seen == [("open", None)]
    proposal_id = propose_change(client, round_id).json()["proposal_id"]
    assert reject(client, round_id, proposal_id).status_code == 202
    assert asked[-1] == {
        "operation": "carry_round_on",
        "round_id": round_id,
        "proposal_id": proposal_id,
    }
    assert seen[-1] == ("open", "rejected")
    proposal = client.get(f"/api/rounds/{round_id}/proposals/{proposal_id}").json()
    assert (proposal["review"], proposal["reviewed_by"]) == (
        "rejected",
        "Dana Whitfield",
    )
    assert proposal["rejection_reason"] == "Keep each rule general"
    assert proposal["reviewed_at"] is not None


@pytest.mark.parametrize(
    ("start_first", "going"),
    [
        (start_dispatch, "A dispatch is running"),
        (start_evaluation, "An evaluation is running"),
        (start_round, "Round 1 is running"),
    ],
)
def test_while_work_is_going_every_start_is_refused_naming_it(
    client, agent_calls, start_first, going
):
    assert start_first(client).status_code == 202
    for start in (start_dispatch, start_evaluation, start_round):
        refused = start(client)
        assert (refused.status_code, refused.json()["detail"]) == (409, going)
    assert len(agent_calls) == 1


def test_a_review_is_refused_while_a_dispatch_runs_and_its_proposal_waits(client):
    round_id = create_round(client).json()["round_id"]
    proposal_id = propose_change(client, round_id).json()["proposal_id"]
    assert start_dispatch(client).status_code == 202
    refused = approve(client, round_id, proposal_id)
    assert (refused.status_code, refused.json()["detail"]) == (
        409,
        "A dispatch is running",
    )
    assert improvement(client)["round"]["waiting"]["proposal_id"] == proposal_id


def test_a_round_waiting_for_a_handler_doesnt_stop_a_dispatch(client):
    round_id = create_round(client).json()["round_id"]
    propose_change(client, round_id)
    assert start_dispatch(client).status_code == 202
    finish(client, newest_run())
    refused = start_round(client)
    assert (refused.status_code, refused.json()["detail"]) == (
        409,
        "Round 1 is open. Finish or stop it first.",
    )


def test_two_dispatches_at_the_same_moment_make_one_run(client, monkeypatch):
    refuse = agent_work.refuse_while_work_goes_on

    def then_wait(db):
        """Leave time after the check for the other start to check too, as it
        could without the lock."""
        refuse(db)
        time.sleep(0.3)

    monkeypatch.setattr(agent_work, "refuse_while_work_goes_on", then_wait)
    # SQLite would take its write lock at that update even though it changes no
    # row, which Postgres doesn't, so leaving it out shows the lock's own effect.
    monkeypatch.setattr(agent_work, "stop_quiet_work", lambda db: None)
    together = threading.Barrier(2)
    answers = []

    def start():
        together.wait()
        answers.append(start_dispatch(client).status_code)

    starting = [threading.Thread(target=start) for _ in range(2)]
    for thread in starting:
        thread.start()
    for thread in starting:
        thread.join(10)
    assert sorted(answers) == [202, 409]
    assert count(runs) == 1


def test_a_start_after_a_dispatch_went_quiet_stops_it_and_goes_ahead(client):
    quiet = create_dispatch(client).json()["run_id"]
    run_heard(quiet, timedelta(minutes=4))
    assert start_dispatch(client).status_code == 409
    run_heard(quiet, QUIET)
    assert start_evaluation(client).status_code == 202
    stopped = run_of(client, quiet)
    assert (stopped["status"], stopped["stopped_because"]) == ("stopped", GONE_QUIET)


def test_a_quiet_round_is_stopped_with_its_running_evaluation(client):
    round_id = create_round(client).json()["round_id"]
    evaluation = round_evaluation(client, round_id).json()["run_id"]
    round_heard(round_id, QUIET)
    assert start_dispatch(client).status_code == 202
    [listed] = improvement(client)["rounds"]
    assert (listed["status"], listed["stopped_because"]) == ("stopped", GONE_QUIET)
    stopped = run_of(client, evaluation)
    assert (stopped["status"], stopped["stopped_because"]) == ("stopped", GONE_QUIET)


def test_a_round_that_spoke_after_it_was_read_as_quiet_isnt_stopped(
    client, monkeypatch
):
    round_id = create_round(client).json()["round_id"]
    round_heard(round_id, QUIET)
    with engine().connect() as db:
        as_read = agent_work.working_rounds(db)
    assert client.post(f"/api/rounds/{round_id}/heartbeat").status_code == 200
    monkeypatch.setattr(agent_work, "working_rounds", lambda db: as_read)
    refused = start_dispatch(client)
    assert (refused.status_code, refused.json()["detail"]) == (
        409,
        "Round 1 is running",
    )
    [listed] = improvement(client)["rounds"]
    assert (listed["status"], listed["stopped_because"]) == ("open", None)


def test_a_round_ended_after_it_was_read_is_left_as_it_ended(client):
    round_id = create_round(client).json()["round_id"]
    with engine().connect() as db:
        as_read = round_row(db, round_id)
    stop_round(client, round_id)
    with engine().begin() as db:
        assert not stop(db, as_read, None, GONE_QUIET)
    [listed] = improvement(client)["rounds"]
    assert (listed["status"], listed["stopped_because"]) == (
        "stopped",
        "Stopped by Dana Whitfield",
    )
    again = stop_round(client, round_id)
    assert (again.status_code, again.json()["detail"]) == (409, "Round 1 is stopped")


def test_a_rounds_evaluation_is_never_stopped_on_its_own(client):
    round_id = create_round(client).json()["round_id"]
    evaluation = round_evaluation(client, round_id).json()["run_id"]
    run_heard(evaluation, QUIET)
    refused = start_dispatch(client)
    assert (refused.status_code, refused.json()["detail"]) == (
        409,
        "Round 1 is running",
    )
    assert run_of(client, evaluation)["status"] == "running"


REFUSED = "A dispatch is running"


@pytest.mark.parametrize(
    ("answer", "status", "because"),
    [
        (unreachable, 503, "The agent's service isn't running"),
        (refusing_with(REFUSED), 409, REFUSED),
        (
            broken,
            502,
            "The agent couldn't take the work: The agent couldn't get ready",
        ),
    ],
)
def test_a_run_the_agent_didnt_take_is_stopped_with_why(
    client, agent_answers, answer, status, because
):
    agent_answers(answer)
    for start in (start_dispatch, start_evaluation):
        refused = start(client)
        assert (refused.status_code, refused.json()["detail"]) == (status, because)
        stopped = run_of(client, newest_run())
        assert (stopped["status"], stopped["stopped_because"]) == ("stopped", because)


def test_a_round_the_agent_didnt_take_is_stopped_with_why(client, agent_answers):
    agent_answers(unreachable)
    refused = start_round(client)
    assert refused.status_code == 503
    [listed] = improvement(client)["rounds"]
    assert (listed["status"], listed["stopped_because"]) == (
        "stopped",
        "The agent's service isn't running",
    )


def test_a_review_the_agent_didnt_take_is_cleared(client, agent_answers, agent_calls):
    round_id = create_round(client).json()["round_id"]
    proposal_id = propose_change(client, round_id).json()["proposal_id"]
    agent_answers(refusing_with(REFUSED))
    refused = approve(client, round_id, proposal_id)
    assert (refused.status_code, refused.json()["detail"]) == (409, REFUSED)
    proposal = client.get(f"/api/rounds/{round_id}/proposals/{proposal_id}").json()
    assert (proposal["review"], proposal["reviewed_by"]) == (None, None)
    assert improvement(client)["round"]["waiting"]["proposal_id"] == proposal_id

    agent_answers(lambda request: httpx.Response(200, json={"accepted": True}))
    assert approve(client, round_id, proposal_id).status_code == 202


def test_a_timeout_leaves_the_dispatch_running_until_it_goes_quiet(
    client, agent_answers
):
    agent_answers(slow)
    timed_out = start_dispatch(client)
    assert timed_out.status_code == 503
    assert "Reload the page" in timed_out.json()["detail"]
    run_id = newest_run()
    assert run_of(client, run_id)["status"] == "running"

    agent_answers(lambda request: httpx.Response(200, json={"accepted": True}))
    assert start_dispatch(client).status_code == 409
    run_heard(run_id, timedelta(minutes=5, seconds=1))
    assert start_dispatch(client).status_code == 202
    assert run_of(client, run_id)["stopped_because"] == GONE_QUIET


@pytest.fixture
def connections_held():
    """Count the most database connections held at once from here on."""
    held = {"now": 0, "most": 0}

    def checked_out(*args):
        held["now"] += 1
        held["most"] = max(held["most"], held["now"])

    def checked_in(*args):
        held["now"] -= 1

    pool = engine().pool
    event.listen(pool, "checkout", checked_out)
    event.listen(pool, "checkin", checked_in)
    yield held
    event.remove(pool, "checkout", checked_out)
    event.remove(pool, "checkin", checked_in)


def test_a_request_that_asks_the_agent_holds_one_connection_at_a_time(
    client, connections_held
):
    round_id = create_round(client).json()["round_id"]
    proposal_id = propose_change(client, round_id).json()["proposal_id"]
    held(client, "CLM-1008", 2240.0)
    held(client, "CLM-1002", 1350.0)
    connections_held["most"] = 0
    assert approve(client, round_id, proposal_id).status_code == 202
    assert sign_off(client, "CLM-1008").status_code == 200
    assert send_back(client, "CLM-1002", NOTE).status_code == 200
    stop_round(client, round_id)
    assert start_dispatch(client).status_code == 202
    assert connections_held["most"] == 1
    assert committed_claim("CLM-1008")["status"] == "decided"


def test_stopping_a_round_stops_its_running_evaluation(client):
    round_id = create_round(client).json()["round_id"]
    evaluation = round_evaluation(client, round_id).json()["run_id"]
    stop_round(client, round_id)
    stopped = run_of(client, evaluation)
    assert (stopped["status"], stopped["stopped_because"]) == (
        "stopped",
        "Stopped by Dana Whitfield",
    )
    finished = finish(client, evaluation)
    assert (finished.status_code, finished.json()["status"]) == (200, "stopped")

    dispatch = create_dispatch(client).json()["run_id"]
    finish(client, dispatch)
    again = finish(client, dispatch)
    assert (again.status_code, again.json()["detail"]) == (
        409,
        f"Run {dispatch} is not running",
    )


def test_the_operations_the_agent_no_longer_calls_are_gone(client):
    operations = {
        operation["operationId"]
        for methods in client.get("/openapi.json").json()["paths"].values()
        for operation in methods.values()
    }
    gone = {
        "create_dispatch",
        "create_evaluation",
        "create_round",
        "record_review",
        "stop_runs",
        "stop_rounds",
    }
    assert operations & gone == set()


def test_a_run_heartbeat_keeps_a_dispatch_from_counting_as_quiet(client):
    run_id = create_dispatch(client).json()["run_id"]
    run_heard(run_id, QUIET)
    assert client.post(f"/api/runs/{run_id}/heartbeat").status_code == 200
    refused = start_dispatch(client)
    assert (refused.status_code, refused.json()["detail"]) == (
        409,
        "A dispatch is running",
    )


def test_a_round_heartbeat_keeps_a_round_from_counting_as_quiet(client):
    round_id = create_round(client).json()["round_id"]
    round_heard(round_id, QUIET)
    assert client.post(f"/api/rounds/{round_id}/heartbeat").status_code == 200
    refused = start_dispatch(client)
    assert (refused.status_code, refused.json()["detail"]) == (
        409,
        "Round 1 is running",
    )


def test_a_review_counts_as_hearing_of_the_round(client):
    round_id = create_round(client).json()["round_id"]
    proposal_id = propose_change(client, round_id).json()["proposal_id"]
    round_heard(round_id, QUIET)
    assert approve(client, round_id, proposal_id).status_code == 202
    refused = start_dispatch(client)
    assert (refused.status_code, refused.json()["detail"]) == (
        409,
        "Round 1 is running",
    )


def test_quiet_work_stays_stopped_when_the_start_is_refused(client):
    round_id = create_round(client).json()["round_id"]
    propose_change(client, round_id)
    quiet = another_running_dispatch()
    run_heard(quiet, QUIET)
    refused = start_round(client)
    assert (refused.status_code, refused.json()["detail"]) == (
        409,
        "Round 1 is open. Finish or stop it first.",
    )
    stopped = run_of(client, quiet)
    assert (stopped["status"], stopped["stopped_because"]) == ("stopped", GONE_QUIET)


def test_a_missing_lock_is_an_error(client):
    with engine().begin() as db:
        db.execute(delete(locks))
    with pytest.raises(RuntimeError, match="The lock on the agent's work is missing"):
        start_dispatch(client)
