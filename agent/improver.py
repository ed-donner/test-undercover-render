"""The improver: a LangChain agent that follows a recipe to improve the claim agent's
configuration, as in labs/week2day5.ipynb. A handler approves each change and each
new recipe before it takes effect, and the backend keeps or rolls back each version
by the business's rule."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

from langchain.agents import create_agent
from langchain.agents.middleware import (
    AgentMiddleware,
    AgentState,
    HumanInTheLoopMiddleware,
    InterruptOnConfig,
    ModelCallLimitMiddleware,
    ModelRequest,
    ModelResponse,
    ToolErrorMiddleware,
    after_model,
    before_model,
    wrap_model_call,
)
from langchain.agents.middleware.human_in_the_loop import DecisionType
from langchain.tools import ToolRuntime, tool
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from langfuse.langchain import CallbackHandler
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.runtime import Runtime
from langgraph.types import Command

from agent import improver_api
from agent.connection import Refused
from agent.json_text import as_json
from agent.openrouter import chat_model, usage_of
from agent.root_run import as_root_run

# The improver's model calls in a round, counted across its stretches of work.
IMPROVER_MODEL_CALLS = 20
FIRST_MESSAGE = "Please carry out one round of your recipe."
TRACE_NAME = "Improver"

APPROVE_OR_REJECT: list[DecisionType] = ["approve", "reject"]

# Works one of the round's evaluations through the dispatcher, given the run the
# backend created for it: the service binds it to the claim agents.
Evaluate = Callable[[dict[str, Any]], None]
Start = dict[str, Any] | Command


@dataclass
class RoundContext:
    """The round the improver works on, as the backend gave it, and how to work one
    of its evaluations."""

    round: dict[str, Any]
    evaluate: Evaluate


def is_allowed(round: dict[str, Any], model: str, reasoning_effort: str) -> bool:
    """Say whether the claim agent may use a model at a reasoning effort."""
    return any(
        allowed["model"] == model and reasoning_effort in allowed["reasoning_efforts"]
        for allowed in round["models_allowed"]
    )


def round_of(runtime: ToolRuntime[RoundContext] | Runtime[RoundContext]) -> str:
    return runtime.context.round["round_id"]


@tool
def read_results(runtime: ToolRuntime[RoundContext]) -> str:
    """Read the current version of the claim agent's configuration, its scores, its mistakes and weakest explanations on the evaluation set, the earlier rounds, the objectives, the round's spending limit and the models allowed."""  # noqa: E501
    return as_json(improver_api.get_improver_view(round_of(runtime)), indent=2)


@tool(parse_docstring=True)
def propose_change(
    instructions: str,
    model: str,
    reasoning_effort: str,
    reason: str,
    runtime: ToolRuntime[RoundContext],
) -> str:
    """Propose a new version of the claim agent's configuration. A human reviews it before it's saved.

    Args:
        instructions: The claim agent's complete instructions
        model: One of the models allowed
        reasoning_effort: A reasoning level allowed for that model
        reason: Why this change should improve the scores
    """  # noqa: E501
    if not is_allowed(runtime.context.round, model, reasoning_effort):
        return f"{model} at {reasoning_effort} isn't allowed. Choose from the models allowed."  # noqa: E501
    version = improver_api.create_version(round_of(runtime))
    return f"Saved as version {version['number']}. Run the evaluation next."


@tool
def run_evaluation(runtime: ToolRuntime[RoundContext]) -> str:
    """Run the newest version once on the evaluation set and twice on the held-out set, then keep it or roll it back."""  # noqa: E501
    round_id = round_of(runtime)
    refused = ""
    for _ in runtime.context.round["version_evaluations"]:
        try:
            run = improver_api.create_round_evaluation(round_id)
        except Refused as refusal:  # such as when the round can't afford them
            refused = f"{refusal.answer}\n"
            break
        runtime.context.evaluate(run)
    verdict = improver_api.record_verdict(round_id)
    return f"{refused}{verdict['summary']}\n{as_json(verdict['scores'], indent=2)}"


@tool(parse_docstring=True)
def propose_recipe(recipe: str, reason: str, runtime: ToolRuntime[RoundContext]) -> str:
    """Propose a new version of your recipe for improving the claim agent. A human reviews it before it's saved.

    Args:
        recipe: The complete new recipe
        reason: What this round showed, and why the new recipe should lead to better changes
    """  # noqa: E501
    saved = improver_api.create_recipe(round_of(runtime))
    return f"Saved as recipe version {saved['number']}."


IMPROVER_TOOLS = [read_results, propose_change, run_evaluation, propose_recipe]


def needs_a_handler(request: ToolCallRequest) -> bool:
    """Pause for a handler only for a change the claim agent may use; any other
    goes straight to the tool, which tells the improver it isn't allowed."""
    args = request.tool_call["args"]
    context = cast(RoundContext, request.runtime.context)
    return is_allowed(
        context.round, args.get("model", ""), args.get("reasoning_effort", "")
    )


def answer_refusals(error: Exception, request: ToolCallRequest) -> str | None:
    """Answer the improver with the backend's refusal, as the lab's tools answer
    with a sentence, so it can take it into account. Any other error stops it."""
    return error.answer if isinstance(error, Refused) else None


@wrap_model_call
def one_tool_call_at_a_time(
    request: ModelRequest, handler: Callable[[ModelRequest], ModelResponse]
) -> ModelResponse:
    """Turn parallel tool calls off, so a reply never holds two proposals."""
    settings = {**request.model_settings, "parallel_tool_calls": False}
    return handler(request.override(model_settings=settings))


@before_model(can_jump_to=["end"])
def stop_with_the_round(
    state: AgentState, runtime: Runtime[RoundContext]
) -> dict[str, Any] | None:
    """End the stretch once the round is no longer open, such as when a handler
    stops it."""
    if improver_api.get_round(round_of(runtime))["status"] != improver_api.OPEN:
        return {"jump_to": "end"}
    return None


@after_model(can_jump_to=["end"])
def record_the_call(
    state: AgentState, runtime: Runtime[RoundContext]
) -> dict[str, Any] | None:
    """Record the tokens and the cost of the model call with the round, as
    OpenRouter reports them. A round stopped while the model answered records
    nothing more, so the stretch ends there."""
    reply = cast(AIMessage, state["messages"][-1])
    try:
        improver_api.record_improver_call(round_of(runtime), *usage_of(reply))
    except Refused:
        return {"jump_to": "end"}
    return None


Improver = CompiledStateGraph[AgentState[Any], RoundContext, Any, Any]


def improver_model(round: dict[str, Any]) -> ChatOpenAI:
    """The round's improver model, at its reasoning effort."""
    return chat_model(
        round["improver_model"], round["improver_reasoning_effort"], timeout=300
    )


def improver(
    round: dict[str, Any], model: BaseChatModel, saver: BaseCheckpointSaver[Any]
) -> Improver:
    """Build the improver for a round: its instructions around the round's recipe,
    its four tools, and the handler's approval it waits for."""
    middleware: list[AgentMiddleware[Any, Any, Any]] = [
        HumanInTheLoopMiddleware(
            interrupt_on={
                propose_change.name: InterruptOnConfig(
                    allowed_decisions=APPROVE_OR_REJECT, when=needs_a_handler
                ),
                propose_recipe.name: InterruptOnConfig(
                    allowed_decisions=APPROVE_OR_REJECT
                ),
            }
        ),
        ModelCallLimitMiddleware(
            thread_limit=IMPROVER_MODEL_CALLS, exit_behavior="error"
        ),
        stop_with_the_round,
        one_tool_call_at_a_time,
        ToolErrorMiddleware(on_error=answer_refusals),
        record_the_call,
    ]
    return create_agent(
        model=model,
        tools=IMPROVER_TOOLS,
        system_prompt=round["instructions"],
        context_schema=RoundContext,
        checkpointer=saver,
        middleware=middleware,
    )


def round_config(round: dict[str, Any]) -> RunnableConfig:
    """Run on the round's thread, traced in Langfuse in the round's session."""
    return {
        "configurable": {"thread_id": round["thread_id"]},
        "callbacks": [CallbackHandler()],
        "metadata": {
            "langfuse_session_id": f"Round {round['number']}:{round['round_id']}",
            "langfuse_trace_name": TRACE_NAME,
        },
    }


def begin() -> dict[str, Any]:
    """The improver's first message in a round."""
    return {"messages": [HumanMessage(FIRST_MESSAGE)]}


def resume(review: improver_api.Review, reason: str) -> Command:
    """Carry the improver on with a handler's review of its proposal."""
    if review == improver_api.APPROVED:
        return Command(resume={"decisions": [{"type": "approve"}]})
    return Command(resume={"decisions": [{"type": "reject", "message": reason}]})


def work_stretch(
    round: dict[str, Any],
    start: Start,
    evaluate: Evaluate,
    saver: BaseCheckpointSaver[Any],
    model: BaseChatModel,
) -> dict[str, Any] | None:
    """Run the improver on the round's thread until it waits for a handler or ends,
    and return what it proposes, if it is waiting."""
    agent = improver(round, model, saver)
    result: dict[str, Any] = as_root_run(
        agent.invoke,
        start,
        round_config(round),
        context=RoundContext(round, evaluate),
        durability="sync",
    )
    waiting = result.get("__interrupt__")
    if not waiting:
        return None
    return waiting[0].value["action_requests"][0]


def record_proposal(round_id: str, request: dict[str, Any]) -> None:
    """Record what the improver waits for a handler to approve, from the tool call
    it paused on."""
    args = request["args"]
    if request["name"] == propose_change.name:
        improver_api.record_change_proposal(
            round_id,
            args["instructions"],
            args["model"],
            args["reasoning_effort"],
            args["reason"],
        )
    else:
        improver_api.record_recipe_proposal(round_id, args["recipe"], args["reason"])
