"""The dispatcher: claim agents working a dispatch at once, with retries."""

import operator
import time
from typing import Annotated, Any, TypedDict, cast

import pytest
from langchain_core.exceptions import ModelRateLimitError, ModelTimeoutError
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.errors import NodeError
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, Send

from agent import api, dispatcher, harness
from agent.tests.dispatching import dispatch
from agent.tests.failures import fail_once
from agent.tests.queue_setup import leave_waiting
from agent.tests.records import claim_of, work_times_of
from agent.tests.stubs import agent_on, approve, call, decide, record, stub, swarm
from backend.tests.claim_requests import sign_off
from backend.tests.dashboard_reads import steps_of
from backend.tests.run_requests import latest_dispatch


def tries_on(model, claim_id):
    """Count the model calls a claim's agents made."""
    return sum(prompt[1].content == f"Claim {claim_id}" for prompt in model.prompts)


def test_the_graph(monkeypatch, no_waits):
    monkeypatch.setattr(dispatcher, "RETRY", no_waits)
    graph = dispatcher.dispatcher()
    drawn = graph.get_graph()
    assert set(drawn.nodes) == {
        "__start__",
        "list_claims",
        "work_claim",
        "finish_run",
        "__end__",
    }
    edges = {(e.source, e.target, e.conditional) for e in drawn.edges}
    assert edges == {
        ("__start__", "list_claims", False),
        ("list_claims", "work_claim", True),
        ("list_claims", "finish_run", True),
        ("work_claim", "finish_run", False),
        ("finish_run", "__end__", False),
    }
    [retry] = graph.nodes["work_claim"].retry_policy or []
    assert (retry.max_attempts, retry.initial_interval) == (3, 10)
    assert retry.retry_on == harness.TRANSIENT


def test_the_tests_retry_without_waiting():
    retry = dispatcher.RETRY
    assert (retry.initial_interval, retry.jitter) == (0, False)
    assert (retry.max_attempts, retry.retry_on) == (3, harness.TRANSIENT)


def test_never_more_than_n_claim_agents_at_once(client):
    ids = ["CLM-1001", "CLM-1003", "CLM-1004", "CLM-1005", "CLM-1006", "CLM-1007"]
    leave_waiting(*ids)
    model = swarm({claim_id: decide("refer", 0) for claim_id in ids}, pause=0.05)
    reports = dispatch(model, agents=3)

    assert model.most_at_once == 3
    assert sorted(reports) == [f"{claim_id}  refer  $0.00" for claim_id in ids]
    claims = [claim_of(client, claim_id) for claim_id in ids]
    assert {c["status"] for c in claims} == {"decided"}
    assert len({c["thread_id"] for c in claims}) == len(ids)
    finished = latest_dispatch(client)
    assert (finished["status"], finished["agents"]) == ("finished", 3)


def test_a_dispatch_works_the_claims_in_progress_and_waiting_oldest_first(client):
    leave_waiting(
        "CLM-1001", "CLM-1003", "CLM-1004", "CLM-1008", "CLM-1010", "CLM-1011"
    )
    harness.work_claim("CLM-1003", None, agent_on(stub(*decide("refer", 0))))
    harness.work_claim("CLM-1008", None, agent_on(stub(*approve("CLM-1008", 2240.0))))
    client.post("/api/claims/CLM-1010/start", json={"thread_id": "t-1010"})

    worked = ["CLM-1001", "CLM-1011", "CLM-1010", "CLM-1004"]
    dispatch(swarm({claim_id: decide("refer", 0) for claim_id in worked}))

    assert [c["claim_id"] for c in latest_dispatch(client)["claims"]] == worked
    assert claim_of(client, "CLM-1010")["thread_id"] == "t-1010"
    assert claim_of(client, "CLM-1003")["attempts"] == 1
    assert claim_of(client, "CLM-1008")["status"] == "waiting_for_sign_off"
    assert claim_of(client, "CLM-1002")["status"] == "left_for_handler"


def test_a_rate_limit_waits_and_carries_the_claim_on(client):
    leave_waiting("CLM-1001")
    limited = ModelRateLimitError("429 Too Many Requests")
    model = swarm({"CLM-1001": [call("get_claim"), limited, record("refer", 0)]})
    assert dispatch(model) == ["CLM-1001  refer  $0.00"]

    claim = claim_of(client, "CLM-1001")
    assert (claim["status"], claim["attempts"]) == ("decided", 1)
    steps = steps_of(client, "CLM-1001")
    assert {s["thread_id"] for s in steps} == {claim["thread_id"]}
    assert "error" not in {s["kind"] for s in steps}
    run_id = latest_dispatch(client)["run_id"]
    assert [w["run_id"] for w in work_times_of("CLM-1001")] == [run_id, run_id]


@pytest.mark.parametrize(
    "error",
    [ModelRateLimitError("429 Too Many Requests"), ModelTimeoutError("Timed out")],
)
def test_a_claim_still_failing_after_its_tries_is_left_in_progress(client, error):
    leave_waiting("CLM-1001", "CLM-1003")
    model = swarm({"CLM-1001": [error] * 3, "CLM-1003": decide("decline", 0)})
    began = time.monotonic()
    reports = dispatch(model)
    assert time.monotonic() - began < 5

    left = f"CLM-1001  left for the next dispatch: {type(error).__name__}: {error}"
    assert sorted(reports) == [left, "CLM-1003  decline  $0.00"]
    assert tries_on(model, "CLM-1001") == 3
    claim = claim_of(client, "CLM-1001")
    assert (claim["status"], claim["attempts"]) == ("in_progress", 1)
    assert "error" not in {s["kind"] for s in steps_of(client, "CLM-1001")}
    assert claim_of(client, "CLM-1003")["status"] == "decided"
    assert latest_dispatch(client)["status"] == "finished"


def test_a_claim_that_fails_is_tried_once_more_in_the_same_dispatch(client):
    leave_waiting("CLM-1001", "CLM-1004")
    outage = RuntimeError("503: The model is unavailable")
    model = swarm(
        {"CLM-1001": [outage, *decide("refer", 0)], "CLM-1004": [outage, outage]}
    )
    reports = dispatch(model)

    assert sorted(reports) == [
        "CLM-1001  refer  $0.00",
        "CLM-1004  failed: RuntimeError: 503: The model is unavailable,"
        " left for a handler",
    ]
    again = claim_of(client, "CLM-1001")
    assert (again["status"], again["attempts"]) == ("decided", 2)
    steps = steps_of(client, "CLM-1001")
    # Each attempt starts with the check.
    assert [s["kind"] for s in steps[:3]] == ["screening", "error", "screening"]
    assert steps[-1]["thread_id"] == again["thread_id"] != steps[0]["thread_id"]
    left = claim_of(client, "CLM-1004")
    assert (left["status"], left["attempts"]) == ("left_for_handler", 2)
    assert tries_on(model, "CLM-1004") == 2


def test_a_claim_started_elsewhere_is_reported_and_the_rest_worked(client, monkeypatch):
    leave_waiting("CLM-1001", "CLM-1003")
    start_claim = api.start_claim

    def started_elsewhere(claim_id, thread_id):
        if claim_id == "CLM-1003":
            start_claim(claim_id, "another-process")
        return start_claim(claim_id, thread_id)

    monkeypatch.setattr(api, "start_claim", started_elsewhere)
    reports = dispatch(swarm({"CLM-1001": decide("refer", 0)}))

    assert sorted(reports) == [
        "CLM-1001  refer  $0.00",
        "CLM-1003  left for the next dispatch: Refused: 409: Claim CLM-1003 is not"
        " waiting",
    ]
    assert claim_of(client, "CLM-1003")["thread_id"] == "another-process"
    assert latest_dispatch(client)["status"] == "finished"


class Work(TypedDict):
    items: list[str]
    done: Annotated[list[str], operator.add]


class Item(TypedDict):
    item: str


def test_langgraph_raises_an_error_its_handler_took_beside_another_worker():
    """LangGraph 1.2.12 still raises from invoke an error a node's error_handler
    took, when the node runs beside another, so the dispatcher doesn't use one.
    When this test fails, a release has fixed it."""
    handled = []

    def fan(state: Work) -> list[Send]:
        return [Send("work", Item(item=item)) for item in state["items"]]

    def work(state: Item) -> dict[str, list[str]]:
        if state["item"] == "bad":
            raise ValueError("bad")
        return {"done": [state["item"]]}

    def handle(state: Item, error: NodeError) -> Command:
        handled.append(state["item"])
        return Command(update={"done": ["handled"]})

    builder = StateGraph(Work)
    # The NodeError parameter is as LangGraph's docs give it; its types don't allow it.
    builder.add_node("work", work, error_handler=cast(Any, handle))
    builder.add_conditional_edges(START, fan, ["work"])
    builder.add_edge("work", END)
    graph = builder.compile()

    assert graph.invoke({"items": ["bad"], "done": []})["done"] == ["handled"]
    handled.clear()
    with pytest.raises(ValueError, match="bad"):
        graph.invoke({"items": ["bad", "good"], "done": []})
    assert handled == ["bad"]


def test_a_dispatch_stopped_partway_is_finished_by_the_next(client):
    leave_waiting("CLM-1001", "CLM-1002", "CLM-1003")
    saver = InMemorySaver()
    harness.work_claim(
        "CLM-1002", None, agent_on(stub(*approve("CLM-1002", 1350.0)), saver)
    )
    model = swarm(
        {
            "CLM-1001": [call("get_claim"), KeyboardInterrupt(), record("refer", 0)],
            "CLM-1003": [call("get_claim"), KeyboardInterrupt(), record("decline", 0)],
        },
        pause=0.05,
    )
    with pytest.raises(KeyboardInterrupt):
        dispatch(model, saver, agents=2)
    stopped = {i: claim_of(client, i) for i in ("CLM-1001", "CLM-1003")}
    assert {c["status"] for c in stopped.values()} == {"in_progress"}
    sign_off(client, "CLM-1002")

    # The sign-off paid CLM-1002, so the next dispatch leaves it alone.
    reports = dispatch(model, saver, agents=2)
    assert sorted(reports) == ["CLM-1001  refer  $0.00", "CLM-1003  decline  $0.00"]
    for claim_id, before in stopped.items():
        claim = claim_of(client, claim_id)
        assert (claim["status"], claim["attempts"]) == ("decided", 1)
        assert claim["thread_id"] == before["thread_id"]
    paid = claim_of(client, "CLM-1002")["payment"]
    assert (paid["amount"], paid["signed_off_by"]) == (1350.0, "Dana Whitfield")


def test_an_approval_whose_payment_failed_is_paid_by_the_next_dispatch(
    client, monkeypatch
):
    leave_waiting("CLM-1001")
    saver = InMemorySaver()
    fail_once(monkeypatch, api, "pay_claim", RuntimeError("The connection was lost"))
    harness.work_claim(
        "CLM-1001", None, agent_on(stub(*approve("CLM-1001", 420.0)), saver)
    )
    assert claim_of(client, "CLM-1001")["status"] == "in_progress"

    assert dispatch(stub(), saver) == ["CLM-1001  approve  $420.00"]
    assert claim_of(client, "CLM-1001")["payment"]["amount"] == 420.0


def test_a_dispatch_with_nothing_to_work_finishes(client):
    leave_waiting()
    assert dispatch(stub()) == []
    finished = latest_dispatch(client)
    assert (finished["status"], finished["claims"]) == ("finished", [])
    assert finished["summary"]["approved"] == 0
