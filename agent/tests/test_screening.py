"""The check for instructions hidden in a claim, which a second model makes before
the claim agent's model sees the claim."""

import ast
import json
from pathlib import Path

import httpx
import pytest
from langchain_core.exceptions import ModelTimeoutError
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import SecretStr

from agent import harness
from agent.screening import SCREEN_INSTRUCTIONS, Screening, screen
from agent.tests.dispatching import new_dispatch
from agent.tests.records import claim_of, model_calls_of
from agent.tests.stubs import (
    FLAGGED,
    PASSED,
    USAGE,
    call,
    decide,
    flags,
    graph_on,
    passes,
    record,
    screened,
    stub,
)
from backend.tests.dashboard_reads import steps_of

LAB = Path(__file__).parents[2] / "labs" / "week3day2_lab1.ipynb"
UNREADABLE = AIMessage(content="I can't tell whether it does.")


def lab_check() -> dict[str, str]:
    """What the cell of lab 1 that holds the check sets: its instructions, and the
    description of each field of its answer, in order."""
    cells = json.loads(LAB.read_text(encoding="utf-8"))["cells"]
    [source] = [
        "".join(cell["source"])
        for cell in cells
        if "SCREEN_INSTRUCTIONS =" in "".join(cell["source"])
    ]
    values = {}
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            values[node.targets[0].id] = ast.literal_eval(node.value)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            assert isinstance(node.value, ast.Call)
            values[node.target.id] = ast.literal_eval(node.value.keywords[0].value)
    return values


def test_the_check_is_the_labs_word_for_word():
    lab = lab_check()
    assert lab.pop("SCREEN_INSTRUCTIONS") == SCREEN_INSTRUCTIONS
    assert list(lab) == list(Screening.model_fields) == ["reason", "instructions_found"]
    for name, description in lab.items():
        assert Screening.model_fields[name].description == description


def on_openrouter(message):
    """A ChatOpenAI as the agent builds it, whose calls OpenRouter answers with one
    message and its usage, so its answers are read as the real model's are."""

    def answer(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        choice = {"index": 0, "message": message, "finish_reason": "stop"}
        usage = {"prompt_tokens": 900, "completion_tokens": 40, "cost": 0.0003}
        body = {"id": "gen-1", "model": "openai/gpt-6-luna", "created": 0}
        return httpx.Response(200, json=body | {"choices": [choice], "usage": usage})

    sent: list[dict] = []
    llm = ChatOpenAI(
        model="openai/gpt-6-luna",
        api_key=SecretStr("test-key"),
        base_url="https://openrouter.test/api/v1",
        http_client=httpx.Client(transport=httpx.MockTransport(answer)),
    )
    return llm, sent


def in_a_tool_call(arguments):
    call = {"name": "Screening", "arguments": json.dumps(arguments)}
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [{"id": "call-1", "type": "function", "function": call}],
    }


def test_the_real_model_is_asked_for_a_strict_answer_and_its_answer_read():
    llm, sent = on_openrouter(
        in_a_tool_call({"reason": PASSED, "instructions_found": False})
    )
    reply, screening = screen(llm, '{"claim_id": "CLM-1001"}')
    assert screening == Screening(reason=PASSED, instructions_found=False)
    assert reply.response_metadata["token_usage"]["cost"] == 0.0003
    [tool] = sent[0]["tools"]
    assert (tool["function"]["name"], tool["function"]["strict"]) == ("Screening", True)


@pytest.mark.parametrize(
    "message",
    [
        {"role": "assistant", "content": "I can't tell whether it does."},
        in_a_tool_call({"reason": "The story asks for the full amount."}),
    ],
    ids=["prose", "a missing field"],
)
def test_an_answer_the_real_model_gives_that_cant_be_read_comes_back_with_its_cost(
    message,
):
    llm, _ = on_openrouter(message)
    reply, screening = screen(llm, '{"claim_id": "CLM-1001"}')
    assert screening is None
    assert reply.response_metadata["token_usage"]["cost"] == 0.0003


def test_a_flagged_claim_is_referred_without_the_claim_agents_model(client):
    run_id = new_dispatch()["run_id"]
    model = stub(*decide("approve", 4800.0))
    graph = graph_on(model, screener=flags())
    report = harness.work_claim("CLM-1901", run_id, graph)

    assert report == "CLM-1901  refer  $0.00"
    assert model.prompts == []
    decision = claim_of(client, "CLM-1901")["decision"]
    assert (decision["decision"], decision["payout"]) == ("refer", 0)
    assert (decision["reason"], decision["section"]) == (
        FLAGGED,
        harness.SECURITY_CHECK,
    )
    [step] = steps_of(client, "CLM-1901")
    assert (step["kind"], step["content"]) == (
        "screening",
        f"Instructions found. {FLAGGED}",
    )
    [check] = model_calls_of("CLM-1901")
    assert (check["run_id"], check["cost"]) == (run_id, USAGE["cost"])


def test_a_passed_claim_goes_to_the_claim_agent(client):
    screener = passes()
    model = stub(*decide("approve", 420.0))
    report = harness.work_claim("CLM-1001", None, graph_on(model, screener=screener))

    assert report == "CLM-1001  approve  $420.00"
    assert claim_of(client, "CLM-1001")["payment"]["amount"] == 420.0
    check, _, as_the_tool_gives_it, *_ = steps_of(client, "CLM-1001")
    assert (check["kind"], check["content"]) == (
        "screening",
        f"No instructions found. {PASSED}",
    )
    [[system, claim]] = screener.prompts
    assert (system, claim) == (
        SystemMessage(SCREEN_INSTRUCTIONS),
        HumanMessage(as_the_tool_gives_it["content"].removeprefix("get_claim: ")),
    )
    assert len(model.prompts) == 2


def test_an_unreadable_answer_is_asked_again(client):
    screener = stub(UNREADABLE, UNREADABLE, screened(False, PASSED))
    model = stub(*decide("refer", 0))
    report = harness.work_claim("CLM-1003", None, graph_on(model, screener=screener))

    assert report == "CLM-1003  refer  $0.00"
    assert len(screener.prompts) == 3
    assert len(model_calls_of("CLM-1003")) == 3 + 2


def test_three_unreadable_answers_fail_the_attempt(client):
    screener = stub(UNREADABLE, UNREADABLE, UNREADABLE)
    model = stub(*decide("refer", 0))
    report = harness.work_claim("CLM-1003", None, graph_on(model, screener=screener))

    assert report == (
        "CLM-1003  failed: UnreadableScreening: The security check's answer "
        "couldn't be read, back in the queue"
    )
    assert model.prompts == []
    assert len(model_calls_of("CLM-1003")) == 3
    assert claim_of(client, "CLM-1003")["status"] == "waiting"


def test_a_timeout_from_the_check_leaves_the_claim_in_progress(client):
    screener = stub(ModelTimeoutError("Timed out"), screened(False, PASSED))
    model = stub(*decide("refer", 0))
    with pytest.raises(ModelTimeoutError):
        harness.work_claim("CLM-1003", None, graph_on(model, screener=screener))

    assert len(screener.prompts) == 1
    assert model.prompts == []
    assert claim_of(client, "CLM-1003")["status"] == "in_progress"


def test_any_other_error_from_the_check_fails_the_attempt(client):
    screener = stub(RuntimeError("503: The model is unavailable"))
    model = stub(*decide("refer", 0))
    report = harness.work_claim("CLM-1003", None, graph_on(model, screener=screener))

    assert report.endswith("503: The model is unavailable, back in the queue")
    assert len(screener.prompts) == 1
    assert model.prompts == []


def test_the_checks_result_is_kept_in_the_claims_state(client):
    graph = graph_on(stub(), screener=flags())
    harness.work_claim("CLM-1901", None, graph)
    state = graph.get_state(harness.thread_of(claim_of(client, "CLM-1901")))
    assert state.values["screening"] == {
        "reason": FLAGGED,
        "instructions_found": True,
    }
    assert state.values["decision"]["reason"] == state.values["screening"]["reason"]


def test_the_check_runs_once_for_each_thread(client):
    screener, saver = passes(), InMemorySaver()
    timeout = ModelTimeoutError("Timed out")
    model = stub(call("get_claim"), timeout, record("refer", 0))
    with pytest.raises(ModelTimeoutError):
        harness.work_claim("CLM-1003", None, graph_on(model, saver, screener=screener))

    report = harness.carry_on(
        "CLM-1003", None, graph_on(model, saver, screener=screener)
    )
    assert report == "CLM-1003  refer  $0.00"
    assert len(screener.prompts) == 1


def test_a_claim_starting_again_from_its_first_message_is_checked_again(client):
    screener = passes()
    graph = graph_on(stub(ModelTimeoutError("Timed out")), screener=screener)
    with pytest.raises(ModelTimeoutError):
        harness.work_claim("CLM-1003", None, graph)

    # Nothing saved: another process's saver, with none of this one's progress.
    fresh = graph_on(stub(*decide("refer", 0)), InMemorySaver(), screener=screener)
    assert harness.carry_on("CLM-1003", None, fresh) == "CLM-1003  refer  $0.00"
    assert len(screener.prompts) == 2


def test_a_second_attempt_is_checked_again(client):
    screener = passes()
    outage = RuntimeError("503: The model is unavailable")
    harness.work_claim("CLM-1003", None, graph_on(stub(outage), screener=screener))
    graph = graph_on(stub(*decide("refer", 0)), screener=screener)
    assert harness.work_claim("CLM-1003", None, graph) == "CLM-1003  refer  $0.00"
    assert len(screener.prompts) == 2
    kinds = [step["kind"] for step in steps_of(client, "CLM-1003")]
    assert [kinds[0], kinds[1], kinds[2]] == ["screening", "error", "screening"]
