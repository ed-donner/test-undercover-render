"""The cost of each model call and the time spent on each claim, with their run."""

import httpx
import pytest

from agent import api, harness
from agent.tests.dispatching import dispatch, new_dispatch
from agent.tests.failures import fail_once
from agent.tests.queue_setup import leave_waiting
from agent.tests.records import claim_of, model_calls_of, work_times_of
from agent.tests.stubs import USAGE, call, decide, graph_on, stub, swarm
from backend.tests.claim_requests import sign_off
from backend.tests.dashboard_reads import steps_of
from backend.tests.run_requests import latest_dispatch


def test_each_model_call_and_spell_of_work_is_recorded(client):
    harness.work_claim("CLM-1001", None, graph_on(stub(*decide("approve", 420.0))))
    thread_id = claim_of(client, "CLM-1001")["thread_id"]
    calls = model_calls_of("CLM-1001")
    assert [
        (c["input_tokens"], c["output_tokens"], c["cost"], c["run_id"]) for c in calls
    ] == [(USAGE["prompt_tokens"], USAGE["completion_tokens"], USAGE["cost"], None)] * 3
    assert {c["thread_id"] for c in calls} == {thread_id}
    [spell] = work_times_of("CLM-1001")
    assert (spell["thread_id"], spell["run_id"]) == (thread_id, None)


def test_a_run_records_its_calls_and_spells_and_tags_its_traces(client, traces):
    leave_waiting("CLM-1001", "CLM-1003")
    dispatch(swarm({"CLM-1001": decide("decline", 0), "CLM-1003": decide("refer", 0)}))

    run_id = latest_dispatch(client)["run_id"]
    for claim_id in ("CLM-1001", "CLM-1003"):
        # The check's call, then the claim agent's two.
        assert [c["run_id"] for c in model_calls_of(claim_id)] == [run_id] * 3
        assert [w["run_id"] for w in work_times_of(claim_id)] == [run_id]
    assert [t["langfuse_tags"] for t in traces] == [[run_id], [run_id]]


def test_a_claim_worked_alone_has_no_tags(traces):
    harness.work_claim("CLM-1001", None, graph_on(stub(*decide("refer", 0))))
    [trace] = traces
    assert "langfuse_tags" not in trace


def test_both_attempts_of_a_claim_are_under_the_run(client):
    leave_waiting("CLM-1004")
    outage = RuntimeError("503: The model is unavailable")
    dispatch(swarm({"CLM-1004": [call("get_claim"), outage, *decide("refer", 0)]}))

    run_id = latest_dispatch(client)["run_id"]
    calls, spells = model_calls_of("CLM-1004"), work_times_of("CLM-1004")
    assert [c["run_id"] for c in calls] == [run_id] * 5
    assert [s["run_id"] for s in spells] == [run_id] * 2
    first, second = (s["thread_id"] for s in spells)
    assert first != second
    # Each attempt is checked first.
    assert [c["thread_id"] for c in calls] == [first, first, second, second, second]


def test_a_held_claim_has_one_spell_and_its_sign_off_adds_none(client):
    run_id = new_dispatch()["run_id"]
    harness.work_claim("CLM-1002", run_id, graph_on(stub(*decide("approve", 1350.0))))
    sign_off(client, "CLM-1002")

    assert claim_of(client, "CLM-1002")["status"] == "decided"
    [spell] = work_times_of("CLM-1002")
    assert spell["run_id"] == run_id


def test_a_failed_recording_still_settles_the_claim(client, monkeypatch):
    lost = httpx.ConnectError("Connection refused")
    fail_once(monkeypatch, api, "record_work_time", lost)
    outage = RuntimeError("503: The model is unavailable")
    with pytest.raises(httpx.ConnectError):
        harness.work_claim("CLM-1004", None, graph_on(stub(outage)))
    claim = claim_of(client, "CLM-1004")
    assert (claim["status"], claim["attempts"]) == ("waiting", 1)
    last = steps_of(client, "CLM-1004")[-1]
    assert (last["kind"], last["content"]) == (
        "error",
        "RuntimeError: 503: The model is unavailable",
    )
