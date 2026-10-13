"""The Copilot's graph, written by hand: a node that asks the model, LangGraph's
ToolNode, and the loop between them. A sign-off is checked in code, paused for the
handler's confirmation in a node of its own, and signed off or canceled in code;
the success criteria's answer is written in code; and with a memory, the
handler's memories are searched as a turn starts and its message and answer saved
as it ends. The graph saves its state after every step on the conversation's
thread."""

import logging
import operator
from collections.abc import Callable
from functools import partial
from http import HTTPStatus
from typing import Annotated, Any, TypedDict, cast

from langchain.tools import ToolException
from langchain_core.language_models import BaseChatModel, LanguageModelInput
from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolCall,
    ToolMessage,
)
from langchain_core.runnables import Runnable
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.runtime import Runtime
from langgraph.store.base import BaseStore
from langgraph.types import Command, Overwrite, interrupt
from pydantic import ValidationError

from agent.agentcore_memory import UNREACHABLE
from agent.app_terms import Status
from agent.console import describe
from agent.context_tools import Sources
from agent.copilot import app_api, cards, memory
from agent.copilot.instructions import instructions_for
from agent.copilot.tools import (
    COPILOT_TOOLS,
    KINDS,
    SEARCH_MEMORY,
    SIGN_OFF,
    CopilotContext,
    SignOffClaim,
)
from agent.json_text import as_json
from agent.openrouter import usage_of
from agent.refusals import REFUSED
from agent.routes import GatewayRefused

log = logging.getLogger(__name__)

TURN_MODEL_CALLS = 25
BEGIN = "begin"
RECALL = "recall"
REMEMBER = "remember"
REPORT_CRITERIA = "report_criteria"
AGENT = "agent"
TOOLS = "tools"
CHECK_SIGN_OFF = "check_sign_off"
CONFIRM = "confirm"
SIGN_OFF_NODE = "sign_off"
CANCELLED = "cancelled"
# What the model is told of a call it can't make.
ONE_STEP = REFUSED.format(reason="one step at a time")
ONE_A_TURN = "One sign-off a turn. Please ask me again for the next one."
CANT_SIGN_OFF = "{name} can't sign off payouts over the approval limit of {limit}"
NOT_HELD = "Claim {claim_id} isn't waiting for sign-off"
A_COPY = "Claim {claim_id} is a copy in an evaluation, which nobody signs off"
# How a sign-off the handler didn't confirm ends the turn, written in code.
CANCELED = "Canceled. Nothing was signed off or paid."
NOT_SIGNED_OFF = "I haven't signed off {claim_id}. What would you like to do instead?"
CLAIM_CHANGED = (
    "The claim changed since the card was shown, so I canceled this sign-off "
    "without making a payment. Please ask again."
)
SIGN_OFF_ANSWER = "sign_off"
FOUND_NOTHING = "Nothing remembered that bears on this"
MEMORY_UNREACHABLE = "The memory can't be reached. {error}"
# The app's, the Gateway's and a tool's own refusals, which go back to the model.
REFUSALS = (app_api.Refused, GatewayRefused, ToolException)

CopilotGraph = CompiledStateGraph["CopilotState", CopilotContext, Any, Any]


class TooManyModelCalls(Exception):
    """The Copilot made as many model calls in a turn as it may without
    finishing."""


class CopilotState(TypedDict):
    """What the graph keeps for a conversation, saved after every step: its
    messages, the turn's model calls and their cost, the claim a sign-off asks
    about this turn, the handler's answer to its confirmation, what the memory
    found, and the success criteria's answer once a tool has written it."""

    messages: Annotated[list[AnyMessage], add_messages]
    model_calls: Annotated[int, operator.add]
    cost: Annotated[float, operator.add]
    confirming: str
    confirmation: dict[str, Any]
    remembered: list[str]
    criteria: str


def begin(state: CopilotState) -> dict[str, Any]:
    """Start a turn's counts again from zero, with no sign-off asked about, nothing
    remembered and no answer on the success criteria."""
    return {
        "model_calls": Overwrite(0),
        "cost": Overwrite(0.0),
        "confirming": "",
        "confirmation": {},
        "remembered": [],
        "criteria": "",
    }


def message_of(state: CopilotState) -> str:
    """The handler's message this turn answers."""
    return next(
        m for m in reversed(state["messages"]) if isinstance(m, HumanMessage)
    ).text


def what_was_found(found: list[str]) -> str:
    """What a search of the memory found, as its card shows it."""
    return "\n".join(f"- {text}" for text in found) or FOUND_NOTHING


def recall(state: CopilotState, runtime: Runtime[CopilotContext]) -> dict[str, Any]:
    """Search the handler's memories for what bears on their message, with a card
    of what it found, and keep it for the instructions. A memory that can't be
    reached refuses the card, and the turn goes on without it."""
    context, message = runtime.context, message_of(state)
    card = cards.start(context, SEARCH_MEMORY, {"query": message})
    store = cast(BaseStore, runtime.store)
    try:
        found = memory.recall(store, context.handler["handler_id"], message)
    except UNREACHABLE as error:
        cards.refused(context, card, MEMORY_UNREACHABLE.format(error=error))
        return {"remembered": []}
    cards.done(context, card, what_was_found(found))
    return {"remembered": found}


def remember(state: CopilotState, runtime: Runtime[CopilotContext]) -> None:
    """Save the handler's message and the turn's answer to the handler's memory,
    and nothing else. A memory that can't be reached is logged as a warning, and
    the turn is still answered."""
    context = runtime.context
    try:
        memory.remember(
            cast(BaseStore, runtime.store),
            context.handler["handler_id"],
            context.conversation_id,
            message_of(state),
            state["messages"][-1].text,
        )
    except UNREACHABLE as error:
        log.warning("The Copilot's memory wasn't saved: %s", describe(error))


def report_criteria(state: CopilotState) -> dict[str, Any]:
    """End the turn with the success criteria's answer as it was written in code,
    with no model call."""
    return {"messages": [AIMessage(state["criteria"])]}


def after_tools(state: CopilotState) -> str:
    """End the turn with the success criteria's answer once a tool has written it,
    or go back to the model."""
    return REPORT_CRITERIA if state["criteria"] else AGENT


def call_model(
    state: CopilotState,
    runtime: Runtime[CopilotContext],
    llm: Runnable[LanguageModelInput, BaseMessage],
) -> dict[str, Any]:
    """Ask the model for its next step, up to TURN_MODEL_CALLS times in a turn,
    with the instructions for this handler, built for each call and never saved,
    and keep the call's cost."""
    calls = state["model_calls"]
    if calls >= TURN_MODEL_CALLS:
        message = f"The Copilot made {calls} model calls without finishing"
        raise TooManyModelCalls(message)
    system = SystemMessage(
        instructions_for(runtime.context.handler, state["remembered"])
    )
    reply = llm.invoke([system, *state["messages"]])
    return {"messages": [reply], "model_calls": 1, "cost": usage_of(reply).cost}


def after_agent(state: CopilotState) -> str:
    """Check a sign-off the model asks for, run the tools it asks for, or end the
    turn with its answer."""
    reply = state["messages"][-1]
    if not isinstance(reply, AIMessage) or not reply.tool_calls:
        return END
    if any(call["name"] == SIGN_OFF for call in reply.tool_calls):
        return CHECK_SIGN_OFF
    return TOOLS


def refusal_answer(refusal: Exception) -> str:
    """A refusal as the model is told it."""
    if isinstance(refusal, app_api.Refused | GatewayRefused):
        return refusal.answer
    return REFUSED.format(reason=refusal)


def refusal_reason(refusal: Exception) -> str:
    """A refusal as its card gives it."""
    if isinstance(refusal, app_api.Refused):
        return str(refusal.detail)
    return str(refusal)


def signed_out(refusal: Exception) -> bool:
    """Say whether the app refused the handler's sign-in itself, as when it has
    run out, after which it refuses everything sent with it."""
    return (
        isinstance(refusal, app_api.Refused)
        and refusal.status_code == HTTPStatus.UNAUTHORIZED
    )


def with_card(
    request: ToolCallRequest,
    execute: Callable[[ToolCallRequest], ToolMessage | Command],
) -> ToolMessage | Command:
    """Run a tool with a card recorded as it starts and again when it ends. A
    refusal goes back to the model, its card keeping the bare reason, and any other
    error marks the card failed and stops the turn. A sign-in the app no longer
    accepts stops the turn at once: nothing more can be recorded with it, so the
    card stays working and the app shows the turn working until it reads as
    stopped. A tool the Copilot doesn't have is left to the ToolNode."""
    call = request.tool_call
    if call["name"] not in KINDS:
        return execute(request)
    context = cast(CopilotContext, request.runtime.context)
    card = cards.start(context, call["name"], call["args"])
    try:
        result = execute(request)
    except REFUSALS as refusal:
        if signed_out(refusal):
            raise
        cards.refused(context, card, refusal_reason(refusal))
        return ToolMessage(
            refusal_answer(refusal),
            tool_call_id=call["id"],
            name=call["name"],
            status="error",
        )
    except Exception as error:
        cards.failed(context, card, describe(error))
        raise
    if isinstance(result, ToolMessage):
        message = result
    else:
        message = cast(dict[str, Any], result.update)["messages"][0]
    cards.done(context, card, message.text, sources_of(message))
    return result


def sources_of(message: ToolMessage) -> Sources:
    """The files a context layer answer came from, in the step it gives as its
    artifact."""
    return message.artifact[2] if message.artifact else []


def why_not(context: CopilotContext, claim_id: str) -> str | None:
    """Say why the handler may not sign the claim off, if they may not: they can't
    sign off over the limit, or the claim isn't waiting for sign-off or is an
    evaluation's copy."""
    handler = context.handler
    if not handler["can_approve_over_limit"]:
        limit = app_api.get_settings(context.sign_in)["current"]["approval_limit"]
        return CANT_SIGN_OFF.format(name=handler["name"], limit=f"${limit:,.2f}")
    try:
        claim = app_api.get_claim(context.sign_in, claim_id)
    except app_api.Refused as refused:
        return str(refused.detail)
    if claim["evaluation_id"] is not None:
        return A_COPY.format(claim_id=claim_id)
    if claim["status"] != Status.WAITING_FOR_SIGN_OFF:
        return NOT_HELD.format(claim_id=claim_id)
    return None


def inputs_wrong(error: ValidationError) -> str:
    """Say what's wrong with the inputs of a call the model made."""
    return "; ".join(
        f"{'.'.join(map(str, problem['loc']))}: {problem['msg']}"
        for problem in error.errors()
    )


def refuse_sign_off(
    context: CopilotContext,
    asked: ToolCall,
    answers: list[AnyMessage],
    reason: str,
) -> Command:
    """Refuse the sign-off the model asked for, with a card and the reason, which
    goes back to the model."""
    cards.refused(context, cards.start(context, SIGN_OFF, asked["args"]), reason)
    refused = ToolMessage(
        REFUSED.format(reason=reason),
        tool_call_id=asked["id"],
        status="error",
    )
    return Command(update={"messages": [*answers, refused]}, goto=AGENT)


def check_sign_off(state: CopilotState, runtime: Runtime[CopilotContext]) -> Command:
    """Check in code that the handler may sign off the claim the model asks about,
    once a turn, before the pause, so the card never shows for a handler who
    can't. Any other call in the same reply is refused, one step at a time. A
    refusal goes back to the model with its card; otherwise the claim is kept for
    the confirmation."""
    context = runtime.context
    reply = cast(AIMessage, state["messages"][-1])
    asked = next(call for call in reply.tool_calls if call["name"] == SIGN_OFF)
    answers: list[AnyMessage] = [
        ToolMessage(ONE_STEP, tool_call_id=call["id"], status="error")
        for call in reply.tool_calls
        if call is not asked
    ]
    try:
        claim_id = SignOffClaim.model_validate(asked["args"]).claim_id
    except ValidationError as error:
        return refuse_sign_off(context, asked, answers, inputs_wrong(error))
    reason = ONE_A_TURN if state["confirming"] else why_not(context, claim_id)
    if reason:
        return refuse_sign_off(context, asked, answers, reason)
    return Command(update={"messages": answers, "confirming": claim_id}, goto=CONFIRM)


def confirm(state: CopilotState) -> Command:
    """Pause until the handler answers the confirmation card. A resume runs this
    node again from the top, so nothing goes before the interrupt."""
    answer = interrupt({"claim_id": state["confirming"]})
    goto = SIGN_OFF_NODE if answer["answer"] == SIGN_OFF_ANSWER else CANCELLED
    return Command(update={"confirmation": answer}, goto=goto)


def sign_off_asked(state: CopilotState) -> ToolCall:
    """The model's call for the sign-off the handler answered."""
    reply = next(m for m in reversed(state["messages"]) if isinstance(m, AIMessage))
    return next(call for call in reply.tool_calls if call["name"] == SIGN_OFF)


def signed_off(context: CopilotContext, claim_id: str) -> dict[str, Any]:
    """Sign the claim off through the app as the handler, which pays it and asks
    the claim agent to finish its work, and return it. A claim this handler has
    already signed off, as a sign-off run again after a restart finds it, counts
    as done; any other refusal is raised."""
    try:
        return app_api.sign_off_claim(context.sign_in, claim_id)
    except app_api.Refused:
        claim = app_api.get_claim(context.sign_in, claim_id)
        decision = claim["decision"]
        if decision and decision["signed_off_by"] == context.handler["name"]:
            return claim
        raise


def sign_off(state: CopilotState, runtime: Runtime[CopilotContext]) -> dict[str, Any]:
    """Sign the claim off as the handler, with an action card, and answer the
    model's call with the app's answer, or its refusal."""
    context, claim_id = runtime.context, state["confirming"]
    asked = sign_off_asked(state)
    card = cards.start(context, SIGN_OFF, asked["args"])
    try:
        claim = signed_off(context, claim_id)
    except app_api.Refused as refused:
        cards.refused(context, card, refusal_reason(refused))
        answer = ToolMessage(refused.answer, tool_call_id=asked["id"], status="error")
        return {"messages": [answer]}
    except Exception as error:
        cards.failed(context, card, describe(error))
        raise
    cards.done(context, card, as_json(claim))
    return {"messages": [ToolMessage(as_json(claim), tool_call_id=asked["id"])]}


def cancelled(state: CopilotState) -> dict[str, Any]:
    """Answer the sign-off the handler didn't confirm, and end the turn with a reply
    written in code, with no model call: after the handler's Cancel, or a Sign off
    the app took as a Cancel because the claim changed."""
    asked = sign_off_asked(state)
    if state["confirmation"].get("changed"):
        line = CLAIM_CHANGED
    else:
        line = NOT_SIGNED_OFF.format(claim_id=state["confirming"])
    answer = ToolMessage(CANCELED, tool_call_id=asked["id"])
    return {"messages": [answer, AIMessage(line)]}


def copilot_graph(
    llm: BaseChatModel, saver: BaseCheckpointSaver[Any], store: BaseStore | None
) -> CopilotGraph:
    """Build the Copilot's graph on its model, which saves its state after every
    step with the saver given. With a memory, a turn starts by searching the
    handler's memories and ends by saving its message and answer."""
    remembers = store is not None
    answered = REMEMBER if remembers else END
    tools = ToolNode(COPILOT_TOOLS, handle_tool_errors=False, wrap_tool_call=with_card)
    bound = llm.bind_tools([*COPILOT_TOOLS, SignOffClaim], parallel_tool_calls=False)
    builder = StateGraph(CopilotState, context_schema=CopilotContext)
    builder.add_node(BEGIN, begin)
    builder.add_node(AGENT, partial(call_model, llm=bound))
    builder.add_node(TOOLS, tools)
    builder.add_node(CHECK_SIGN_OFF, check_sign_off, destinations=(AGENT, CONFIRM))
    builder.add_node(CONFIRM, confirm, destinations=(SIGN_OFF_NODE, CANCELLED))
    builder.add_node(SIGN_OFF_NODE, sign_off)
    builder.add_node(CANCELLED, cancelled)
    builder.add_node(REPORT_CRITERIA, report_criteria)
    builder.add_edge(START, BEGIN)
    if remembers:
        builder.add_node(RECALL, recall)
        builder.add_node(REMEMBER, remember)
        builder.add_edge(BEGIN, RECALL)
        builder.add_edge(RECALL, AGENT)
        builder.add_edge(REMEMBER, END)
    else:
        builder.add_edge(BEGIN, AGENT)
    builder.add_conditional_edges(
        AGENT,
        after_agent,
        {TOOLS: TOOLS, CHECK_SIGN_OFF: CHECK_SIGN_OFF, END: answered},
    )
    builder.add_conditional_edges(TOOLS, after_tools, [AGENT, REPORT_CRITERIA])
    builder.add_edge(SIGN_OFF_NODE, AGENT)
    builder.add_edge(CANCELLED, answered)
    builder.add_edge(REPORT_CRITERIA, answered)
    return builder.compile(checkpointer=saver, store=store)
