"""The agent stopped partway, by a crash, a restart or Ctrl-C, and carrying on. The
tests stop it with KeyboardInterrupt, which the harness doesn't catch, so the claim is
left as a crash leaves it."""

import itertools

import pytest
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver

from agent import api, harness
from agent.tests.failures import fail_once
from agent.tests.records import claim_of
from agent.tests.stubs import StubModel, call, decide, graph_on, record, stub
from backend.tests.claim_requests import sign_off
from backend.tests.dashboard_reads import steps_of


def stop_while_working(claim_id, saver, *replies):
    """Work a claim until the agent is stopped after the replies given."""
    with pytest.raises(KeyboardInterrupt):
        harness.work_claim(
            claim_id, None, graph_on(stub(*replies, KeyboardInterrupt()), saver)
        )


def calls_to(monkeypatch, name):
    """Count the calls to one of the backend's operations."""
    calls = []
    function = getattr(api, name)

    def count(*args):
        calls.append(args)
        return function(*args)

    monkeypatch.setattr(api, name, count)
    return calls


class StopBeforeCheckpoint(InMemorySaver):
    """Saves a step's writes, then stops before saving the checkpoint that follows,
    once a step has recorded a decision: the gap a crash can land in."""

    stopping = False

    def put_writes(self, config, writes, task_id, task_path=""):
        super().put_writes(config, writes, task_id, task_path)
        self.stopping = self.stopping or any(c == "decision" for c, _ in writes)

    def put(self, config, checkpoint, metadata, new_versions):
        if self.stopping:
            self.stopping = False
            raise KeyboardInterrupt
        return super().put(config, checkpoint, metadata, new_versions)


def test_a_claim_stopped_partway_carries_on_from_its_last_step(client):
    saver = InMemorySaver()
    stop_while_working(
        "CLM-1001", saver, call("get_claim"), call("get_policy", policy_id="POL-2001")
    )
    stopped = claim_of(client, "CLM-1001")
    assert (stopped["status"], stopped["attempts"]) == ("in_progress", 1)
    before = steps_of(client, "CLM-1001")

    model = stub(record("approve", 420.0))
    report = harness.carry_on("CLM-1001", None, graph_on(model, saver))
    assert report == "CLM-1001  approve  $420.00"
    claim = claim_of(client, "CLM-1001")
    assert (claim["thread_id"], claim["attempts"]) == (stopped["thread_id"], 1)
    assert claim["payment"]["amount"] == 420.0
    first = model.prompts[0]
    assert len([m for m in first if isinstance(m, HumanMessage)]) == 1
    earlier = [m.name for m in first if isinstance(m, ToolMessage)]
    assert earlier == ["get_claim", "get_policy"]
    steps = steps_of(client, "CLM-1001")
    assert steps[: len(before)] == before
    assert len(steps) == len(before) + 2
    assert {s["thread_id"] for s in steps} == {claim["thread_id"]}
    assert "error" not in {s["kind"] for s in steps}


def test_stopped_just_after_the_decision_is_recorded(client, monkeypatch):
    saver = InMemorySaver()
    fail_once(monkeypatch, api, "record_decision", KeyboardInterrupt(), carry_out=True)
    with pytest.raises(KeyboardInterrupt):
        harness.work_claim(
            "CLM-1001", None, graph_on(stub(*decide("approve", 420.0)), saver)
        )
    assert claim_of(client, "CLM-1001")["payment"] is None

    model = stub()
    report = harness.carry_on("CLM-1001", None, graph_on(model, saver))
    assert report == "CLM-1001  approve  $420.00"
    assert claim_of(client, "CLM-1001")["payment"]["amount"] == 420.0
    assert model.prompts == []


def test_stopped_just_after_the_payment_is_recorded(client, monkeypatch):
    saver = InMemorySaver()
    fail_once(monkeypatch, api, "pay_claim", KeyboardInterrupt(), carry_out=True)
    with pytest.raises(KeyboardInterrupt):
        harness.work_claim(
            "CLM-1001", None, graph_on(stub(*decide("approve", 420.0)), saver)
        )
    paid = claim_of(client, "CLM-1001")["payment"]

    payments = calls_to(monkeypatch, "pay_claim")
    graph = graph_on(stub(), saver)
    report = harness.carry_on("CLM-1001", None, graph)
    assert report == "CLM-1001  approve  $420.00"
    assert payments == [("CLM-1001", 420.0)]
    assert claim_of(client, "CLM-1001")["payment"] == paid
    thread = harness.thread_of(claim_of(client, "CLM-1001"))
    assert graph.get_state(thread).next == ()


def test_stopped_after_a_step_was_written_but_before_its_checkpoint(client):
    saver = StopBeforeCheckpoint()
    with pytest.raises(KeyboardInterrupt):
        harness.work_claim(
            "CLM-1001", None, graph_on(stub(*decide("approve", 420.0)), saver)
        )
    assert claim_of(client, "CLM-1001")["decision"]["payout"] == 420.0

    model = stub()
    graph = graph_on(model, saver)
    report = harness.carry_on("CLM-1001", None, graph)
    assert report == "CLM-1001  approve  $420.00"
    assert model.prompts == []
    claim = claim_of(client, "CLM-1001")
    assert (claim["payment"]["amount"], claim["attempts"]) == (420.0, 1)
    thread = harness.thread_of(claim)
    assert graph.get_state(thread).values["decision"]["payout"] == 420.0


def test_a_held_payout_stopped_before_its_checkpoint_is_paid_by_the_sign_off(
    client, monkeypatch
):
    saver = StopBeforeCheckpoint()
    with pytest.raises(KeyboardInterrupt):
        harness.work_claim(
            "CLM-1002", None, graph_on(stub(*decide("approve", 1350.0)), saver)
        )
    sign_off(client, "CLM-1002")

    payments = calls_to(monkeypatch, "pay_claim")
    model = stub()
    report = harness.carry_on("CLM-1002", None, graph_on(model, saver))
    assert report == "CLM-1002  approve  $1,350.00"
    assert (payments, model.prompts) == ([], [])
    assert claim_of(client, "CLM-1002")["payment"]["signed_off_by"] == "Dana Whitfield"


def test_finished_without_a_decision_but_stopped_before_it_was_failed(
    client, monkeypatch
):
    saver = InMemorySaver()
    fail_once(monkeypatch, harness, "settle", KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        harness.work_claim(
            "CLM-1004", None, graph_on(stub(call("get_claim"), "Hmm."), saver)
        )
    assert claim_of(client, "CLM-1004")["status"] == "in_progress"

    model = stub()
    report = harness.carry_on("CLM-1004", None, graph_on(model, saver))
    assert report == (
        "CLM-1004  failed: The agent finished without recording a decision,"
        " back in the queue"
    )
    assert model.prompts == []


def test_a_claim_stopped_before_its_first_step_was_saved(client):
    client.post("/api/claims/CLM-1001/start", json={"thread_id": "nothing-saved"})
    model = stub(*decide("refer", 0))
    report = harness.carry_on("CLM-1001", None, graph_on(model))
    assert report == "CLM-1001  refer  $0.00"
    claim = claim_of(client, "CLM-1001")
    assert (claim["thread_id"], claim["attempts"]) == ("nothing-saved", 1)
    assert model.prompts[0][1].content == "Claim CLM-1001"


def test_the_model_call_limit_holds_across_a_restart(client):
    saver = InMemorySaver()
    before = 20
    stop_while_working("CLM-1004", saver, *(call("get_claim") for _ in range(before)))
    endless = StubModel(messages=(call("get_claim") for _ in itertools.count()))
    report = harness.carry_on("CLM-1004", None, graph_on(endless, saver))
    assert report.startswith("CLM-1004  failed: TooManyModelCalls: ")
    assert len(endless.prompts) == harness.CLAIM_MODEL_CALLS - before


def test_a_claim_that_fails_while_carried_on_starts_afresh_next_time(client):
    saver = InMemorySaver()
    stop_while_working("CLM-1004", saver, call("get_claim"))
    stopped = claim_of(client, "CLM-1004")
    outage = stub(RuntimeError("503: The model is unavailable"))
    report = harness.carry_on("CLM-1004", None, graph_on(outage, saver))
    assert report == (
        "CLM-1004  failed: RuntimeError: 503: The model is unavailable,"
        " back in the queue"
    )
    assert len(outage.prompts) == 1

    harness.work_claim("CLM-1004", None, graph_on(stub(*decide("refer", 0)), saver))
    claim = claim_of(client, "CLM-1004")
    assert claim["attempts"] == 2
    assert claim["thread_id"] != stopped["thread_id"]
