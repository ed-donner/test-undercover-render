"""The Copilot's loop: its lookups and actions, each a card, refusals passed on to
the model, one tool at a time, a turn's model calls limited, a failed turn and a
message after it, and the handler's sign-in on every request it sends."""

import itertools
import json

import pytest
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage

from agent.connection import Refused
from agent.copilot import app_api, turns
from agent.copilot.tools import COPILOT_TOOLS, KINDS
from agent.gateway import GATEWAY_URL
from agent.tests.copilot_driver import Copilot
from agent.tests.stubs import USAGE, call, stub
from backend.tests.claim_requests import held
from backend.tests.copilot_requests import latest, started
from backend.tests.run_requests import another_running_dispatch, fail_run, run_path
from backend.tests.sign_in import DANA, MARCUS, OTHER_KEY, token

WHY = "Why does CLM-1003 need me?"
ANSWER = "CLM-1003 is held for your sign-off at $3,750.00."


def cards_of(turn):
    return [(card["tool"], card["input"], card["status"]) for card in turn["steps"]]


def test_the_loop(client, copilot: Copilot):
    held(client, "CLM-1003", 3750.0)
    copilot.model = stub(
        call("get_claim", claim_id="CLM-1003"),
        call("list_steps", claim_id="CLM-1003"),
        call("read_section", document="claims_manual", number=6),
        ANSWER,
    )
    conversation = copilot.ask(WHY)
    [turn] = conversation["turns"]
    assert cards_of(turn) == [
        ("get_claim", "CLM-1003", "done"),
        ("list_steps", "CLM-1003", "done"),
        ("read_section", "claims_manual 6", "done"),
    ]
    assert all(card["finished_at"] and card["seconds"] >= 0 for card in turn["steps"])
    [source] = turn["steps"][2]["sources"]
    assert set(source) == {"file", "system", "owner", "reviewed"}
    assert source["file"].startswith("claims_manual")
    assert (turn["status"], turn["answer"], turn["model_calls"]) == ("done", ANSWER, 4)
    assert turn["cost"] == pytest.approx(4 * USAGE["cost"])


def test_the_model_knows_who_it_works_for(copilot: Copilot):
    copilot.model = stub("Hello, Dana.")
    copilot.ask("Hello")
    [system, *_] = copilot.model.prompts[0]
    assert isinstance(system, SystemMessage)
    assert "Dana Whitfield, Senior Claims Handler" in system.text
    assert "They can sign off payouts over the approval limit." in system.text
    copilot.model = stub("Hello, Marcus.")
    copilot.ask("Hello", email=MARCUS)
    [system, *_] = copilot.model.prompts[0]
    assert "Marcus Oyelaran, Claims Handler" in system.text
    assert "They can't sign off payouts over the approval limit" in system.text


def test_a_refusal_goes_back_to_the_model(copilot: Copilot):
    another_running_dispatch()
    copilot.model = stub(call("start_dispatch", agents=10), "A dispatch is running.")
    [turn] = copilot.ask("Work the queue with 10 agents")["turns"]
    [card] = turn["steps"]
    assert (card["tool"], card["kind"], card["status"], card["reason"]) == (
        "start_dispatch",
        "action",
        "refused",
        "A dispatch is running",
    )
    refusal = copilot.model.prompts[1][-1]
    assert isinstance(refusal, ToolMessage)
    assert refusal.text == "Refused: A dispatch is running"


def run_started(client, copilot: Copilot) -> dict:
    """The run the model was told it started, as the agent reads it."""
    started = json.loads(copilot.model.prompts[1][-1].text)
    run = client.get(run_path(started["run_id"])).json()
    assert started == {"run_id": run["run_id"], "number": run["number"]}
    fail_run(client, run["run_id"])
    return run


def test_starts_with_the_agents_asked_for_or_the_settings(client, copilot: Copilot):
    copilot.model = stub(call("start_dispatch", agents=10), "Started.")
    copilot.ask("Work the queue with 10 agents")
    run = run_started(client, copilot)
    assert (run["kind"], run["agents"]) == ("dispatch", 10)
    copilot.model = stub(call("start_dispatch", agents=None), "Started.")
    copilot.ask("Work the queue")
    assert run_started(client, copilot)["agents"] == 25
    copilot.model = stub(
        call("start_evaluation", evaluation_set="held_out", tiny=True, agents=None),
        "Started.",
    )
    copilot.ask("Evaluate the held-out set's tiny claims")
    run = run_started(client, copilot)
    assert (run["kind"], run["evaluation_set"], run["tiny"], run["agents"]) == (
        "evaluation",
        "held_out",
        True,
        25,
    )


NOTE = "Check the hotel receipts again."


def test_a_send_back_as_the_handler_who_asks(client, copilot: Copilot, agent_calls):
    held(client, "CLM-1008", 2240.0)
    copilot.model = stub(
        call("send_back_claim", claim_id="CLM-1008", note=NOTE), "Sent back."
    )
    [turn] = copilot.ask("Send CLM-1008 back")["turns"]
    assert cards_of(turn) == [("send_back_claim", f"CLM-1008 {NOTE}", "done")]
    [sent_back] = client.get("/api/claims/CLM-1008").json()["sent_back_decisions"]
    assert (sent_back["note"], sent_back["sent_back_by"]) == (NOTE, "Dana Whitfield")
    assert agent_calls[-1] == {"operation": "resume_claim", "claim_id": "CLM-1008"}
    held(client, "CLM-1011", 1150.0)
    copilot.model = stub(
        call("send_back_claim", claim_id="CLM-1011", note=NOTE), "I can't."
    )
    [turn] = copilot.ask("Send CLM-1011 back", email=MARCUS)["turns"]
    [card] = turn["steps"]
    assert (card["status"], card["reason"]) == (
        "refused",
        "Only a handler who can sign off payouts over $1,000.00 can send this back. "
        "Marcus Oyelaran can't.",
    )


def test_one_tool_at_a_time_in_order(client, copilot: Copilot):
    held(client, "CLM-1003", 3750.0)
    calls = [
        call("get_claim", claim_id="CLM-1003"),
        call("get_policy", policy_id="POL-2003"),
        call("lookup_term", term="Trip Delay"),
    ]
    together = AIMessage(content="", tool_calls=[c.tool_calls[0] for c in calls])
    copilot.model = stub(together, ANSWER)
    [turn] = copilot.ask(WHY)["turns"]
    assert [card["tool"] for card in turn["steps"]] == [
        "get_claim",
        "get_policy",
        "lookup_term",
    ]
    for before, after in itertools.pairwise(turn["steps"]):
        assert before["finished_at"] <= after["started_at"]
    assert copilot.model.bound_with[-1] == {"parallel_tool_calls": False}


def test_a_turn_makes_25_model_calls_at_most(copilot: Copilot):
    copilot.model = stub(*[call("get_settings") for _ in range(26)])
    conversation = copilot.ask("Keep looking")
    [turn] = conversation["turns"]
    assert (turn["status"], turn["failure"]) == (
        "failed",
        "TooManyModelCalls: The Copilot made 25 model calls without finishing",
    )
    assert len(copilot.model.prompts) == 25
    copilot.model = stub("Hello again.")
    later = copilot.ask("Hello", conversation["conversation_id"])["turns"][-1]
    assert (later["status"], later["model_calls"]) == ("done", 1)


def test_a_failed_turn_and_a_message_after_it(copilot: Copilot, monkeypatch):
    def broken(sign_in):
        raise RuntimeError("The queue broke\nwith a long story")

    monkeypatch.setattr(app_api, "list_claims", broken)
    asked = call("list_claims")
    copilot.model = stub(asked)
    conversation = copilot.ask("What's in the queue?")
    [turn] = conversation["turns"]
    [card] = turn["steps"]
    assert (card["status"], card["reason"]) == (
        "failed",
        "RuntimeError: The queue broke",
    )
    assert (turn["status"], turn["failure"]) == (
        "failed",
        "RuntimeError: The queue broke",
    )
    copilot.model = stub("Here it is.")
    copilot.ask("Try again", conversation["conversation_id"])
    sent = copilot.model.prompts[0]
    closed, message = sent[-2], sent[-1]
    assert isinstance(closed, ToolMessage)
    assert (closed.tool_call_id, closed.text) == (
        asked.tool_calls[0]["id"],
        "This step stopped before it finished",
    )
    assert message.text == "Try again"
    calls = {c["id"] for m in sent if isinstance(m, AIMessage) for c in m.tool_calls}
    answered = {m.tool_call_id for m in sent if isinstance(m, ToolMessage)}
    assert calls <= answered


def test_who_is_signed_in_comes_first(copilot: Copilot):
    copilot.model = stub()
    conversation = started(copilot.dashboard)
    turn_id = latest(conversation)["turn_id"]
    with pytest.raises(Refused) as refused:
        turns.the_turn(
            token(DANA, key=OTHER_KEY), conversation["conversation_id"], turn_id
        )
    assert refused.value.status_code == 401
    with pytest.raises(Refused) as refused:
        turns.the_turn(token(MARCUS), conversation["conversation_id"], turn_id)
    assert refused.value.status_code == 404
    with pytest.raises(turns.NotThisTurn):
        turns.the_turn(token(DANA), conversation["conversation_id"], "turn-0")
    assert copilot.model.prompts == []


def test_the_gateway_route_for_the_context_layer(
    copilot: Copilot, gateway, monkeypatch
):
    monkeypatch.setenv(GATEWAY_URL, gateway.url)
    copilot.model = stub(
        call("read_section", document="policy_wording", number=3), "Read."
    )
    [turn] = copilot.ask("What does section 3 say?")["turns"]
    assert gateway.names == ["undercover-context___read_section"]
    assert all(c.signed for c in gateway.calls)
    assert cards_of(turn) == [("read_section", "policy_wording 3", "done")]


def test_the_copilots_tools(copilot: Copilot):
    copilot.model = stub("Hello.")
    copilot.ask("Hello")
    [bound] = copilot.model.bound_tools
    named = [getattr(t, "name", None) or t.model_config["title"] for t in bound]
    assert named == [
        "list_claims",
        "get_claim",
        "list_steps",
        "what_needs_a_handler",
        "find_customers",
        "get_customer",
        "get_policy",
        "lookup_term",
        "describe_fields",
        "get_plan",
        "get_claim_rules",
        "search_reference_data",
        "search_documents",
        "read_section",
        "get_latest_dispatch",
        "list_evaluations",
        "get_settings",
        "wait_for_run",
        "start_dispatch",
        "start_evaluation",
        "send_back_claim",
        "check_success_criteria",
        "sign_off_claim",
    ]
    for tool in COPILOT_TOOLS:
        assert tool.description, tool.name
        assert "\n" not in tool.description, tool.name
    assert KINDS == {
        "list_claims": "claims",
        "get_claim": "claims",
        "list_steps": "claims",
        "what_needs_a_handler": "claims",
        "find_customers": "customers",
        "get_customer": "customers",
        "get_policy": "customers",
        "lookup_term": "context",
        "describe_fields": "context",
        "get_plan": "context",
        "get_claim_rules": "context",
        "search_reference_data": "context",
        "search_documents": "context",
        "read_section": "context",
        "get_latest_dispatch": "work",
        "list_evaluations": "work",
        "get_settings": "work",
        "wait_for_run": "work",
        "search_memory": "memory",
        "start_dispatch": "action",
        "start_evaluation": "action",
        "send_back_claim": "action",
        "sign_off_claim": "action",
        "check_success_criteria": "action",
    }


def test_the_lookups_each_with_a_card(client, copilot: Copilot):
    copilot.model = stub(
        AIMessage(
            content="",
            tool_calls=[
                {"name": "find_customers", "args": {"name": "maya"}, "id": "f"}
            ],
        ),
        call("get_customer", customer_id="CUS-3001"),
        call("get_policy", policy_id="POL-2001"),
        call("get_latest_dispatch"),
        call("list_evaluations"),
        call("get_settings"),
        "Maya Patel has one policy.",
    )
    [turn] = copilot.ask("Tell me about Maya Patel")["turns"]
    assert [(c["tool"], c["kind"], c["status"]) for c in turn["steps"]] == [
        ("find_customers", "customers", "done"),
        ("get_customer", "customers", "done"),
        ("get_policy", "customers", "done"),
        ("get_latest_dispatch", "work", "done"),
        ("list_evaluations", "work", "done"),
        ("get_settings", "work", "done"),
    ]
    found = copilot.model.prompts[1][-1]
    assert json.loads(found.text) == [{"customer_id": "CUS-3001", "name": "Maya Patel"}]


def test_a_call_with_bad_inputs_or_to_no_such_tool_goes_back_to_the_model(
    copilot: Copilot,
):
    copilot.model = stub(
        call("get_claim"), call("pay_claim", claim_id="CLM-1001"), "Ok."
    )
    [turn] = copilot.ask("Look at a claim")["turns"]
    [card] = turn["steps"]
    assert (card["tool"], card["status"]) == ("get_claim", "refused")
    assert "claim_id" in card["reason"]
    bad, missing = copilot.model.prompts[1][-1], copilot.model.prompts[2][-1]
    assert bad.text.startswith("Refused: ")
    assert "pay_claim is not a valid tool" in missing.text


def test_the_model_is_the_one_the_app_names(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    model = turns.copilot_model(token(DANA))
    assert (model.model_name, model.reasoning_effort) == ("openai/gpt-6-luna", "low")


def test_a_sign_in_that_runs_out_partway_leaves_the_turn_for_the_app_to_stop(
    copilot: Copilot, monkeypatch
):
    """Once the sign-in runs out, the app refuses every call made with it, so the
    Copilot can't mark the card or the turn failed: the turn stops at once, with
    no more model calls, and the app shows it working until it reads as stopped."""
    call_as = app_api.call_as
    ran_out = False

    def runs_out_at_the_queue(sign_in: str, method: str, path: str, **request):
        nonlocal ran_out
        ran_out = ran_out or path == "/claims"
        if ran_out:
            raise Refused(401, "The sign-in isn't valid. Please sign in again.")
        return call_as(sign_in, method, path, **request)

    monkeypatch.setattr(app_api, "call_as", runs_out_at_the_queue)
    copilot.model = stub(call("list_claims"), "Never asked.")
    with pytest.raises(Refused):
        copilot.ask("What's in the queue?")
    conversation = copilot.read(copilot.last_payload()["conversation_id"])
    [turn] = conversation["turns"]
    [card] = turn["steps"]
    assert (turn["status"], card["status"]) == ("working", "working")
    assert len(copilot.model.prompts) == 1
