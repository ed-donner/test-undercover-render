"""The claim agent's two routes to its tools and its payment: through the Gateway,
signed, or directly to the app."""

import asyncio
import json
from typing import cast

import pytest
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver

from agent import api, direct, harness
from agent.direct import CONTEXT_URL
from agent.gateway import GATEWAY_URL, Gateway
from agent.mcp_tools import McpTools
from agent.routes import Target
from agent.tests.gateway_stand_in import DENIED
from agent.tests.records import claim_of, payments_of
from agent.tests.stubs import (
    agent_on,
    approve,
    calculate,
    call,
    decide,
    flags,
    passes,
    record,
    stub,
)
from agent.tools import claim_as_read
from backend.agent_api import OPERATIONS
from backend.tests.claim_requests import sign_off, start
from backend.tests.dashboard_reads import steps_of
from backend.tests.settings_requests import change_settings

APP = "undercover-app___"
CONTEXT = "undercover-context___"
DELAY = [
    {"description": "Hotel", "amount": 245, "quantity": 1, "kind": "hotel",
     "nights": 1, "hours": 0},
    {"description": "Meals", "amount": 95, "quantity": 1, "kind": "expense",
     "nights": 0, "hours": 0},
    {"description": "Taxis", "amount": 80, "quantity": 1, "kind": "expense",
     "nights": 0, "hours": 0},
]  # fmt: skip


def on_the_gateway(gateway, model, **kwargs):
    return agent_on(model, route=Gateway(gateway.url), **kwargs)


@pytest.fixture(params=["direct", "gateway"])
def route_name(request):
    return request.param


@pytest.fixture
def route(request, route_name):
    """Each route in turn: directly to the app, or through the stand-in Gateway."""
    if route_name == "direct":
        return direct.from_environment()
    return Gateway(request.getfixturevalue("gateway").url)


def test_the_models_tools_are_the_same_on_both_routes(gateway):
    on_each = []
    for route in (direct.from_environment(), Gateway(gateway.url)):
        model = stub()
        agent_on(model, route=route)
        [tools] = model.bound_tools
        on_each.append([(tool.name, tool.args) for tool in tools])
    assert on_each[0] == on_each[1]
    inputs = {name: set(args) for name, args in on_each[0]}
    for name in ("get_claim", "get_policy", "get_claim_history", "calculate_payout"):
        assert {"claim_id", "policy_id", "customer_id"} & inputs[name] == set()


def test_the_gateway_route_reads_decides_and_pays_through_the_gateway(client, gateway):
    model = stub(
        call("get_claim"),
        call("get_policy"),
        call("get_claim_history"),
        call("calculate_payout", benefit="trip_delay", lines=DELAY, paid_by_others=0),
        record("approve", 420.0),
    )
    report = harness.work_claim("CLM-1001", None, on_the_gateway(gateway, model))
    assert report == "CLM-1001  approve  $420.00"
    assert gateway.names == [
        f"{APP}get_claim",
        f"{APP}get_policy",
        f"{APP}get_claim_history",
        f"{APP}calculate_payout",
        f"{APP}record_decision",
        f"{APP}pay_claim",
    ]
    inputs = [call.inputs for call in gateway.calls]
    assert inputs[:3] == [
        {"claim_id": "CLM-1001"},
        {"policy_id": "POL-2001"},
        {"customer_id": "CUS-3001"},
    ]
    assert inputs[3]["claim_id"] == inputs[4]["claim_id"] == "CLM-1001"
    assert inputs[5] == {"claim_id": "CLM-1001", "amount": 420.0}
    assert all(call.signed for call in gateway.calls)
    claim = claim_of(client, "CLM-1001")
    assert claim["status"] == "decided"
    assert [p["amount"] for p in payments_of("CLM-1001")] == [420.0]


def test_the_bookkeeping_and_the_checks_referral_skip_the_gateway(client, gateway):
    report = harness.work_claim(
        "CLM-1901", None, on_the_gateway(gateway, stub(), screener=flags())
    )
    assert report == "CLM-1901  refer  $0.00"
    assert gateway.calls == []
    model = stub(*decide("refer", 0))
    harness.work_claim("CLM-1003", None, on_the_gateway(gateway, model))
    assert gateway.names == [f"{APP}get_claim", f"{APP}record_decision"]


def test_get_claim_gives_the_same_text_on_both_routes(client, gateway):
    start(client, "CLM-1003")
    claim = {"claim_id": "CLM-1003"}
    on_each = [
        claim_as_read(route.call(Target.APP, "get_claim", claim))
        for route in (direct.from_environment(), Gateway(gateway.url))
    ]
    assert on_each[0] == on_each[1] == claim_as_read(api.get_claim("CLM-1003"))


def test_the_check_reads_what_get_claim_gives_on_the_gateway(client, gateway):
    screener = passes()
    model = stub(*decide("refer", 0))
    agent = on_the_gateway(gateway, model, screener=screener)
    harness.work_claim("CLM-1003", None, agent)
    [[_, read]] = screener.prompts
    tool_message = model.prompts[1][-1]
    assert isinstance(tool_message, ToolMessage)
    assert gateway.names[0] == f"{APP}get_claim"
    assert read == HumanMessage(tool_message.text)


def test_a_decision_the_app_refuses_is_a_refusal_on_each_route(
    client, route_name, route
):
    model = stub(
        record("approve", 0), calculate("CLM-1001", 420.0), record("approve", 420.0)
    )
    report = harness.work_claim("CLM-1001", None, agent_on(model, route=route))
    assert report == "CLM-1001  approve  $420.00"
    refusal = model.prompts[1][-1]
    assert isinstance(refusal, ToolMessage)
    # The app's answer: through the agent's API, its status and reason, and
    # through the Gateway, the body the app answered with.
    answer = {"direct": "Refused with status 422: ", "gateway": 'Refused: {"detail":'}
    assert refusal.text.startswith(answer[route_name])
    assert "section 14: an approval needs a payout above zero" in refusal.text
    refusals = [s for s in steps_of(client, "CLM-1001") if s["kind"] == "refusal"]
    name = route.name(Target.APP, "record_decision")
    assert [s["content"] for s in refusals] == [f"{name}: {refusal.text}"]
    assert claim_of(client, "CLM-1001")["payment"]["amount"] == 420.0


def test_a_tool_the_gateway_refuses_is_a_refusal_and_the_work_goes_on(client, gateway):
    gateway.refused.add(f"{APP}get_policy")
    model = stub(call("get_policy"), *decide("refer", 0))
    report = harness.work_claim("CLM-1003", None, on_the_gateway(gateway, model))
    assert report == "CLM-1003  refer  $0.00"
    refusal = model.prompts[1][-1]
    assert refusal.text == f"Refused by the Gateway: {DENIED}"
    [step] = [s for s in steps_of(client, "CLM-1003") if s["kind"] == "refusal"]
    assert step["content"] == f"{APP}get_policy: Refused by the Gateway: {DENIED}"


def test_a_payment_the_gateway_refuses_waits_for_a_handlers_sign_off(client, gateway):
    change_settings(client, approval_limit=2000.0)
    model = stub(*approve("CLM-1002", 1500.0))
    agent = on_the_gateway(gateway, model)
    report = harness.work_claim("CLM-1002", None, agent)
    assert report == "CLM-1002  approve  $1,500.00, waiting for sign-off"
    assert gateway.names[-1] == f"{APP}pay_claim"
    claim = claim_of(client, "CLM-1002")
    assert (claim["status"], claim["payment"]) == ("waiting_for_sign_off", None)
    assert claim["decision"]["gateway_refusal"] == DENIED
    refusal = steps_of(client, "CLM-1002")[-1]
    assert (refusal["kind"], refusal["content"]) == (
        "refusal",
        f"{APP}pay_claim: Refused by the Gateway: {DENIED}",
    )

    assert harness.paused(claim, agent)

    assert sign_off(client, "CLM-1002").status_code == 200
    steps = steps_of(client, "CLM-1002")
    assert harness.resume("CLM-1002", agent) == "CLM-1002  approve  $1,500.00"
    assert len(model.prompts) == 3
    assert steps_of(client, "CLM-1002") == steps
    assert [p["amount"] for p in payments_of("CLM-1002")] == [1500.0]


def test_the_route_is_read_when_the_claim_agents_are_built(gateway, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(harness, "PostgresSaver", lambda pool: InMemorySaver())
    version = api.get_current_version()
    monkeypatch.setenv(GATEWAY_URL, gateway.url)
    no_pool = cast(harness.Pool, None)
    assert isinstance(harness.claim_graphs(version, None, no_pool)().route, Gateway)
    monkeypatch.delenv(GATEWAY_URL)
    assert isinstance(
        harness.claim_graphs(version, None, no_pool)().route, direct.Direct
    )


def test_an_mcp_call_leaves_the_main_threads_event_loop(gateway):
    loop = asyncio.get_event_loop()
    stand_in = McpTools("The stand-in Gateway", gateway.url)
    stand_in.call(f"{APP}get_claim", {"claim_id": "CLM-1001"})
    assert asyncio.get_event_loop() is loop
    assert not loop.is_closed()


def test_the_stand_ins_app_tools_are_the_agents_api_documents_operations(
    client, gateway
):
    document = client.get("/api/agent/openapi.json").json()
    tools = {op.tool.name: op.tool for op in gateway.operations.values()}
    assert set(tools) == {f"{APP}{operation}" for operation in OPERATIONS}
    for path, methods in document["paths"].items():
        for operation in methods.values():
            tool = tools[f"{APP}{operation['operationId']}"]
            named = {p["name"] for p in operation.get("parameters", [])}
            assert named <= set(tool.inputSchema["properties"]), path
    pay_claim = tools[f"{APP}pay_claim"].inputSchema
    record_decision = tools[f"{APP}record_decision"].inputSchema
    assert set(pay_claim["properties"]) == {"claim_id", "amount"}
    assert set(record_decision["required"]) == {
        "claim_id",
        "decision",
        "payout",
        "section",
        "reason",
        "decided_by",
    }


CONTEXT_CALLS = [
    call("lookup_term", term="unattended"),
    call("describe_fields", record="claim"),
    call("get_plan", plan="premium"),
    call("get_claim_rules"),
    call("search_reference_data", query="Lisbon strike"),
    call("search_documents", query="unattended"),
    call("read_section", document="claims_manual", number=14),
    call("read_section", document="claims_manual", number=99),
]


def test_the_context_layers_tools_answer_on_each_route(
    client, request, route_name, route
):
    model = stub(*CONTEXT_CALLS, *decide("refer", 0))
    report = harness.work_claim("CLM-1003", None, agent_on(model, route=route))
    assert report == "CLM-1003  refer  $0.00"
    *answers, refused = [
        m for m in model.prompts[len(CONTEXT_CALLS)] if isinstance(m, ToolMessage)
    ]
    files = [json.loads(a.text)["sources"][0]["file"] for a in answers]
    assert files == [
        "glossary.yaml",
        "data_dictionary.yaml",
        "plans.yaml",
        "claim_rules.yaml",
        "reference_data.yaml",
        "policy_wording.md",
        "claims_manual.md",
    ]
    assert refused.status == "error"
    assert refused.text.startswith("Refused: ")
    assert refused.text.endswith("Section 99 of the claims manual not found")
    if route_name == "gateway":
        gateway = request.getfixturevalue("gateway")
        context_calls = [n for n in gateway.names if n.startswith(CONTEXT)]
        assert context_calls == [
            f"{CONTEXT}{c.tool_calls[0]['name']}" for c in CONTEXT_CALLS
        ]


# A port nothing on the laptop listens on.
NOBODY = "http://127.0.0.1:9/mcp"


def test_a_context_layer_that_isnt_answering_says_so_in_a_line(monkeypatch):
    monkeypatch.setenv(CONTEXT_URL, NOBODY)
    with pytest.raises(ConnectionError) as down:
        direct.from_environment()
    assert str(down.value) == f"The context layer isn't answering at {NOBODY}"
