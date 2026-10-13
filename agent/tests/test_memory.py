"""The claim agent's memory of each customer: what it saves of a decided claim, and
what a search of the customer's memories finds."""

import logging
from functools import partial
from typing import cast

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver

from agent import agentcore_memory, api, app_terms, checkpoints, harness, memory
from agent.memory import MEMORY_ID
from agent.tests.dispatching import new_dispatch
from agent.tests.failures import fail_once
from agent.tests.memory_stand_in import MemoryStandIn
from agent.tests.records import claim_of
from agent.tests.stubs import agent_on, approve, call, decide, flags, stub

FACTS = "/customers/CUS-3005/facts/"
FIRST_CLAIM = "/customers/CUS-3005/claims/CLM-1005/"
SECOND_CLAIM = "/customers/CUS-3005/claims/CLM-1006/"
SOMEONE_ELSES = "/customers/CUS-3001/claims/CLM-1001/"


def tools_of(agent):
    """The names of the tools a claim agent's graph runs."""
    return set(agent.graph.nodes[harness.TOOLS].bound.tools_by_name)


def test_an_approval_paid_saves_the_claim_and_the_decision(client):
    store = MemoryStandIn()
    agent = agent_on(stub(*approve("CLM-1001", 420.0)), store=store)
    assert harness.work_claim("CLM-1001", None, agent) == "CLM-1001  approve  $420.00"
    claimed, decided = store.events
    assert (claimed.actor, claimed.session) == ("CUS-3001", "CLM-1001")
    assert (decided.actor, decided.session) == ("CUS-3001", "CLM-1001")
    assert isinstance(claimed.message, HumanMessage)
    assert isinstance(decided.message, AIMessage)
    claim = claim_of(client, "CLM-1001")
    for shown in (
        claim["summary"],
        claim["claim_type"],
        claim["incident_date"],
        claim["incident_location"],
        claim["items"][0]["description"],
    ):
        assert shown in claimed.message.text
    assert decided.message.text == (
        "Decision on CLM-1001: approve, paying $420.00, under Section 3, Trip Delay. "
        "The delay was covered."
    )
    for kept_on_the_claim in (claim["story"], claim["documents"][0]["content"]):
        assert kept_on_the_claim not in claimed.message.text
        assert kept_on_the_claim not in decided.message.text


@pytest.mark.parametrize(
    ("claim_id", "replies", "report"),
    [
        ("CLM-1003", partial(decide, "decline", 0), "CLM-1003  decline  $0.00"),
        ("CLM-1004", partial(decide, "refer", 0), "CLM-1004  refer  $0.00"),
    ],
)
def test_each_decision_the_claim_agent_makes_is_saved(
    client, claim_id, replies, report
):
    store = MemoryStandIn()
    agent = agent_on(stub(*replies()), store=store)
    assert harness.work_claim(claim_id, None, agent) == report
    customer_id = claim_of(client, claim_id)["customer_id"]
    assert [(e.actor, e.session) for e in store.events] == [(customer_id, claim_id)] * 2


def test_a_claim_the_check_referred_is_never_saved(client):
    store = MemoryStandIn()
    agent = agent_on(stub(), screener=flags(), store=store)
    assert harness.work_claim("CLM-1901", None, agent) == "CLM-1901  refer  $0.00"
    assert store.events == []


def test_a_claim_that_fails_before_its_decision_is_never_saved(client):
    store = MemoryStandIn()
    outage = RuntimeError("503: The model is unavailable")
    agent = agent_on(stub(call("get_claim"), outage), store=store)
    assert harness.work_claim("CLM-1004", None, agent).endswith("back in the queue")
    assert store.events == []


def test_an_approval_stopped_before_its_payment_is_saved_once_it_is_paid(
    client, monkeypatch
):
    store, saver = MemoryStandIn(), InMemorySaver()
    fail_once(monkeypatch, api, "pay_claim", KeyboardInterrupt())
    agent = agent_on(stub(*approve("CLM-1001", 420.0)), saver, store=store)
    with pytest.raises(KeyboardInterrupt):
        harness.work_claim("CLM-1001", None, agent)
    assert claim_of(client, "CLM-1001")["status"] == "in_progress"
    assert store.events == []
    # The dispatcher carries on a claim in progress; once it's paid and
    # remembered, its work has ended and there's nothing left to run.
    again = agent_on(stub(), saver, store=store)
    run_id = new_dispatch()["run_id"]
    assert harness.work_in_run("CLM-1001", run_id, lambda: again) == (
        "CLM-1001  approve  $420.00"
    )
    assert len(store.events) == 2
    assert harness.carry_on("CLM-1001", None, again) == "CLM-1001  approve  $420.00"
    assert len(store.events) == 2


def search(store, query="earlier claims"):
    """A claim agent on CLM-1006, Oliver Grant's second claim, that searches its
    memory, then refers the claim. Return what the search answered."""
    model = stub(call("search_memory", query=query), *decide("refer", 0))
    harness.work_claim("CLM-1006", None, agent_on(model, store=store))
    answer = model.prompts[1][-1]
    assert isinstance(answer, ToolMessage)
    return answer


def test_a_search_finds_only_the_customers_memories_and_not_this_claims_summary(
    client,
):
    store = MemoryStandIn(
        memories=[
            (FACTS, "Oliver Grant travels with his partner."),
            (FIRST_CLAIM, "CLM-1005 was approved for $243.00."),
            (SECOND_CLAIM, "CLM-1006, worked before, was referred."),
            (SOMEONE_ELSES, "Maya Patel's delayed flight was approved."),
        ]
    )
    answer = search(store)
    assert store.searched == ["/customers/CUS-3005"]
    assert answer.status != "error"
    assert answer.text == (
        '["Oliver Grant travels with his partner.", '
        '"CLM-1005 was approved for $243.00."]'
    )


def test_with_no_memory_or_in_an_evaluation_there_is_nothing_to_remember(
    monkeypatch,
):
    plain = agent_on(stub())
    assert harness.REMEMBER not in plain.graph.nodes
    assert "search_memory" not in tools_of(plain)

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(harness, "PostgresSaver", lambda pool: InMemorySaver())
    monkeypatch.setattr(memory, "memory_store", MemoryStandIn)
    version = api.get_current_version()
    no_pool = cast(checkpoints.Pool, None)
    evaluation = harness.claim_graphs(version, app_terms.EVALUATION, no_pool)()
    assert harness.REMEMBER not in evaluation.graph.nodes
    assert "search_memory" not in tools_of(evaluation)
    dispatch = harness.claim_graphs(version, app_terms.DISPATCH, no_pool)()
    assert harness.REMEMBER in dispatch.graph.nodes
    assert "search_memory" in tools_of(dispatch)


def test_a_memory_that_cant_be_reached_leaves_the_decision_and_refuses_a_search(
    client, caplog
):
    store = MemoryStandIn(reachable=False)
    agent = agent_on(stub(*decide("decline", 0)), store=store)
    assert harness.work_claim("CLM-1003", None, agent) == "CLM-1003  decline  $0.00"
    assert claim_of(client, "CLM-1003")["decision"]["decision"] == "decline"
    [warning] = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warning.getMessage().startswith(
        "CLM-1003  EndpointConnectionError: Could not connect"
    )
    refusal = search(store)
    assert refusal.status == "error"
    assert refusal.text.startswith("Refused: The memory can't be reached.")


def test_the_memory_is_read_when_the_claim_agents_are_built(monkeypatch):
    made = []

    def recorder(**settings):
        made.append(settings)
        return MemoryStandIn()

    monkeypatch.setattr(agentcore_memory, "AgentCoreMemoryStore", recorder)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-2")
    monkeypatch.setattr(harness, "PostgresSaver", lambda pool: InMemorySaver())
    version = api.get_current_version()
    no_pool = cast(checkpoints.Pool, None)
    without = harness.claim_graphs(version, None, no_pool)()
    assert harness.REMEMBER not in without.graph.nodes
    monkeypatch.setenv(MEMORY_ID, "undercover_memory-abc")
    agent = harness.claim_graphs(version, None, no_pool)()
    assert harness.REMEMBER in agent.graph.nodes
    assert made == [{"memory_id": "undercover_memory-abc", "region_name": "eu-west-2"}]
