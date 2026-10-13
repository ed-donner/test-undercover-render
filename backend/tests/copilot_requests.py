"""Requests the backend's tests send about the Copilot's conversations: a handler's,
from the sidebar, and the Copilot's own records of a turn, which it sends with the
handler's sign-in."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import update

from backend.database import copilot_turns, engine, stamp_precisely
from backend.tests.sign_in import DANA, bearer, signed_in

CONVERSATIONS = "/api/copilot/conversations"
TURNS = "/api/copilot/turns"
QUESTION = "What needs me today?"


def start_conversation(client, message=QUESTION, email=DANA, access_token=None):
    """Start a conversation as a handler, with a new sign-in for the email or the
    access token given."""
    headers = bearer(access_token) if access_token else signed_in(email)
    return client.post(CONVERSATIONS, json={"message": message}, headers=headers)


def conversation_of(client, conversation_id, email=DANA):
    return client.get(f"{CONVERSATIONS}/{conversation_id}", headers=signed_in(email))


def send_message(
    client, conversation_id, message="And the latest dispatch?", email=DANA
):
    return client.post(
        f"{CONVERSATIONS}/{conversation_id}/messages",
        json={"message": message},
        headers=signed_in(email),
    )


def answer(client, conversation_id, turn_id, answer="sign_off", headers=None):
    """Answer a turn's confirmation card, as Dana Whitfield unless the headers say
    otherwise."""
    return client.post(
        f"{CONVERSATIONS}/{conversation_id}/confirmation",
        json={"turn_id": turn_id, "answer": answer},
        headers=headers or signed_in(),
    )


def list_conversations(client, email=DANA):
    return client.get(CONVERSATIONS, headers=signed_in(email))


def started(client, message=QUESTION, email=DANA):
    """Start a conversation as a handler does, and return it."""
    return start_conversation(client, message, email).json()


def latest(conversation):
    """A conversation's latest turn."""
    return conversation["turns"][-1]


def start_step(client, turn_id, tool="get_claim", input="CLM-1012", email=DANA):
    body = {"tool": tool, "kind": "claims", "input": input, "asked": '{"claim_id": 1}'}
    return client.post(f"{TURNS}/{turn_id}/steps", json=body, headers=signed_in(email))


def finish_step(client, turn_id, step_id, status="done", email=DANA, **result):
    body = {"status": status, "answer": "{}", "reason": None, "sources": []} | result
    return client.post(
        f"{TURNS}/{turn_id}/steps/{step_id}/finish",
        json=body,
        headers=signed_in(email),
    )


def finish_turn(client, turn_id, email=DANA, answer="Nothing needs you today."):
    body = {"answer": answer, "model_calls": 4, "cost": 0.0021}
    return client.post(f"{TURNS}/{turn_id}/finish", json=body, headers=signed_in(email))


def pause_turn(client, turn_id, claim_id="CLM-1003", email=DANA):
    return client.post(
        f"{TURNS}/{turn_id}/pause",
        json={"claim_id": claim_id},
        headers=signed_in(email),
    )


def fail_turn(client, turn_id, reason="RuntimeError: It broke", email=DANA):
    return client.post(
        f"{TURNS}/{turn_id}/failure", json={"reason": reason}, headers=signed_in(email)
    )


def times_ago(turn_id, **ago: timedelta):
    """Set a turn's times straight in its table, each that long ago, such as its
    start 21 minutes back."""
    moments = {
        column: stamp_precisely(datetime.now(UTC) - before)
        for column, before in ago.items()
    }
    with engine().begin() as db:
        db.execute(
            update(copilot_turns)
            .where(copilot_turns.c.turn_id == turn_id)
            .values(moments)
        )
