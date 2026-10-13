"""The Copilot as an AgentCore app: one entrypoint takes each payload the app sends,
a turn or the answer to a confirmation, checks with the app who is signed in and
which turn it is before it answers, keeps one turn at a time for each conversation
in its process, and hands the turn to turns.py on a thread of its own, which its
/ping reports as busy until it ends. npm run dev serves it on 127.0.0.1:8081, and
runtime/copilot.py runs it on AgentCore Runtime. Nothing happens as it's imported:
it gets ready on its first request. It asks for no key: everything it does carries
the handler's sign-in, which the app checks on every call."""

import logging
import random
import threading
from collections.abc import Callable
from functools import partial
from typing import Annotated, Any, Literal

from bedrock_agentcore.runtime import BedrockAgentCoreApp, RequestContext
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres import PostgresSaver
from pydantic import Field, TypeAdapter

from agent import identity
from agent.agentcore_app import (
    ACCEPTED,
    HEALTHY,
    Health,
    Operation,
    Ready,
    Refusal,
    in_background,
    read,
)
from agent.checkpoints import Pool, open_checkpoint_pool
from agent.console import show_reports
from agent.copilot import app_api, turns

log = logging.getLogger(__name__)

NOT_READY = "The Copilot couldn't get ready: {error}"
STILL_WORKING = "Conversation {conversation_id} already has a turn working"
NO_ANSWER = "Turn {turn_id} has no answer to its confirmation yet"
# The Copilot's credentials in AgentCore Identity on Runtime: the project holds
# three, and the Copilot needs two.
CREDENTIALS = ("OPENROUTER_API_KEY", "DATABASE_URL")

app = BedrockAgentCoreApp()


# A handler's sign-in, an access token in the characters a JWT uses, which a
# payload error names without its value and a repr leaves out.
SignIn = Annotated[str, Field(pattern=r"^[A-Za-z0-9_.-]+$", repr=False)]


class TakeTurn(Operation):
    operation: Literal["take_turn"]
    conversation_id: str
    turn_id: str
    sign_in: SignIn


class AnswerConfirmation(Operation):
    operation: Literal["answer_confirmation"]
    conversation_id: str
    turn_id: str
    sign_in: SignIn


Payload = Annotated[
    Health | TakeTurn | AnswerConfirmation, Field(discriminator="operation")
]
PAYLOADS: TypeAdapter[Payload] = TypeAdapter(Payload)


def get_ready() -> Pool:
    """Get ready to work. On Runtime, reseed the random numbers, which every session
    starts with from one snapshot, and fetch the Copilot's two credentials. Then set
    up the report lines and open the checkpoint pool."""
    if identity.on_runtime():
        random.seed()
        identity.fetch_credentials(*CREDENTIALS)
    show_reports()
    return open_checkpoint_pool()


def new_ready() -> Ready[Pool]:
    return Ready(get_ready, NOT_READY)


ready = new_ready()


def saver_on(pool: Pool) -> BaseCheckpointSaver[Any]:
    """A saver of the turn's own on the process's pool, since a saver lets one
    graph at a time read or write."""
    return PostgresSaver(pool)


class Conversations:
    """The conversations with a turn working in this process."""

    def __init__(self) -> None:
        self.guard = threading.Lock()
        self.working: set[str] = set()

    def take(self, conversation_id: str) -> None:
        """Take a conversation for a turn, or refuse while it has one working."""
        with self.guard:
            if conversation_id in self.working:
                message = STILL_WORKING.format(conversation_id=conversation_id)
                raise Refusal(message)
            self.working.add(conversation_id)

    def release(self, conversation_id: str) -> None:
        with self.guard:
            self.working.discard(conversation_id)


working = Conversations()


def hand_on(turn: turns.Turn, work: Callable[[], None]) -> None:
    """Work a turn in the background, one at a time in its conversation. A turn
    that raises, which only happens when the app can't be told it failed, is
    logged."""
    working.take(turn.conversation_id)

    def then_release() -> None:
        try:
            work()
        except (
            Exception
        ):  # a turn the app couldn't be told about stops, and nothing else
            log.exception("Turn %s stopped", turn.turn_id)
        finally:
            working.release(turn.conversation_id)

    in_background(app, "turn", then_release)


def checked(request: TakeTurn | AnswerConfirmation) -> turns.Turn:
    """The turn the app asks for, checked with the app before any model call."""
    return turns.the_turn(request.sign_in, request.conversation_id, request.turn_id)


def take_turn(request: TakeTurn, pool: Pool) -> None:
    """Work a turn's message."""
    turn = checked(request)
    hand_on(turn, partial(turns.take_turn, turn, saver_on(pool)))


def answer_confirmation(request: AnswerConfirmation, pool: Pool) -> None:
    """Carry a paused turn on with the answer the app recorded, refusing a turn with
    no answer recorded or a conversation with no sign-off waiting."""
    turn = checked(request)
    if turn.record["confirmation_answer"] is None:
        raise Refusal(NO_ANSWER.format(turn_id=turn.turn_id))
    saver = saver_on(pool)
    turns.check_paused(turn, saver)
    hand_on(turn, partial(turns.answer_confirmation, turn, saver))


def start(request: Payload, pool: Pool) -> dict[str, Any]:
    """Hand an operation its work, and answer that the Copilot took it."""
    match request:
        case Health():
            return HEALTHY
        case TakeTurn():
            take_turn(request, pool)
        case AnswerConfirmation():
            answer_confirmation(request, pool)
    return ACCEPTED


@app.entrypoint
def invoke(payload: Any, context: RequestContext) -> dict[str, Any]:
    """Take one payload: get ready, read it, and start its work, or say why the
    Copilot won't."""
    pool = ready.get()
    request = read(PAYLOADS, payload)
    try:
        return start(request, pool)
    except (Refusal, turns.NotThisTurn) as refusal:
        return {"refused": str(refusal)}
    except app_api.Refused as refused:  # the app's, such as a sign-in it refuses
        return {"refused": str(refused.detail)}
