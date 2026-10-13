"""The pause for a handler's answer: an approval held for sign-off pauses the claim
graph, with its place saved on the claim's thread, and a handler's sign-off resumes
it."""

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from agent import harness
from agent.gateway import Gateway
from agent.tests.dispatching import new_evaluation
from agent.tests.gateway_stand_in import DENIED
from agent.tests.held import StopAtThePause, hold, state_of
from agent.tests.memory_stand_in import MemoryStandIn
from agent.tests.records import claim_of, payments_of, work_times_of
from agent.tests.stubs import agent_on, approve, stub
from backend.tests.claim_requests import sign_off
from backend.tests.dashboard_reads import steps_of
from backend.tests.settings_requests import change_settings

HELD = "CLM-1003  approve  $3,750.00, waiting for sign-off"


def test_an_approval_held_for_sign_off_pauses_the_claim_graph(client):
    saver = InMemorySaver()
    agent = agent_on(stub(*approve("CLM-1003", 3750.0)), saver)
    assert harness.work_claim("CLM-1003", None, agent) == HELD
    claim = claim_of(client, "CLM-1003")
    assert (claim["status"], claim["payment"]) == ("waiting_for_sign_off", None)
    [waiting] = state_of(agent, client, "CLM-1003").interrupts
    assert waiting.value == {"claim_id": "CLM-1003"}
    again = agent_on(stub(), saver)
    assert len(state_of(again, client, "CLM-1003").interrupts) == 1
    assert harness.paused(claim, again)


def test_a_payment_the_gateway_refuses_pauses_the_claim_graph(client, gateway):
    change_settings(client, approval_limit=2000.0)
    agent = agent_on(stub(*approve("CLM-1002", 1500.0)), route=Gateway(gateway.url))
    report = harness.work_claim("CLM-1002", None, agent)
    assert report == "CLM-1002  approve  $1,500.00, waiting for sign-off"
    claim = claim_of(client, "CLM-1002")
    assert claim["decision"]["gateway_refusal"] == DENIED
    assert harness.paused(claim, agent)


def test_an_evaluations_copy_held_for_sign_off_doesnt_pause(client):
    run = new_evaluation("evaluation")
    agent = agent_on(stub(*approve("CLM-1020", 1240.0)), pauses=False)
    report = harness.work_in_run("CLM-1020-E1", run["run_id"], lambda: agent)
    assert report == "CLM-1020-E1  approve  $1,240.00, waiting for sign-off"
    state = state_of(agent, client, "CLM-1020-E1")
    assert (state.interrupts, state.next) == ((), ())
    assert not harness.paused(claim_of(client, "CLM-1020-E1"), agent)


def test_a_claim_with_no_thread_isnt_paused(client):
    assert not harness.paused(claim_of(client, "CLM-1003"), agent_on(stub()))


def test_a_claim_stopped_before_its_pause_ran_isnt_paused(client):
    saver = StopAtThePause()
    with pytest.raises(KeyboardInterrupt):
        hold(saver=saver)
    agent = agent_on(stub(), saver)
    state = state_of(agent, client, "CLM-1003")
    assert (state.next, state.interrupts) == ((harness.WAIT_FOR_HANDLER,), ())
    assert claim_of(client, "CLM-1003")["status"] == "waiting_for_sign_off"
    assert not harness.paused(claim_of(client, "CLM-1003"), agent)


@pytest.mark.parametrize("remembers", [True, False])
def test_a_sign_off_resumes_the_claim_and_ends_its_work(client, remembers):
    store = MemoryStandIn() if remembers else None
    saver = InMemorySaver()
    hold(saver=saver, store=store)
    assert sign_off(client, "CLM-1003").status_code == 200
    model = stub()
    agent = agent_on(model, saver, store=store)
    assert harness.paused(claim_of(client, "CLM-1003"), agent)
    assert "memory_save" not in [s["kind"] for s in steps_of(client, "CLM-1003")]
    assert store is None or store.events == []

    assert harness.resume("CLM-1003", agent) == "CLM-1003  approve  $3,750.00"
    assert model.prompts == []
    assert [p["amount"] for p in payments_of("CLM-1003")] == [3750.0]
    kinds = [s["kind"] for s in steps_of(client, "CLM-1003")]
    assert ("memory_save" in kinds) is remembers
    if store is not None:
        assert [(e.actor, e.session) for e in store.events] == [
            ("CUS-3003", "CLM-1003")
        ] * 2
    state = state_of(agent, client, "CLM-1003")
    assert (state.interrupts, state.next) == ((), ())
    assert not harness.paused(claim_of(client, "CLM-1003"), agent)


def test_a_resume_is_timed_with_no_run(client):
    saver = InMemorySaver()
    hold(saver=saver)
    sign_off(client, "CLM-1003")
    before = work_times_of("CLM-1003")
    harness.resume("CLM-1003", agent_on(stub(), saver))
    [*_, resumed] = work_times_of("CLM-1003")
    assert len(work_times_of("CLM-1003")) == len(before) + 1
    assert resumed["run_id"] is None


def test_a_resume_is_traced_in_the_claims_session(client, traces):
    saver = InMemorySaver()
    hold(saver=saver)
    sign_off(client, "CLM-1003")
    harness.resume("CLM-1003", agent_on(stub(), saver))
    thread_id = claim_of(client, "CLM-1003")["thread_id"]
    assert [(t["langfuse_session_id"], t["langfuse_trace_name"]) for t in traces] == [
        (f"CLM-1003:{thread_id}", "Work claim"),
        (f"CLM-1003:{thread_id}", "Resume"),
    ]
    assert "langfuse_tags" not in traces[-1]
