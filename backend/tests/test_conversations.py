"""The Copilot's conversations in the app: each handler's own, one message at a
time, the Copilot's records of each turn, a turn that stops, the confirmation card
filled in from the claim, and the handler's answer to it."""

import json
import logging
import re
import threading
import time
from datetime import timedelta

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import select

from backend.conversations import (
    ANSWER_FIRST,
    CLAIM_CHANGED,
    NO_SUCH_CONFIRMATION,
    STILL_WORKING,
    add_after,
    owned,
)
from backend.database import (
    conversations,
    copilot_steps,
    copilot_turns,
    engine,
    payments,
    seed,
)
from backend.dependencies import API_KEY_HEADER
from backend.models import Handler
from backend.tests.claim_requests import (
    held,
    record_decision,
    send_back,
    sign_off,
    take,
)
from backend.tests.copilot_requests import (
    CONVERSATIONS,
    QUESTION,
    answer,
    conversation_of,
    fail_turn,
    finish_step,
    finish_turn,
    latest,
    list_conversations,
    pause_turn,
    send_message,
    start_conversation,
    start_step,
    started,
    times_ago,
)
from backend.tests.dashboard_reads import read
from backend.tests.rows import calculated, count, everything_recorded
from backend.tests.run_requests import create_evaluation
from backend.tests.sign_in import DANA, MARCUS, bearer, signed_in, token

CONVERSATION_ID = (
    r"conversation-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)
TWENTY_ONE_MINUTES = timedelta(minutes=21)


def turn_of(client, conversation_id, number=-1):
    return conversation_of(client, conversation_id).json()["turns"][number]


def done(client, conversation):
    """Finish a conversation's latest turn, as the Copilot does."""
    finish_turn(client, latest(conversation)["turn_id"])


def waiting_on(client, claim_id="CLM-1003", payout=3750.0):
    """A conversation whose turn waits for Dana to confirm a sign-off of a held
    payout, and the turn's id."""
    held(client, claim_id, payout)
    conversation = started(client, f"Sign off {claim_id}")
    turn_id = latest(conversation)["turn_id"]
    assert pause_turn(client, turn_id, claim_id).status_code == 200
    return conversation["conversation_id"], turn_id


def test_a_conversation_starts_with_one_working_turn(dashboard, copilot_calls):
    response = start_conversation(dashboard)
    assert response.status_code == 202
    conversation = response.json()
    assert re.fullmatch(CONVERSATION_ID, conversation["conversation_id"])
    assert conversation["title"] == QUESTION
    [turn] = conversation["turns"]
    assert (turn["number"], turn["message"], turn["status"]) == (1, QUESTION, "working")
    assert turn["steps"] == []
    assert copilot_calls == [
        {
            "operation": "take_turn",
            "conversation_id": conversation["conversation_id"],
            "turn_id": turn["turn_id"],
            "sign_in": copilot_calls[0]["sign_in"],
        }
    ]


def test_a_long_first_message_is_cut_to_120_characters_for_the_title(dashboard):
    message = "Tell me about the queue. " * 10
    conversation = started(dashboard, message)
    assert conversation["title"] == message.strip()[:120]
    assert latest(conversation)["message"] == message.strip()


def test_a_message_waits_for_the_turn_before_it(dashboard, copilot_calls):
    conversation = started(dashboard)
    conversation_id = conversation["conversation_id"]
    refused = send_message(dashboard, conversation_id)
    assert (refused.status_code, refused.json()["detail"]) == (409, STILL_WORKING)
    done(dashboard, conversation)
    sent = send_message(dashboard, conversation_id)
    assert sent.status_code == 202
    second = latest(sent.json())
    assert (second["number"], second["status"]) == (2, "working")
    assert copilot_calls[-1]["turn_id"] == second["turn_id"]
    assert fail_turn(dashboard, second["turn_id"]).status_code == 200
    third = send_message(dashboard, conversation_id)
    assert third.status_code == 202
    times_ago(latest(third.json())["turn_id"], started_at=TWENTY_ONE_MINUTES)
    assert send_message(dashboard, conversation_id).status_code == 202
    assert [
        t["status"] for t in conversation_of(dashboard, conversation_id).json()["turns"]
    ] == [
        "done",
        "failed",
        "stopped",
        "working",
    ]


def test_no_message_while_a_confirmation_waits(client, dashboard):
    conversation_id, _ = waiting_on(client)
    refused = send_message(dashboard, conversation_id)
    assert (refused.status_code, refused.json()["detail"]) == (409, ANSWER_FIRST)


@pytest.mark.parametrize("message", ["", "   ", "x" * 4001])
def test_a_blank_or_long_message_is_refused(dashboard, copilot_calls, message):
    assert start_conversation(dashboard, message).status_code == 422
    conversation = started(dashboard)
    done(dashboard, conversation)
    assert (
        send_message(dashboard, conversation["conversation_id"], message).status_code
        == 422
    )
    assert len(copilot_calls) == 1


def test_a_message_of_4000_characters_is_fine(dashboard):
    assert start_conversation(dashboard, "x" * 4000).status_code == 202


def test_two_messages_at_the_same_moment_make_one_turn(dashboard):
    conversation = started(dashboard)
    conversation_id = conversation["conversation_id"]
    done(dashboard, conversation)
    together = threading.Barrier(2)
    answers = []

    def send():
        together.wait()
        answers.append(send_message(dashboard, conversation_id).status_code)

    sending = [threading.Thread(target=send) for _ in range(2)]
    for thread in sending:
        thread.start()
    for thread in sending:
        thread.join(10)
    assert sorted(answers) == [202, 409]
    assert len(conversation_of(dashboard, conversation_id).json()["turns"]) == 2


def test_a_message_read_before_another_moved_the_conversation_on_is_refused(
    dashboard,
):
    """The conditional update alone, with the conversation as a second message read
    it before the first one moved it on."""
    conversation = started(dashboard)
    conversation_id = conversation["conversation_id"]
    done(dashboard, conversation)
    dana = Handler(**read(dashboard, "/api/me").json())
    with engine().connect() as db:
        as_read = owned(db, conversation_id, dana)
    second = latest(send_message(dashboard, conversation_id).json())
    finish_turn(dashboard, second["turn_id"])
    with engine().connect() as db, pytest.raises(HTTPException) as refused:
        add_after(db, as_read, "A third message")
    assert (refused.value.status_code, refused.value.detail) == (409, STILL_WORKING)


def test_the_copilot_records_its_cards_and_the_turns_answer(dashboard):
    conversation = started(dashboard)
    turn_id = latest(conversation)["turn_id"]
    card = start_step(dashboard, turn_id).json()
    assert (card["tool"], card["kind"], card["input"], card["status"]) == (
        "get_claim",
        "claims",
        "CLM-1012",
        "working",
    )
    time.sleep(0.05)
    [later] = turn_of(dashboard, conversation["conversation_id"])["steps"]
    assert later["seconds"] > card["seconds"]
    source = {
        "file": "policy_wording.md",
        "system": "Policy admin",
        "owner": "Head of product",
        "reviewed": "2026-09-01",
    }
    finished = finish_step(
        dashboard,
        turn_id,
        card["step_id"],
        answer='{"claim_id": "CLM-1012"}',
        sources=[source],
    ).json()
    assert (finished["status"], finished["answer"], finished["sources"]) == (
        "done",
        '{"claim_id": "CLM-1012"}',
        [source],
    )
    refused = start_step(dashboard, turn_id, "start_dispatch", "10").json()
    finish_step(
        dashboard,
        turn_id,
        refused["step_id"],
        "refused",
        answer=None,
        reason="A dispatch is running",
    )
    failed = start_step(dashboard, turn_id, "read_section").json()
    finish_step(
        dashboard, turn_id, failed["step_id"], "failed", answer=None, reason="It broke"
    )
    again = finish_step(dashboard, turn_id, card["step_id"])
    assert again.status_code == 409
    answered = finish_turn(dashboard, turn_id).json()
    assert (
        answered["status"],
        answered["answer"],
        answered["model_calls"],
        answered["cost"],
    ) == (
        "done",
        "Nothing needs you today.",
        4,
        0.0021,
    )
    assert answered["seconds"] >= 0.05
    assert [(s["status"], s["reason"]) for s in answered["steps"]] == [
        ("done", None),
        ("refused", "A dispatch is running"),
        ("failed", "It broke"),
    ]


def test_a_failed_turn_says_why(dashboard):
    conversation = started(dashboard)
    failed = fail_turn(dashboard, latest(conversation)["turn_id"]).json()
    assert (failed["status"], failed["failure"]) == ("failed", "RuntimeError: It broke")
    assert failed["finished_at"] is not None


def test_a_turn_that_isnt_working_or_isnt_the_latest_takes_no_records(dashboard):
    conversation = started(dashboard)
    conversation_id = conversation["conversation_id"]
    first = latest(conversation)["turn_id"]
    done(dashboard, conversation)
    for record in (
        start_step(dashboard, first),
        finish_turn(dashboard, first),
        fail_turn(dashboard, first),
        pause_turn(dashboard, first),
    ):
        assert record.status_code == 409
    send_message(dashboard, conversation_id)
    assert finish_turn(dashboard, first).status_code == 409


def late_records(client, turn_id, step_id):
    return [
        start_step(client, turn_id),
        finish_step(client, turn_id, step_id),
        pause_turn(client, turn_id),
        finish_turn(client, turn_id),
        fail_turn(client, turn_id),
    ]


def test_a_stopped_turn_stays_stopped(client, dashboard):
    held(client, "CLM-1003", 3750.0)
    conversation = started(dashboard)
    turn_id = latest(conversation)["turn_id"]
    step_id = start_step(dashboard, turn_id).json()["step_id"]
    times_ago(turn_id, started_at=TWENTY_ONE_MINUTES)
    assert turn_of(dashboard, conversation["conversation_id"])["status"] == "stopped"
    for late in late_records(dashboard, turn_id, step_id):
        assert late.status_code == 409
    stopped = turn_of(dashboard, conversation["conversation_id"])
    assert stopped["status"] == "stopped"
    assert stopped["steps"][0]["status"] == "working"


def test_a_late_record_of_a_stopped_turn_leaves_the_newer_turn_alone(dashboard):
    conversation = started(dashboard)
    conversation_id = conversation["conversation_id"]
    old = latest(conversation)["turn_id"]
    step_id = start_step(dashboard, old).json()["step_id"]
    times_ago(old, started_at=TWENTY_ONE_MINUTES)
    newer = latest(send_message(dashboard, conversation_id).json())["turn_id"]
    start_step(dashboard, newer, "list_claims", "")
    before = conversation_of(dashboard, conversation_id).json()
    for late in late_records(dashboard, old, step_id):
        assert late.status_code == 409
    after = conversation_of(dashboard, conversation_id).json()
    assert [t["status"] for t in after["turns"]] == ["stopped", "working"]
    assert [s["tool"] for s in after["turns"][1]["steps"]] == ["list_claims"]
    assert after["turns"][1]["status"] == before["turns"][1]["status"]


def test_a_pause_fills_the_card_in_from_the_claim(client, dashboard):
    claim = held(client, "CLM-1003", 3750.0)
    conversation = started(dashboard, "Sign off CLM-1003")
    turn_id = latest(conversation)["turn_id"]
    paused = pause_turn(dashboard, turn_id).json()
    assert paused["status"] == "waiting_for_confirmation"
    assert paused["confirmation"] == {
        "claim_id": "CLM-1003",
        "customer_name": claim["customer_name"],
        "payout": 3750.0,
        "reason": claim["decision"]["reason"],
    }
    with engine().connect() as db:
        query = select(copilot_turns.c.confirmation).where(
            copilot_turns.c.turn_id == turn_id
        )
        kept = db.execute(query).scalar_one()
    assert kept["decided_at"] == claim["decision"]["decided_at"]


def test_a_pause_on_a_claim_not_waiting_for_sign_off_or_a_copy_is_refused(
    client, dashboard
):
    conversation = started(dashboard)
    turn_id = latest(conversation)["turn_id"]
    refused = pause_turn(dashboard, turn_id, "CLM-1001")
    assert (refused.status_code, refused.json()["detail"]) == (
        409,
        "Claim CLM-1001 is not waiting for sign-off",
    )
    copy = create_evaluation(client).json()["claims"][0]["claim_id"]
    held(client, copy, 1500.0)
    refused = pause_turn(dashboard, turn_id, copy)
    assert (refused.status_code, refused.json()["detail"]) == (
        409,
        f"Claim {copy} is a copy in an evaluation and can't be signed off",
    )
    assert turn_of(dashboard, conversation["conversation_id"])["status"] == "working"


def test_the_handlers_answer_carries_the_turn_on(client, dashboard, copilot_calls):
    conversation_id, turn_id = waiting_on(client)
    own = token(DANA)
    response = answer(dashboard, conversation_id, turn_id, "sign_off", bearer(own))
    assert response.status_code == 202
    turn = latest(response.json())
    assert (turn["status"], turn["confirmation_answer"], turn["canceled_because"]) == (
        "working",
        "sign_off",
        None,
    )
    assert turn["answered_at"] is not None
    assert copilot_calls[-1] == {
        "operation": "answer_confirmation",
        "conversation_id": conversation_id,
        "turn_id": turn_id,
        "sign_in": own,
    }
    again = answer(dashboard, conversation_id, turn_id, "cancel")
    assert again.status_code == 409


def test_a_cancel_is_recorded_the_same_way(client, dashboard):
    conversation_id, turn_id = waiting_on(client)
    turn = latest(answer(dashboard, conversation_id, turn_id, "cancel").json())
    assert (turn["status"], turn["confirmation_answer"]) == ("working", "cancel")


def test_an_answer_the_copilot_didnt_take_waits_again(
    client, dashboard, copilot_answers
):
    conversation_id, turn_id = waiting_on(client)
    copilot_answers(lambda request: httpx.Response(200, json={"refused": "Busy"}))
    refused = answer(dashboard, conversation_id, turn_id)
    assert (refused.status_code, refused.json()["detail"]) == (409, "Busy")
    turn = turn_of(dashboard, conversation_id)
    assert (turn["status"], turn["confirmation_answer"], turn["answered_at"]) == (
        "waiting_for_confirmation",
        None,
        None,
    )


def test_an_answer_with_nothing_waiting_is_refused(dashboard, copilot_calls):
    conversation = started(dashboard)
    turn_id = latest(conversation)["turn_id"]
    refused = answer(dashboard, conversation["conversation_id"], turn_id)
    assert refused.status_code == 409
    assert [c["operation"] for c in copilot_calls] == ["take_turn"]


def test_a_stale_tab_cant_answer_a_newer_card(client, dashboard, copilot_calls):
    conversation_id, first = waiting_on(client)
    answer(dashboard, conversation_id, first, "cancel")
    finish_turn(dashboard, first)
    held(client, "CLM-1008", 2240.0)
    newer = latest(send_message(dashboard, conversation_id, "Sign off CLM-1008").json())
    pause_turn(dashboard, newer["turn_id"], "CLM-1008")
    calls = len(copilot_calls)
    refused = answer(dashboard, conversation_id, first, "sign_off")
    assert (refused.status_code, refused.json()["detail"]) == (
        409,
        NO_SUCH_CONFIRMATION,
    )
    assert len(copilot_calls) == calls
    assert count(payments) == 0
    assert turn_of(dashboard, conversation_id)["status"] == "waiting_for_confirmation"


def test_an_answer_to_a_card_already_canceled_is_refused(
    client, dashboard, copilot_calls
):
    conversation_id, turn_id = waiting_on(client)
    answer(dashboard, conversation_id, turn_id, "cancel")
    calls = len(copilot_calls)
    assert answer(dashboard, conversation_id, turn_id, "sign_off").status_code == 409
    assert len(copilot_calls) == calls
    assert count(payments) == 0


def changed_by_a_send_back(client, claim_id="CLM-1003"):
    """Send a held claim back and decide it again with the same payout and another
    reason, as the agent does."""
    send_back(client, claim_id)
    take(client, claim_id)
    calculated(claim_id, 3750.0)
    record_decision(
        client,
        claim_id,
        decision="approve",
        payout=3750.0,
        reason="The hospital bill is covered, less what the airline paid.",
    )


def signed_off_elsewhere(client, claim_id="CLM-1003"):
    sign_off(client, claim_id)


@pytest.mark.parametrize("change", [changed_by_a_send_back, signed_off_elsewhere])
def test_a_sign_off_for_a_claim_that_changed_is_taken_as_a_cancel(
    client, dashboard, copilot_calls, change
):
    conversation_id, turn_id = waiting_on(client)
    change(client)
    paid = count(payments)
    response = answer(dashboard, conversation_id, turn_id, "sign_off")
    assert response.status_code == 202
    turn = latest(response.json())
    assert (turn["confirmation_answer"], turn["canceled_because"]) == (
        "cancel",
        CLAIM_CHANGED,
    )
    assert copilot_calls[-1]["operation"] == "answer_confirmation"
    assert count(payments) == paid
    finish_turn(dashboard, turn_id)
    assert send_message(dashboard, conversation_id).status_code == 202


@pytest.mark.parametrize("change", [changed_by_a_send_back, signed_off_elsewhere])
def test_a_cancel_for_a_claim_that_changed_is_taken(client, dashboard, change):
    conversation_id, turn_id = waiting_on(client)
    change(client)
    turn = latest(answer(dashboard, conversation_id, turn_id, "cancel").json())
    assert (turn["confirmation_answer"], turn["canceled_because"]) == ("cancel", None)


def test_a_turn_stops_20_minutes_after_its_start_or_its_answer(client, dashboard):
    conversation = started(dashboard)
    turn_id = latest(conversation)["turn_id"]
    times_ago(turn_id, started_at=timedelta(minutes=19))
    assert turn_of(dashboard, conversation["conversation_id"])["status"] == "working"
    times_ago(turn_id, started_at=TWENTY_ONE_MINUTES)
    assert turn_of(dashboard, conversation["conversation_id"])["status"] == "stopped"
    conversation_id, waiting = waiting_on(client, "CLM-1008", 2240.0)
    times_ago(waiting, started_at=timedelta(hours=5), paused_at=timedelta(hours=5))
    assert turn_of(dashboard, conversation_id)["status"] == "waiting_for_confirmation"
    answer(dashboard, conversation_id, waiting, "cancel")
    times_ago(waiting, answered_at=timedelta(minutes=19))
    assert turn_of(dashboard, conversation_id)["status"] == "working"
    times_ago(waiting, answered_at=TWENTY_ONE_MINUTES)
    assert turn_of(dashboard, conversation_id)["status"] == "stopped"


def test_a_turns_seconds_leave_out_the_wait_for_the_handler(client, dashboard):
    conversation_id, turn_id = waiting_on(client)
    answer(dashboard, conversation_id, turn_id, "cancel")
    times_ago(
        turn_id,
        started_at=timedelta(minutes=10, seconds=12),
        paused_at=timedelta(minutes=10, seconds=8),
        answered_at=timedelta(seconds=8),
    )
    seconds = finish_turn(dashboard, turn_id).json()["seconds"]
    assert 11.5 < seconds < 13


def test_another_handler_cant_see_or_carry_on_a_conversation(client, dashboard):
    conversation_id, turn_id = waiting_on(client)
    marcus = [
        conversation_of(dashboard, conversation_id, MARCUS),
        send_message(dashboard, conversation_id, email=MARCUS),
        answer(dashboard, conversation_id, turn_id, headers=signed_in(MARCUS)),
        start_step(dashboard, turn_id, email=MARCUS),
        finish_step(dashboard, turn_id, 1, email=MARCUS),
        finish_turn(dashboard, turn_id, email=MARCUS),
        pause_turn(dashboard, turn_id, email=MARCUS),
        fail_turn(dashboard, turn_id, email=MARCUS),
    ]
    assert [response.status_code for response in marcus] == [404] * len(marcus)


def test_each_handler_lists_their_own_conversations_newest_first(dashboard):
    first = started(dashboard, "What needs me today?")
    second = started(dashboard, "How did the latest dispatch go?")
    started(dashboard, "What needs Marcus?", MARCUS)
    listed = list_conversations(dashboard).json()
    assert [(c["conversation_id"], c["title"]) for c in listed] == [
        (second["conversation_id"], "How did the latest dispatch go?"),
        (first["conversation_id"], "What needs me today?"),
    ]
    assert [c["title"] for c in list_conversations(dashboard, MARCUS).json()] == [
        "What needs Marcus?"
    ]


def test_the_sign_in_is_never_kept(client, dashboard, caplog):
    caplog.set_level(logging.DEBUG)
    own = token(DANA)
    held(client, "CLM-1003", 3750.0)
    conversation = start_conversation(dashboard, access_token=own).json()
    conversation_id = conversation["conversation_id"]
    turn_id = latest(conversation)["turn_id"]
    step_id = start_step(dashboard, turn_id).json()["step_id"]
    finish_step(dashboard, turn_id, step_id)
    pause_turn(dashboard, turn_id)
    answer(dashboard, conversation_id, turn_id, "sign_off", bearer(own))
    finish_turn(dashboard, turn_id)
    assert own not in json.dumps(everything_recorded(), default=str)
    assert [r for r in caplog.records if own in r.getMessage()] == []


def test_the_agents_key_never_stands_in_for_a_handler(dashboard, agent_key):
    both = signed_in() | {API_KEY_HEADER: agent_key}
    refused = dashboard.get("/api/settings", headers=both)
    assert refused.status_code == 403
    assert dashboard.get("/api/claims", headers=both).status_code == 200
    assert dashboard.get("/api/settings", headers=signed_in()).status_code == 200
    start = dashboard.post(CONVERSATIONS, json={"message": QUESTION}, headers=both)
    assert start.status_code == 403
    assert count(conversations) == 0


def test_seeding_empties_the_conversations(dashboard):
    conversation = started(dashboard)
    start_step(dashboard, latest(conversation)["turn_id"])
    seed(engine())
    assert (count(conversations), count(copilot_turns), count(copilot_steps)) == (
        0,
        0,
        0,
    )
