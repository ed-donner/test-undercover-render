"""The Copilot, as the app calls it: a turn, or the answer to a confirmation, posted to
its AgentCore app on the laptop, with no key, since the payload carries the
handler's sign-in, or sent to its runtime on AgentCore Runtime when
UNDERCOVER_COPILOT_RUNTIME names one, with the conversation's id as the session's,
so a turn soon after the last reaches the same session."""

import os

import httpx

from backend import runtime_calls
from backend.runtime_calls import Payload, Wording

COPILOT = "UNDERCOVER_COPILOT"
# The Copilot's AgentCore app on the laptop, as npm run dev serves it.
LOCAL_COPILOT = "http://127.0.0.1:8081"
RUNTIME = "UNDERCOVER_COPILOT_RUNTIME"
NOT_RUNNING = "The Copilot isn't running"
NO_ANSWER = (
    "The Copilot didn't answer in time. Reload the page to see whether it went through."
)
COULDNT_TAKE = "The Copilot couldn't take the message: {reason}"
WORDING = Wording(NOT_RUNNING, COULDNT_TAKE, NO_ANSWER)

copilot = httpx.Client()


def ask(conversation_id: str, payload: Payload) -> None:
    """Ask the Copilot to work on a conversation, on Runtime in the conversation's
    session when UNDERCOVER_COPILOT_RUNTIME names its runtime, read now, or else on
    the laptop at UNDERCOVER_COPILOT. Raise NotTaken or MayHaveStarted when it
    didn't, or may not have."""
    if arn := os.getenv(RUNTIME):
        runtime_calls.invoke(arn, conversation_id, payload, WORDING)
    else:
        url = os.getenv(COPILOT, LOCAL_COPILOT)
        runtime_calls.post(copilot, url, payload, {}, WORDING)


def take_turn(conversation_id: str, turn_id: str, sign_in: str) -> None:
    """Ask the Copilot to answer a turn's message, as the handler signed in."""
    ask(conversation_id, on_a_turn("take_turn", conversation_id, turn_id, sign_in))


def answer_confirmation(conversation_id: str, turn_id: str, sign_in: str) -> None:
    """Ask the Copilot to carry a turn on with the handler's answer to its
    confirmation, which it reads from the turn."""
    payload = on_a_turn("answer_confirmation", conversation_id, turn_id, sign_in)
    ask(conversation_id, payload)


def on_a_turn(
    operation: str, conversation_id: str, turn_id: str, sign_in: str
) -> Payload:
    """The payload of an operation on a conversation's turn, with the handler's
    sign-in."""
    return {
        "operation": operation,
        "conversation_id": conversation_id,
        "turn_id": turn_id,
        "sign_in": sign_in,
    }
