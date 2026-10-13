import itertools
import json
import logging

import pytest
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver

from agent import api, harness
from agent.connection import Refused
from agent.tests.records import claim_of, payments_of
from agent.tests.stubs import (
    INSTRUCTIONS,
    PASSED,
    StubModel,
    call,
    decide,
    graph_on,
    record,
    stub,
)
from backend.tests.claim_requests import sign_off
from backend.tests.dashboard_reads import steps_of
from backend.tests.settings_requests import change_settings


def work(claim_id, model, saver=None):
    return harness.work_claim(claim_id, None, graph_on(model, saver))


def state_of(graph, client, claim_id):
    return graph.get_state(harness.thread_of(claim_of(client, claim_id)))


def test_the_graph():
    graph = graph_on(stub()).get_graph()
    assert set(graph.nodes) == {
        "__start__",
        "screen",
        "refer",
        "agent",
        "tools",
        "pay",
        "__end__",
    }
    edges = {(e.source, e.target, e.conditional) for e in graph.edges}
    assert edges == {
        ("__start__", "screen", False),
        ("screen", "refer", True),
        ("screen", "agent", True),
        ("refer", "__end__", False),
        ("agent", "tools", True),
        ("agent", "__end__", True),
        ("tools", "agent", True),
        ("tools", "pay", True),
        ("tools", "__end__", True),
        ("pay", "__end__", False),
    }


def test_approves_and_the_graph_pays_within_the_limit(client, caplog):
    caplog.set_level(logging.INFO, logger="agent")
    model = stub(
        call("get_claim"),
        call("get_policy", policy_id="POL-2001"),
        call("get_claim_history", customer_id="CUS-3001"),
        record("approve", 420.0),
    )
    assert work("CLM-1001", model) == "CLM-1001  approve  $420.00"
    assert caplog.messages == ["CLM-1001  approve  $420.00"]
    assert len(model.prompts) == 4

    claim = claim_of(client, "CLM-1001")
    assert claim["status"] == "decided"
    assert claim["attempts"] == 1
    assert claim["decision"]["payout"] == 420.0
    assert claim["payment"]["amount"] == 420.0
    assert len(claim["thread_id"]) == 36

    check, *steps = steps_of(client, "CLM-1001")
    assert (check["kind"], check["content"]) == (
        "screening",
        f"No instructions found. {PASSED}",
    )
    assert [s["kind"] for s in steps] == ["tool_call", "tool_result"] * 4
    assert steps[0]["content"] == "get_claim()"
    assert steps[1]["content"].startswith('get_claim: {"claim_id": "CLM-1001"')
    assert steps[6]["content"].startswith("record_decision(")
    assert steps[7]["content"].startswith('record_decision: {"claim_id": "CLM-1001"')
    assert "pay_claim" not in "".join(s["content"] for s in steps)
    assert {s["thread_id"] for s in [check, *steps]} == {claim["thread_id"]}


def test_the_claim_agent_reads_its_instructions_then_its_claim(client):
    model = stub(*decide("refer", 0))
    work("CLM-1003", model)
    system, first = model.prompts[0]
    assert isinstance(system, SystemMessage)
    assert system.content == INSTRUCTIONS
    assert first.content == "Claim CLM-1003"


def test_a_payout_held_for_sign_off_ends_the_claims_work(client, monkeypatch):
    paid = []
    monkeypatch.setattr(api, "pay_claim", lambda *payment: paid.append(payment))
    model = stub(*decide("approve", 1350.0))
    graph = graph_on(model)
    report = harness.work_claim("CLM-1002", None, graph)
    assert report == "CLM-1002  approve  $1,350.00, waiting for sign-off"
    assert len(model.prompts) == 2
    assert state_of(graph, client, "CLM-1002").next == ()
    claim = claim_of(client, "CLM-1002")
    assert (claim["status"], claim["payment"]) == ("waiting_for_sign_off", None)

    sign_off(client, "CLM-1002")
    steps = steps_of(client, "CLM-1002")
    assert harness.carry_on("CLM-1002", None, graph) == "CLM-1002  approve  $1,350.00"
    assert paid == []
    assert len(model.prompts) == 2
    assert steps_of(client, "CLM-1002") == steps
    assert [p["amount"] for p in payments_of("CLM-1002")] == [1350.0]


def test_the_graph_follows_the_backend_on_the_limit(client):
    change_settings(client, approval_limit=2000.0)
    report = work("CLM-1002", stub(*decide("approve", 1350.0)))
    assert report == "CLM-1002  approve  $1,350.00"
    assert claim_of(client, "CLM-1002")["payment"]["amount"] == 1350.0


@pytest.mark.parametrize("decision", ["decline", "refer"])
def test_declines_and_refers(client, decision):
    graph = graph_on(stub(*decide(decision, 0)))
    report = harness.work_claim("CLM-1003", None, graph)
    assert report == f"CLM-1003  {decision}  $0.00"
    claim = claim_of(client, "CLM-1003")
    assert (claim["status"], claim["payment"]) == ("decided", None)
    history = graph.get_state_history(harness.thread_of(claim))
    assert harness.PAY not in {node for snapshot in history for node in snapshot.next}


def test_two_decisions_in_one_reply_are_recorded_and_paid_once(client):
    twice = [record("approve", 420.0).tool_calls[0] for _ in range(2)]
    model = stub(AIMessage(content="", tool_calls=twice))
    assert work("CLM-1001", model) == "CLM-1001  approve  $420.00"
    claim = claim_of(client, "CLM-1001")
    assert (claim["status"], claim["payment"]["amount"]) == ("decided", 420.0)
    results = [s for s in steps_of(client, "CLM-1001") if s["kind"] == "tool_result"]
    assert len(results) == 2


def test_a_refused_decision_goes_back_to_the_model(client):
    model = stub(record("approve", 0), record("approve", 420.0))
    assert work("CLM-1001", model) == "CLM-1001  approve  $420.00"
    refusal = model.prompts[1][-1]
    assert isinstance(refusal, ToolMessage)
    assert refusal.text.startswith("Refused with status 422: ")
    assert claim_of(client, "CLM-1001")["payment"]["amount"] == 420.0


def test_reading_a_section_is_recorded(client):
    model = stub(
        call("read_section", document="claims_manual", number=9),
        call("read_section", document="claims_manual", number=15),
        call("search_documents", query="wild animal"),
        *decide("refer", 0),
    )
    work("CLM-1004", model)

    _, *steps = [(s["kind"], s["content"]) for s in steps_of(client, "CLM-1004")]
    assert steps[0] == (
        "tool_call",
        'read_section(document="claims_manual", number=9)',
    )
    assert steps[1][1].startswith('read_section: {"document": "claims_manual"')
    assert steps[2] == ("reading", "Claims manual, section 9: Repeat claims")
    assert steps[4] == (
        "tool_result",
        "read_section: Refused with status 404: "
        "Section 15 of the claims manual not found",
    )
    assert steps[5] == ("tool_call", 'search_documents(query="wild animal")')
    assert steps[6][1].startswith('search_documents: [{"document": "claims_manual"')
    assert [s for s in steps if s[0] == "reading"] == [steps[2]]


def test_a_section_with_bad_arguments_goes_back_to_the_model(client):
    model = stub(
        call("read_section", document="handbook", number=1), *decide("refer", 0)
    )
    assert work("CLM-1004", model) == "CLM-1004  refer  $0.00"
    assert "reading" not in {s["kind"] for s in steps_of(client, "CLM-1004")}


def test_working_out_the_payout(client):
    lines = [
        {
            "description": "Hotel",
            "amount": 245,
            "quantity": 1,
            "kind": "hotel",
            "nights": 1,
            "hours": 0,
        },
        {
            "description": "Meals",
            "amount": 95,
            "quantity": 1,
            "kind": "expense",
            "nights": 0,
            "hours": 0,
        },
        {
            "description": "Taxis",
            "amount": 80,
            "quantity": 1,
            "kind": "expense",
            "nights": 0,
            "hours": 0,
        },
    ]
    model = stub(
        call("calculate_payout", benefit="trip_delay", lines=lines, paid_by_others=0),
        *decide("approve", 420.0),
    )
    assert work("CLM-1001", model) == "CLM-1001  approve  $420.00"
    # After the check's step and the call.
    result = steps_of(client, "CLM-1001")[2]
    assert result["kind"] == "tool_result"
    content = result["content"].removeprefix("calculate_payout: ")
    assert json.loads(content)["payout"] == 420.0


def test_a_claim_is_traced_in_the_session_of_its_thread(client, traces):
    work("CLM-1001", stub(*decide("refer", 0)))
    thread_id = claim_of(client, "CLM-1001")["thread_id"]
    assert [(t["langfuse_session_id"], t["langfuse_trace_name"]) for t in traces] == [
        (f"CLM-1001:{thread_id}", "Work claim")
    ]


def test_working_a_claim_saves_each_step_on_its_thread(client, monkeypatch):
    graph = graph_on(stub(*decide("refer", 0)))
    runs = []
    invoke = graph.invoke

    def spy(start, config, **kwargs):
        runs.append((config, kwargs))
        return invoke(start, config, **kwargs)

    monkeypatch.setattr(graph, "invoke", spy)
    harness.work_claim("CLM-1003", None, graph)
    [(config, kwargs)] = runs
    assert kwargs["durability"] == "sync"
    thread_id = claim_of(client, "CLM-1003")["thread_id"]
    assert config["configurable"]["thread_id"] == thread_id


def test_a_provider_error_puts_the_claim_back_in_the_queue(client):
    outage = RuntimeError("503: The model is unavailable")
    saver = InMemorySaver()
    report = work("CLM-1004", stub(call("get_claim"), outage), saver)
    assert report == (
        "CLM-1004  failed: RuntimeError: 503: The model is unavailable,"
        " back in the queue"
    )
    claim = claim_of(client, "CLM-1004")
    assert (claim["status"], claim["attempts"]) == ("waiting", 1)
    last = steps_of(client, "CLM-1004")[-1]
    assert (last["kind"], last["content"]) == (
        "error",
        "RuntimeError: 503: The model is unavailable",
    )

    model = stub(outage)
    again = work("CLM-1004", model, saver)
    assert again.endswith(", left for a handler")
    retried = claim_of(client, "CLM-1004")
    assert (retried["status"], retried["attempts"]) == ("left_for_handler", 2)
    assert retried["thread_id"] != claim["thread_id"]
    assert [m.content for m in model.prompts[0][1:]] == ["Claim CLM-1004"]


def test_a_tool_that_breaks_stops_the_agent_rather_than_telling_the_model(
    client, monkeypatch
):
    def broken(policy_id):
        raise RuntimeError("The backend is unreachable")

    monkeypatch.setattr(api, "get_policy", broken)
    model = stub(call("get_policy", policy_id="POL-2001"), *decide("refer", 0))
    report = work("CLM-1001", model)
    assert report == (
        "CLM-1001  failed: RuntimeError: The backend is unreachable, back in the queue"
    )
    assert len(model.prompts) == 1


def test_finishing_without_a_decision_is_a_failure(client):
    model = stub(call("get_claim"), AIMessage(content="Hmm."))
    assert work("CLM-1004", model) == (
        "CLM-1004  failed: The agent finished without recording a decision,"
        " back in the queue"
    )


def test_a_claim_agent_going_round_in_circles_stops(client):
    model = StubModel(messages=(call("get_claim") for _ in itertools.count()))
    report = work("CLM-1004", model)
    assert report == (
        "CLM-1004  failed: TooManyModelCalls: The claim agent made 30 model calls"
        " without finishing, back in the queue"
    )
    assert len(model.prompts) == harness.CLAIM_MODEL_CALLS
    assert claim_of(client, "CLM-1004")["status"] == "waiting"


def test_a_failure_after_the_decision_keeps_it(client, monkeypatch, caplog):
    def lost(claim_id, amount):
        raise RuntimeError("The connection was lost")

    monkeypatch.setattr(api, "pay_claim", lost)
    report = work("CLM-1001", stub(*decide("approve", 420.0)))
    assert report == "CLM-1001  approve  $420.00, not paid yet"
    assert "CLM-1001  RuntimeError: The connection was lost" in caplog.messages
    claim = claim_of(client, "CLM-1001")
    assert (claim["status"], claim["attempts"]) == ("in_progress", 1)
    assert claim["decision"]["payout"] == 420.0
    assert "error" not in {s["kind"] for s in steps_of(client, "CLM-1001")}


def test_a_claim_that_isnt_waiting_is_not_started(client):
    work("CLM-1003", stub(*decide("refer", 0)))
    before = steps_of(client, "CLM-1003")
    with pytest.raises(Refused, match="^409: Claim CLM-1003 is not waiting$"):
        work("CLM-1003", stub())
    assert steps_of(client, "CLM-1003") == before
    assert claim_of(client, "CLM-1003")["attempts"] == 1


def test_each_claim_starts_clean(client):
    model = stub(*decide("decline", 0), *decide("refer", 0))
    graph = graph_on(model)
    harness.work_claim("CLM-1001", None, graph)
    harness.work_claim("CLM-1003", None, graph)
    firsts = [prompt for prompt in model.prompts if len(prompt) == 2]
    assert [prompt[1].content for prompt in firsts] == [
        "Claim CLM-1001",
        "Claim CLM-1003",
    ]
    assert firsts[0][0] == firsts[1][0]
    decided = [claim_of(client, i) for i in ("CLM-1001", "CLM-1003")]
    assert [c["decision"]["decision"] for c in decided] == ["decline", "refer"]
    assert decided[0]["thread_id"] != decided[1]["thread_id"]
