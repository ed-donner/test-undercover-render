"""The success criteria we agreed, checked in code from an evaluation the Copilot
runs, our settings and the app's count of payouts over the limit, and the turn's
whole answer written in code."""

import threading

import pytest
from sqlalchemy import insert, select, update

from agent.copilot import criteria, waiting
from agent.tests.copilot_driver import Copilot, started_run
from agent.tests.memory_stand_in import MemoryStandIn
from agent.tests.stubs import call, stub
from backend.database import engine, handler_decisions, now, payments
from backend.tests.claim_requests import decide, held, sign_off, start
from backend.tests.run_requests import (
    another_running_dispatch,
    fail_run,
    finish,
    run_path,
)
from backend.tests.settings_requests import change_settings

HEADER = "| Criterion | Target | Figure | Met |\n| --- | --- | --- | --- |"
STRAIGHT_THROUGH = "| Straight through | At least 70% | {figure} | {met} |"
ACCURACY = (
    "| Accuracy | At least {objective}, our accuracy objective in Settings | "
    "{figure} | {met} |"
)
OVER_THE_LIMIT = (
    "| Over the limit | Every payout over the approval limit signed off by a handler "
    "| {figure} | {met} |"
)
CHECK = "Are we meeting the success criteria we agreed?"


@pytest.fixture(autouse=True)
def quick_waits(monkeypatch):
    """Read the run every hundredth of a second, for up to ten seconds."""
    monkeypatch.setattr(waiting, "POLL", 0.01)
    monkeypatch.setattr(waiting, "WAIT", 10)


def handlers_decided() -> list[str]:
    """Set our handlers' decisions on the held-out set, in the test's own database,
    so the test knows the measures: the first three claims referred, the rest
    approved at $100.00. Return the claims in that order."""
    with engine().begin() as db:
        held_out = handler_decisions.c.evaluation_set == "held_out"
        query = select(handler_decisions.c.claim_id).where(held_out)
        claims = sorted(db.execute(query).scalars())
        db.execute(
            update(handler_decisions)
            .where(held_out)
            .values(decision="approve", payout=100.0)
        )
        db.execute(
            update(handler_decisions)
            .where(held_out, handler_decisions.c.claim_id.in_(claims[:3]))
            .values(decision="refer", payout=0.0)
        )
    assert len(claims) == 25
    return claims


def work_the_copies(client, run_id: str, claims: list[str]) -> None:
    """Decide the evaluation's copies as the agent would, so that 5 of 25 are
    referred, 80% straight through, and 22 are right, 88% accuracy: the three the
    handlers referred, two more referred, one approved at $200.00 and the rest
    approved at $100.00, then finish the evaluation."""
    for copy in client.get(run_path(run_id)).json()["claims"]:
        copy_id = copy["claim_id"]
        place = claims.index(copy_id.rsplit("-E", 1)[0])
        start(client, copy_id)
        if place < 5:
            decide(client, copy_id, "refer", 0)
        else:
            decide(client, copy_id, "approve", 200.0 if place == 5 else 100.0)
    finish(client, run_id)


def playing_the_evaluation_out(client, agent_calls, end):
    """A thread that waits for the evaluation the Copilot starts and ends it as
    the test says."""
    thread = threading.Thread(target=lambda: end(started_run(agent_calls)))
    thread.start()
    return thread


def check(copilot: Copilot, client, agent_calls, end) -> dict:
    """Ask whether we meet the success criteria, with the evaluation ended as the
    test says, and return the turn."""
    playing = playing_the_evaluation_out(client, agent_calls, end)
    copilot.model = stub(call("check_success_criteria"))
    [turn] = copilot.ask(CHECK)["turns"]
    playing.join(10)
    return turn


def table(straight, accuracy, over, verdict, objective="60%"):
    """The answer the criteria give: the table and the line on whether all three
    are met."""
    rows = [
        STRAIGHT_THROUGH.format(figure=straight[0], met=straight[1]),
        ACCURACY.format(objective=objective, figure=accuracy[0], met=accuracy[1]),
        OVER_THE_LIMIT.format(figure=over[0], met=over[1]),
    ]
    return "\n".join([HEADER, *rows]) + f"\n\n{verdict}"


def test_the_success_criteria(client, copilot: Copilot, agent_calls):
    claims = handlers_decided()
    held(client, "CLM-1002", 1350.0)
    sign_off(client, "CLM-1002")
    turn = check(
        copilot, client, agent_calls, lambda run: work_the_copies(client, run, claims)
    )
    run = client.get(run_path(started_run(agent_calls))).json()
    assert (run["kind"], run["evaluation_set"], run["tiny"], run["agents"]) == (
        "evaluation",
        "held_out",
        False,
        25,
    )
    assert turn["answer"] == table(
        ("80%", "Yes"),
        ("88%", "Yes"),
        ("1 of 1 signed off", "Yes"),
        "All three are met.",
    )
    assert len([c for c in agent_calls if c["operation"] == "work_run"]) == 1


def test_the_answer_is_written_in_code(client, copilot: Copilot, agent_calls):
    claims = handlers_decided()
    copilot.store = MemoryStandIn()
    turn = check(
        copilot, client, agent_calls, lambda run: work_the_copies(client, run, claims)
    )
    criteria = turn["answer"]
    assert criteria == table(
        ("80%", "Yes"),
        ("88%", "Yes"),
        ("None paid over the limit yet", "Yes"),
        "All three are met.",
    )
    assert len(copilot.model.prompts) == 1
    assert (turn["status"], turn["model_calls"]) == ("done", 1)
    [card] = [c for c in turn["steps"] if c["tool"] == "check_success_criteria"]
    assert (card["kind"], card["answer"]) == ("action", criteria)
    message, answer = copilot.store.events
    assert (message.message.text, answer.message.text) == (CHECK, criteria)
    copilot.model = stub("We're doing well.")
    conversation_id = copilot.last_payload()["conversation_id"]
    later = copilot.ask("Thanks", conversation_id)["turns"][-1]
    assert later["answer"] == "We're doing well."


def paid_without_a_sign_off(claim_id, amount):
    """Write a payment straight into the table, as nothing in the app would for a
    payout held for sign-off."""
    with engine().begin() as db:
        db.execute(
            insert(payments).values(claim_id=claim_id, amount=amount, paid_at=now())
        )


def test_the_third_with_none_paid_and_with_one_unsigned(
    client, copilot: Copilot, agent_calls
):
    claims = handlers_decided()
    turn = check(
        copilot, client, agent_calls, lambda run: work_the_copies(client, run, claims)
    )
    assert "| None paid over the limit yet | Yes |" in turn["answer"]
    held(client, "CLM-1002", 1350.0)
    sign_off(client, "CLM-1002")
    held(client, "CLM-1008", 1200.0)
    paid_without_a_sign_off("CLM-1008", 1200.0)
    agent_calls.clear()
    turn = check(
        copilot, client, agent_calls, lambda run: work_the_copies(client, run, claims)
    )
    assert turn["answer"] == table(
        ("80%", "Yes"),
        ("88%", "Yes"),
        ("1 of 2 signed off", "No"),
        "Two of the three are met.",
    )


def test_an_evaluation_that_stops_gives_no_figures_for_the_first_two(
    client, copilot: Copilot, agent_calls
):
    turn = check(
        copilot,
        client,
        agent_calls,
        lambda run: fail_run(client, run, "RuntimeError: The dispatcher broke"),
    )
    why = "The evaluation stopped: RuntimeError: The dispatcher broke"
    assert turn["answer"] == table(
        (why, "Not known"),
        (why, "Not known"),
        ("None paid over the limit yet", "Yes"),
        "Only the third can be judged without the evaluation's figures, and it is met.",
    )


def test_an_evaluation_still_going_gives_no_figures_for_the_first_two(
    client, copilot: Copilot, agent_calls, monkeypatch
):
    monkeypatch.setattr(waiting, "WAIT", 0.05)
    turn = check(copilot, client, agent_calls, lambda run: None)
    why = "Still going after 0 minutes. Follow it on the Scoreboard."
    assert f"| {why} | Not known |" in turn["answer"]
    assert "| None paid over the limit yet | Yes |" in turn["answer"]


def test_a_start_the_app_refuses_gives_its_reason(client, copilot: Copilot):
    another_running_dispatch()
    held(client, "CLM-1008", 1200.0)
    paid_without_a_sign_off("CLM-1008", 1200.0)
    copilot.model = stub(call("check_success_criteria"))
    [turn] = copilot.ask(CHECK)["turns"]
    why = "The evaluation couldn't start: A dispatch is running"
    assert turn["answer"] == table(
        (why, "Not known"),
        (why, "Not known"),
        ("0 of 1 signed off", "No"),
        "Only the third can be judged without the evaluation's figures, and it "
        "isn't met.",
    )


def test_the_accuracy_objective_comes_from_the_settings(
    client, dashboard, copilot: Copilot, agent_calls
):
    claims = handlers_decided()
    objectives = {"accuracy": 0.9, "grade": 1.0}
    assert change_settings(dashboard, objectives=objectives).status_code == 200
    turn = check(
        copilot, client, agent_calls, lambda run: work_the_copies(client, run, claims)
    )
    assert turn["answer"] == table(
        ("80%", "Yes"),
        ("88%", "No"),
        ("None paid over the limit yet", "Yes"),
        "Two of the three are met.",
        objective="90%",
    )


def test_the_objective_shows_as_settings_shows_it():
    none_paid = {"paid_over_the_limit": 0, "signed_off": 0}
    [_, accuracy, _] = criteria.rows(criteria.Figures(0.8, 0.70), 0.705, none_paid)
    assert (accuracy.target, accuracy.figure, accuracy.met) == (
        "At least 70.5%, our accuracy objective in Settings",
        "70%",
        False,
    )
