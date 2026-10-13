"""Evaluations: the agent works copies of a labeled set's claims, and the
backend scores them."""

from functools import partial

import pytest
from langchain_core.exceptions import ModelRateLimitError
from langgraph.checkpoint.memory import InMemorySaver

from agent import api, dispatcher, harness
from agent.tests.dispatching import dispatch, new_evaluation
from agent.tests.invoking import ACCEPTED, work_run
from agent.tests.queue_setup import leave_waiting
from agent.tests.records import claim_of, model_calls_of, work_times_of
from agent.tests.stubs import agent_on, approve, decide, stub, swarm
from backend.tests.dashboard_reads import evaluations
from backend.tests.run_requests import get_evaluation, latest_dispatch, queue

TINY = ["CLM-1007", "CLM-1015", "CLM-1017", "CLM-1020", "CLM-1021"]


def test_an_evaluation_the_app_created_worked_by_the_agent(client, serve):
    before = queue(client)
    outage = RuntimeError("503: The model is unavailable")
    model = swarm(
        {
            "CLM-1007-E1": approve("CLM-1007", 50.0),
            "CLM-1015-E1": approve("CLM-1015", 300.0),
            "CLM-1017-E1": decide("decline", 0),
            "CLM-1020-E1": approve("CLM-1020", 1240.0),
            "CLM-1021-E1": [outage, outage],
        }
    )
    saver = InMemorySaver()
    agent = serve(model, saver)
    run_id = new_evaluation("evaluation")["run_id"]
    assert agent.invoke(work_run(run_id)).json() == ACCEPTED

    [listed] = evaluations(client)
    assert (listed["status"], listed["agents"], listed["size"]) == ("finished", 5, 5)
    assert queue(client) == before
    held = claim_of(client, "CLM-1020-E1")
    assert held["status"] == "waiting_for_sign_off"
    # A copy held for sign-off counts as finished, with nothing left to run.
    held_state = agent_on(stub(), saver).graph.get_state(harness.thread_of(held))
    assert held_state.created_at is not None
    assert (held_state.next, held_state.interrupts) == ((), ())
    assert claim_of(client, "CLM-1021-E1")["status"] == "left_for_handler"

    evaluation = get_evaluation(client, listed["run_id"])
    measures = evaluation["measures"]
    assert (measures["decision_accuracy"], measures["accuracy"]) == (0.4, 0.2)
    assert measures["cost_of_mistakes"] == 2850.0
    assert measures["straight_through"] == 0.8
    copies = [f"{claim_id}-E1" for claim_id in TINY]
    cost = sum(c["cost"] for i in copies for c in model_calls_of(i))
    seconds = sum(w["seconds"] for i in copies for w in work_times_of(i))
    assert measures["model_cost_per_claim"] == pytest.approx(cost / 5)
    assert measures["seconds_per_claim"] == pytest.approx(seconds / 5)
    # The claim agents' eleven calls, three of them working out the approvals'
    # payouts, and the check's six: one for each attempt.
    assert cost == pytest.approx(0.0042 * (11 + 6))


def test_a_dispatch_leaves_an_evaluations_copies_alone(client):
    leave_waiting("CLM-1001")
    evaluation = new_evaluation()
    client.post("/api/claims/CLM-1104-E1/start", json={"thread_id": "copy-thread"})
    client.post(f"/api/runs/{evaluation['run_id']}/finish")
    dispatch(swarm({"CLM-1001": decide("refer", 0)}))

    assert [c["claim_id"] for c in latest_dispatch(client)["claims"]] == ["CLM-1001"]
    copy = claim_of(client, "CLM-1104-E1")
    assert (copy["status"], copy["thread_id"]) == ("in_progress", "copy-thread")
    assert claim_of(client, "CLM-1106-E1")["status"] == "waiting"


def test_the_agent_cant_read_the_scoreboard():
    for name in (
        "list_evaluations",
        "get_evaluation",
        "start_dispatch",
        "start_evaluation",
        "get_configuration",
        "get_version_details",
    ):
        assert not hasattr(api, name)


def test_a_copy_still_failing_after_its_tries_is_left_in_progress(client):
    run = new_evaluation()
    limited = ModelRateLimitError("429 Too Many Requests")
    scripts = {copy["claim_id"]: decide("refer", 0) for copy in run["claims"]}
    model = swarm(scripts | {"CLM-1104-E1": [limited] * 3})
    work = partial(
        harness.work_in_run, new_agent=partial(agent_on, model, InMemorySaver())
    )
    reports = dispatcher.work_run(run, work)

    assert (
        "CLM-1104-E1  left in progress: ModelRateLimitError: 429 Too Many Requests"
        in reports
    )
    assert claim_of(client, "CLM-1104-E1")["status"] == "in_progress"
