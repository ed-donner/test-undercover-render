"""Rounds of the improver through the agent's AgentCore app, on a stub improver that
follows a script and stub claim agents, with the backend as it is."""

from collections.abc import Callable
from typing import Any

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import func, select

from agent import entrypoint, work
from agent.improver import improver_model
from agent.tests.dispatching import new_dispatch, the_app
from agent.tests.invoking import ACCEPTED, HEALTH, carry_round_on, work_round
from agent.tests.rounds import (
    RULE,
    VERSION_1,
    RuleFollowingModel,
    claim_agents_model,
    improver,
    propose,
    whole_round,
)
from agent.tests.stubs import StubModel, call
from backend.database import engine, grades, improver_calls, model_calls, runs
from backend.tests.dashboard_reads import configuration, version_details
from backend.tests.round_requests import create_round, improvement, stop_round
from backend.tests.round_requests import review as review_as_a_handler
from backend.tests.run_requests import get_evaluation
from backend.tests.settings_requests import STARTING, change_settings

# Room for a round's evaluations: a spending limit above what the stub claim agents
# cost, and noise and a tolerance on time so wide that a test's timing, which is
# real, never counts for or against a version.
UNTIMED = {"seconds_per_claim": 1000}
ROOM: dict[str, Any] = {
    "spending_limit": 5.0,
    "noise": STARTING["noise"] | UNTIMED,
    "tolerance": STARTING["tolerance"] | UNTIMED,
}
# Fewer claim agents at once than the agent's most, to show that a round uses its
# own setting.
AGENTS = 5


@pytest.fixture(autouse=True)
def room_to_run(client):
    change_settings(client, agents=AGENTS, **ROOM)


def start_round(agent, wait=True):
    """Start a round as a handler does, which the app creates, and have the agent
    work it."""
    with the_app() as caller:
        round_id = create_round(caller).json()["round_id"]
    return agent.invoke(work_round(round_id), wait=wait)


def review(agent, round_, proposal_id, verdict="approved"):
    """Review a proposal as a handler does, which the app records, and have the
    agent carry the round on."""
    round_id = round_["round_id"]
    with the_app() as caller:
        reviewed = review_as_a_handler(caller, round_id, proposal_id, verdict)
    assert reviewed.status_code == 200, reviewed.text
    return agent.invoke(carry_round_on(round_id, proposal_id))


def the_round(client):
    return improvement(client)["round"]


def total(table, column, where):
    with engine().connect() as db:
        query = select(func.coalesce(func.sum(column), 0)).where(where)
        return db.execute(query).scalar_one()


def test_a_round_runs_its_first_evaluations_then_waits_for_a_change(
    client, serve_rounds
):
    model = whole_round()
    agent = serve_rounds(model, claim_agents_model())
    assert start_round(agent).json() == ACCEPTED

    round_ = the_round(client)
    assert (round_["number"], round_["status"], round_["stage"]) == (
        1,
        "open",
        "change_waiting",
    )
    evaluations = [(e["evaluation_set"], e["status"]) for e in round_["evaluations"]]
    assert evaluations == [
        ("evaluation", "finished"),
        ("held_out", "finished"),
        ("held_out", "finished"),
    ]
    waiting = round_["waiting"]
    assert waiting["kind"] == "change"
    assert waiting["diff"]["added"] == 2
    assert len(model.prompts) == 2
    read = model.prompts[1][-1]
    assert read.name == "read_results"
    assert '"wrong"' in read.content
    # The round waits for a handler, so a dispatch can start.
    assert new_dispatch()["status"] == "running"


def test_a_whole_round_with_a_rejection(client, serve_rounds):
    model = whole_round()
    agent = serve_rounds(model, claim_agents_model())
    start_round(agent)
    round_ = the_round(client)

    rejected = review(agent, round_, round_["waiting"]["proposal_id"], "rejected")
    assert rejected.json() == ACCEPTED
    answer = model.prompts[2][-1]
    assert answer.name == "propose_change"
    assert "Keep each rule general" in answer.content
    assert configuration(client)["current"] == 1

    second = the_round(client)["waiting"]
    assert second["proposal_id"] != round_["waiting"]["proposal_id"]
    review(agent, round_, second["proposal_id"])
    after = the_round(client)
    assert (after["version"], after["verdict"]) == (2, "kept")
    assert after["verdict_reason"] == "accuracy improved"
    assert client.get("/api/versions/current").json()["number"] == 2
    tested = [e for e in after["evaluations"] if e["version"] == 2]
    assert [(e["evaluation_set"], e["agents"]) for e in tested] == [
        ("evaluation", AGENTS),
        ("held_out", AGENTS),
        ("held_out", AGENTS),
    ]
    assert after["waiting"]["kind"] == "recipe"

    review(agent, round_, after["waiting"]["proposal_id"])
    page = improvement(client)
    finished = page["round"]
    assert finished["status"] == "finished"
    assert [r["number"] for r in page["recipes"] if r["current"]] == [2]
    assert [(r["kind"], r["review"]) for r in finished["reviews"]] == [
        ("change", "rejected"),
        ("change", "approved"),
        ("recipe", "approved"),
    ]
    round_id = round_["round_id"]
    in_round = select(runs.c.run_id).where(runs.c.round_id == round_id)
    cost = (
        total(
            improver_calls, improver_calls.c.cost, improver_calls.c.round_id == round_id
        )
        + total(model_calls, model_calls.c.cost, model_calls.c.run_id.in_(in_round))
        + total(grades, grades.c.cost, grades.c.run_id.in_(in_round))
    )
    assert finished["cost"] == pytest.approx(cost)
    assert total(improver_calls, improver_calls.c.cost, True) == pytest.approx(
        6 * 0.0042
    )


def test_a_model_outside_the_models_allowed_goes_back_to_the_improver(
    client, serve_rounds
):
    model = improver(
        call("read_results"),
        propose(model="openai/gpt-7", reasoning_effort="high"),
        propose(),
    )
    agent = serve_rounds(model, claim_agents_model())
    start_round(agent)
    answer = model.prompts[2][-1]
    assert answer.content == (
        "openai/gpt-7 at high isn't allowed. Choose from the models allowed."
    )
    round_ = the_round(client)
    assert round_["stage"] == "change_waiting"
    assert round_["waiting"]["model_after"] == "openai/gpt-6-luna"
    assert [r["kind"] for r in round_["reviews"]] == []


def test_a_round_whose_improver_proposes_nothing_finishes(client, serve_rounds):
    agent = serve_rounds(
        improver(call("read_results"), "No change would help."),
        claim_agents_model(),
    )
    start_round(agent)
    round_ = the_round(client)
    assert (round_["status"], round_["version"]) == ("finished", None)


def test_the_improver_is_built_from_the_rounds_model(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.delenv("MODEL_NAME", raising=False)
    model = improver_model(
        {"improver_model": "openai/gpt-6-luna", "improver_reasoning_effort": "medium"}
    )
    assert (model.model_name, model.reasoning_effort) == ("openai/gpt-6-luna", "medium")
    assert (model.request_timeout, model.max_retries) == (300, 5)


def test_the_rounds_work_is_traced_in_its_own_session(client, serve_rounds, traces):
    agent = serve_rounds(whole_round(), claim_agents_model())
    start_round(agent)
    round_ = the_round(client)
    session = f"Round 1:{round_['round_id']}"
    improver_traces = [t for t in traces if t.get("langfuse_trace_name") == "Improver"]
    assert [t["langfuse_session_id"] for t in improver_traces] == [session]
    claims = [t for t in traces if t.get("langfuse_trace_name") == "Work claim"]
    assert len(claims) == 75
    run_ids = {e["run_id"] for e in round_["evaluations"]}
    for trace in claims:
        run_id, round_id = trace["langfuse_tags"]
        assert (run_id in run_ids, round_id) == (True, round_["round_id"])
    assert RULE not in VERSION_1


def restart(monkeypatch, fresh_agent):
    """Get the agent ready again, as after a restart."""
    monkeypatch.setattr(entrypoint, "ready", entrypoint.Ready())
    fresh_agent().invoke(HEALTH)


def test_a_round_waiting_for_a_handler_survives_a_restart(
    client, serve_rounds, monkeypatch, fresh_agent
):
    model = whole_round()
    agent = serve_rounds(model, claim_agents_model())
    start_round(agent)
    restart(monkeypatch, fresh_agent)
    round_ = the_round(client)
    assert (round_["status"], round_["stage"]) == ("open", "change_waiting")

    review(agent, round_, round_["waiting"]["proposal_id"], "rejected")
    assert "Keep each rule general" in model.prompts[2][-1].content
    assert the_round(client)["stage"] == "change_waiting"


def test_a_round_in_its_first_evaluations_is_left_open_by_a_restart(
    client, workers_from, monkeypatch, fresh_agent
):
    stubs = StubModel(messages=iter(()))
    workers_from(stubs, InMemorySaver(), stubs)
    create_round(client)
    restart(monkeypatch, fresh_agent)
    assert the_round(client)["status"] == "open"


class StoppingModel(RuleFollowingModel):
    """Stub claim agents that stop the round as they work the version under test."""

    stop: Callable[[], None] = lambda: None

    def next_reply(self, messages):
        if RULE.strip() in messages[0].content:
            self.stop()
        return super().next_reply(messages)


def test_stopping_a_round_during_its_evaluations(client, serve_rounds):
    change_settings(client, agents=1, **ROOM)
    model = improver(
        call("read_results"), propose(), call("run_evaluation"), "Never reached"
    )
    claims = claim_agents_model()
    stopping = StoppingModel(messages=iter(()), answers=claims.answers)
    agent = serve_rounds(model, stopping)
    start_round(agent)
    round_ = the_round(client)
    stopping.stop = lambda: stop_round(client, round_["round_id"])
    review(agent, round_, round_["waiting"]["proposal_id"])

    stopped = the_round(client)
    assert (stopped["status"], stopped["stopped_by"]) == ("stopped", "Dana Whitfield")
    [tested] = [e for e in stopped["evaluations"] if e["version"] == 2]
    assert tested["status"] == "stopped"
    # The claim in hand when the round stopped finished; no other started.
    copies = get_evaluation(client, tested["run_id"])["claims"]
    statuses = [copy["status"] for copy in copies]
    assert (statuses.count("decided"), statuses.count("waiting")) == (1, 24)
    assert len(model.prompts) == 3
    assert total(improver_calls, improver_calls.c.cost, True) == pytest.approx(
        3 * 0.0042
    )
    assert version_details(client, 2)["status"] == ("rolled_back")
    assert new_dispatch()["status"] == "running"


def test_the_improver_stops_after_20_model_calls_in_a_round(client, serve_rounds):
    model = improver(
        *[call("read_results") for _ in range(18)],
        propose(),
        call("read_results"),
        call("read_results"),
    )
    agent = serve_rounds(model, claim_agents_model())
    start_round(agent)
    round_ = the_round(client)
    review(agent, round_, round_["waiting"]["proposal_id"])

    stopped = the_round(client)
    assert stopped["status"] == "stopped"
    assert "Model call limits exceeded" in stopped["stopped_because"]
    assert len(model.prompts) == 20


def test_the_spending_limit_cuts_a_round_short_in_its_first_evaluations(
    client, serve_rounds
):
    change_settings(client, spending_limit=0.01, agents=1)
    model = whole_round()
    agent = serve_rounds(model, claim_agents_model())
    start_round(agent)

    round_ = the_round(client)
    assert (round_["status"], round_["stopped_because"]) == (
        "stopped",
        "The spending limit cut short its first evaluations",
    )
    assert [e["status"] for e in round_["evaluations"]] == ["stopped"]
    assert model.prompts == []
    assert new_dispatch()["status"] == "running"


def test_a_proposal_the_backend_refuses_goes_back_to_the_improver(client, serve_rounds):
    model = improver(
        call("read_results"),
        propose(),
        call("run_evaluation"),
        propose(VERSION_1 + "\nAnother rule.\n"),
        call("propose_recipe", recipe="1. Read the results.\n", reason="Shorter"),
    )
    agent = serve_rounds(model, claim_agents_model())
    start_round(agent)
    round_ = the_round(client)
    review(agent, round_, round_["waiting"]["proposal_id"])

    answer = model.prompts[4][-1]
    assert answer.name == "propose_change"
    assert "Refused: Round 1 has already tried version 2" in answer.content
    after = the_round(client)
    assert (after["status"], after["stage"]) == ("open", "recipe_waiting")


def test_a_version_is_evaluated_only_until_its_verdict(client, serve_rounds):
    model = improver(
        call("read_results"),
        propose(),
        call("run_evaluation"),
        call("run_evaluation"),
        "The round is done.",
    )
    agent = serve_rounds(model, claim_agents_model())
    start_round(agent)
    round_ = the_round(client)
    review(agent, round_, round_["waiting"]["proposal_id"])

    assert model.prompts[4][-1].content == (
        "Refused: Round 1 has no version under test"
    )
    finished = the_round(client)
    assert finished["status"] == "finished"
    assert len(finished["evaluations"]) == 6


class StoppedMidCall(StubModel):
    """A stub improver whose second reply comes after a handler stops the round."""

    stop: Callable[[], None] = lambda: None

    def next_reply(self, messages):
        if self.prompts[1:]:
            self.stop()
        return super().next_reply(messages)


def test_a_round_stopped_during_a_model_call_ends_quietly(client, serve_rounds, caplog):
    model = StoppedMidCall(messages=iter([call("read_results"), propose()]))
    agent = serve_rounds(model, claim_agents_model())
    model.stop = lambda: stop_round(client, the_round(client)["round_id"])
    start_round(agent)

    stopped = the_round(client)
    assert (stopped["status"], stopped["stopped_by"]) == ("stopped", "Dana Whitfield")
    assert stopped["waiting"] is None
    assert len(model.prompts) == 2
    assert total(improver_calls, improver_calls.c.cost, True) == pytest.approx(0.0042)
    assert "The round stopped" not in caplog.text


def test_the_improver_asks_for_one_tool_call_at_a_time(client, serve_rounds):
    model = improver(call("read_results"), "No change would help.")
    start_round(serve_rounds(model, claim_agents_model()))
    assert model.bound_with
    assert all(bound["parallel_tool_calls"] is False for bound in model.bound_with)


def test_a_round_whose_evaluation_fails_is_stopped_with_its_run(
    client, serve_rounds, monkeypatch
):
    def broken(run, claim_agents):
        raise RuntimeError("The claim agents couldn't be built")

    monkeypatch.setattr(work, "claim_work", broken)
    model = whole_round()
    agent = serve_rounds(model, claim_agents_model())
    start_round(agent)

    round_ = the_round(client)
    because = "RuntimeError: The claim agents couldn't be built"
    assert (round_["status"], round_["stopped_because"]) == ("stopped", because)
    [evaluation] = round_["evaluations"]
    assert (evaluation["status"], evaluation["stopped_because"]) == (
        "stopped",
        because,
    )
    assert model.prompts == []
    assert new_dispatch()["status"] == "running"
