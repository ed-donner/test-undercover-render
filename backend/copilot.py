"""The backend's operations on the Copilot's conversations: the dashboard's, which
start a conversation, send a message or answer a confirmation, each passing the
handler's sign-in on to the Copilot, and read the conversations; and the Copilot's
records of each turn, which it makes with the same sign-in."""

from functools import partial

from fastapi import APIRouter
from sqlalchemy import Connection

from backend import conversations, copilot_service
from backend.asking import commit_and_ask
from backend.dependencies import Database, SignedIn, SignedInHandler, SignIn
from backend.free_models import model_or_free
from backend.models import (
    ConfirmationRequest,
    Conversation,
    ConversationSummary,
    CopilotModel,
    CopilotStep,
    CopilotStepRequest,
    CopilotStepResult,
    CopilotTurn,
    MessageRequest,
    PauseRequest,
    TurnFailureRequest,
    TurnFinishRequest,
)

router = APIRouter()

# The model the Copilot runs on, unless students on free models have one of their
# own.
COPILOT_MODEL = ("openai/gpt-6-luna", "low")
CONVERSATIONS = "/api/copilot/conversations"
CONVERSATION = CONVERSATIONS + "/{conversation_id}"
TURN = "/api/copilot/turns/{turn_id}"


def ask_for_the_turn(
    db: Connection, conversation_id: str, turn_id: str, sign_in: str
) -> None:
    """Ask the Copilot to answer a turn as the handler signed in, which fails the
    turn with the reason when the Copilot didn't take it."""
    commit_and_ask(
        db,
        partial(copilot_service.take_turn, conversation_id, turn_id, sign_in),
        lambda reason: conversations.fail_untaken(db, turn_id, reason),
    )


@router.get(CONVERSATIONS, operation_id="list_conversations")
def list_conversations(handler: SignedIn, db: Database) -> list[ConversationSummary]:
    """List the handler's own conversations with the Copilot, newest first."""
    return conversations.conversations_of(db, handler)


@router.post(CONVERSATIONS, operation_id="start_conversation", status_code=202)
def start_conversation(
    request: MessageRequest, handler: SignedIn, sign_in: SignIn, db: Database
) -> Conversation:
    """Start a conversation with the Copilot with a message, which it answers."""
    conversation_id, turn_id = conversations.start(db, handler, request.message)
    ask_for_the_turn(db, conversation_id, turn_id, sign_in)
    return conversations.conversation(db, conversation_id, handler)


@router.get(CONVERSATION, operation_id="get_conversation")
def get_conversation(
    conversation_id: str, handler: SignedIn, db: Database
) -> Conversation:
    """Get one of the handler's conversations, with each turn and its cards."""
    return conversations.conversation(db, conversation_id, handler)


@router.post(CONVERSATION + "/messages", operation_id="send_message", status_code=202)
def send_message(
    conversation_id: str,
    request: MessageRequest,
    handler: SignedIn,
    sign_in: SignIn,
    db: Database,
) -> Conversation:
    """Send the Copilot a message in a conversation once its last turn has ended."""
    turn_id = conversations.next_turn(db, conversation_id, handler, request.message)
    ask_for_the_turn(db, conversation_id, turn_id, sign_in)
    return conversations.conversation(db, conversation_id, handler)


@router.post(
    CONVERSATION + "/confirmation", operation_id="answer_confirmation", status_code=202
)
def answer_confirmation(
    conversation_id: str,
    request: ConfirmationRequest,
    handler: SignedIn,
    sign_in: SignIn,
    db: Database,
) -> Conversation:
    """Answer the confirmation card a turn shows, which the Copilot carries on from."""
    turn = conversations.waiting_turn(db, conversation_id, request.turn_id, handler)
    conversations.record_answer(db, turn, request.answer)
    commit_and_ask(
        db,
        partial(
            copilot_service.answer_confirmation,
            conversation_id,
            request.turn_id,
            sign_in,
        ),
        lambda reason: conversations.undo_answer(db, request.turn_id),
    )
    return conversations.conversation(db, conversation_id, handler)


@router.get(
    "/api/copilot/model",
    operation_id="get_copilot_model",
    dependencies=[SignedInHandler],
)
def get_copilot_model() -> CopilotModel:
    """Get the model the Copilot runs on and its reasoning effort."""
    model, reasoning_effort = model_or_free(*COPILOT_MODEL)
    return CopilotModel(model=model, reasoning_effort=reasoning_effort)


@router.post(TURN + "/steps", operation_id="start_copilot_step")
def start_copilot_step(
    turn_id: str, request: CopilotStepRequest, handler: SignedIn, db: Database
) -> CopilotStep:
    """Record a card for a tool the Copilot starts on a turn that is working."""
    turn = conversations.working_turn(db, turn_id, handler)
    return conversations.step_view(db, conversations.add_step(db, turn, request))


@router.post(TURN + "/steps/{step_id}/finish", operation_id="finish_copilot_step")
def finish_copilot_step(
    turn_id: str,
    step_id: int,
    request: CopilotStepResult,
    handler: SignedIn,
    db: Database,
) -> CopilotStep:
    """Finish a card of a working turn with what came back, or why not."""
    turn = conversations.working_turn(db, turn_id, handler)
    conversations.finish_step(db, turn, step_id, request)
    return conversations.step_view(db, step_id)


@router.post(TURN + "/finish", operation_id="finish_turn")
def finish_turn(
    turn_id: str, request: TurnFinishRequest, handler: SignedIn, db: Database
) -> CopilotTurn:
    """Record the answer to a working turn, with its model calls and their cost."""
    conversations.finish(db, conversations.working_turn(db, turn_id, handler), request)
    return conversations.turn_view(db, turn_id)


@router.post(TURN + "/pause", operation_id="pause_turn")
def pause_turn(
    turn_id: str, request: PauseRequest, handler: SignedIn, db: Database
) -> CopilotTurn:
    """Record that a working turn waits for the handler to confirm a sign-off."""
    turn = conversations.working_turn(db, turn_id, handler)
    conversations.pause(db, turn, request.claim_id)
    return conversations.turn_view(db, turn_id)


@router.post(TURN + "/failure", operation_id="fail_turn")
def fail_turn(
    turn_id: str, request: TurnFailureRequest, handler: SignedIn, db: Database
) -> CopilotTurn:
    """Record that a working turn failed, with what went wrong."""
    turn = conversations.working_turn(db, turn_id, handler)
    conversations.fail(db, turn, request.reason)
    return conversations.turn_view(db, turn_id)
