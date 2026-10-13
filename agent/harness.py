"""The harness: it builds the claim agent's graph, with the check for hidden
instructions as its first step, and works a claim with it."""

import logging
import os
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import partial
from typing import Any, cast

from langchain.tools import ToolException
from langchain_core.exceptions import ModelRateLimitError, ModelTimeoutError
from langchain_core.language_models import BaseChatModel, LanguageModelInput
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.runnables import Runnable, RunnableConfig
from langchain_openai import ChatOpenAI
from langfuse.langchain import CallbackHandler
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.runtime import Runtime
from langgraph.types import Command, RetryPolicy
from psycopg import Connection, sql
from psycopg.rows import DictRow, dict_row
from psycopg_pool import ConnectionPool

from agent import api
from agent.connection import Refused
from agent.console import describe
from agent.json_text import as_json
from agent.openrouter import chat_model, usage_of
from agent.root_run import as_root_run
from agent.screening import screen
from agent.tools import CLAIM_TOOLS, ClaimContext, ClaimState, claim_as_read

log = logging.getLogger(__name__)

ClaimGraph = CompiledStateGraph[ClaimState, ClaimContext, Any, Any]
NewGraph = Callable[[], ClaimGraph]
Pool = ConnectionPool[Connection[DictRow]]
Messages = dict[str, list[BaseMessage]]
Start = Messages | None
# Tags for a claim's trace beside its run's, such as the round it works in.
Tags = tuple[str, ...]

# The model's errors that pass with time: a claim that hits one is left in progress,
# with its progress saved, to carry on later.
TRANSIENT = (ModelRateLimitError, ModelTimeoutError)

SCHEMA = "undercover"
CONNECTIONS = 4
CONNECTION_WAIT = 120
CLAIM_MODEL_CALLS = 30
NO_DECISION = "The agent finished without recording a decision"
WORK_CLAIM = "Work claim"
CARRY_ON = "Carry on"
SCREEN = "screen"
REFER = "refer"
AGENT = "agent"
TOOLS = "tools"
PAY = "pay"


# The check's result as the claim's first step, and the section of the referral it
# makes when it finds an instruction.
FOUND = "Instructions found. {reason}"
NONE_FOUND = "No instructions found. {reason}"
SECURITY_CHECK = "Security check: no section of the wording or the manual applies"


class TooManyModelCalls(Exception):
    """The claim agent made as many model calls as it may without finishing."""


class UnreadableScreening(Exception):
    """The check for hidden instructions gave an answer that can't be read."""


# Tries the check three times in all when its answer can't be read, and for nothing
# else: a rate limit, a timeout or a refusal goes on like any error in the graph.
SCREEN_RETRY = RetryPolicy(max_attempts=3, retry_on=UnreadableScreening)


def model(named: dict[str, Any]) -> ChatOpenAI:
    """Return the model a version or get_screening names, at its reasoning effort."""
    return chat_model(named["model"], named["reasoning_effort"], timeout=120)


@contextmanager
def checkpoint_pool() -> Iterator[Pool]:
    """Open the process's pool of at most CONNECTIONS connections to DATABASE_URL,
    where claim graphs save their progress in our own schema, set up once. A claim
    agent waits up to CONNECTION_WAIT seconds for a connection."""
    settings = {
        "autocommit": True,
        "prepare_threshold": 0,
        "row_factory": dict_row,
        "options": f"-c search_path={SCHEMA}",
    }
    with ConnectionPool[Connection[DictRow]](
        os.environ["DATABASE_URL"],
        min_size=1,
        max_size=CONNECTIONS,
        timeout=CONNECTION_WAIT,
        kwargs=settings,
    ) as pool:
        with pool.connection() as connection:
            create = sql.SQL("CREATE SCHEMA IF NOT EXISTS {}")
            connection.execute(create.format(sql.Identifier(SCHEMA)))
        PostgresSaver(pool).setup()
        yield pool


def refusal(error: Exception) -> str:
    """Show the model why a tool was refused, and let any other error stop the agent."""
    if isinstance(error, Refused):
        return f"Refused with status {error}"
    if isinstance(error, ToolException):
        return f"Refused: {error}"
    raise error


def record_reply(claim_id: str, reply: BaseMessage) -> None:
    """Record the model's reply on the claim: its text, then each tool it calls."""
    if reply.text:
        api.record_step(claim_id, "message", reply.text)
    if isinstance(reply, AIMessage):
        for call in reply.tool_calls:
            args = ", ".join(f"{k}={as_json(v)}" for k, v in call["args"].items())
            api.record_step(claim_id, "tool_call", f"{call['name']}({args})")


def record_result(
    request: ToolCallRequest,
    execute: Callable[[ToolCallRequest], ToolMessage | Command],
) -> ToolMessage | Command:
    """Run a tool and record its result on the claim, then any step it gives as its
    artifact, such as a section it read."""
    result = execute(request)
    if isinstance(result, ToolMessage):
        message = result
    else:
        message = cast(dict[str, Any], result.update)["messages"][0]
    claim_id = cast(ClaimContext, request.runtime.context).claim_id
    api.record_step(claim_id, "tool_result", f"{message.name}: {message.text}")
    if message.artifact:
        api.record_step(claim_id, *message.artifact)
    return result


def record_call(context: ClaimContext, reply: BaseMessage) -> None:
    """Record the tokens and the cost of one model call, as OpenRouter reports them."""
    api.record_model_call(context.claim_id, context.run_id, *usage_of(reply))


def screen_claim(
    state: ClaimState, runtime: Runtime[ClaimContext], screener: BaseChatModel
) -> dict[str, Any]:
    """Have the check read the claim as the claim agent's get_claim tool gives it,
    before the claim agent's model sees it, and record its call and its result as
    the claim's first step. Raise UnreadableScreening, after recording the call,
    when its answer can't be read."""
    context = runtime.context
    reply, screening = screen(screener, claim_as_read(context.claim_id))
    record_call(context, reply)
    if screening is None:
        raise UnreadableScreening("The security check's answer couldn't be read")
    line = FOUND if screening.instructions_found else NONE_FOUND
    api.record_step(context.claim_id, "screening", line.format(reason=screening.reason))
    return {"screening": screening.model_dump()}


def refer(state: ClaimState, runtime: Runtime[ClaimContext]) -> dict[str, Any]:
    """Refer a claim the check flagged to a handler, with the check's reason."""
    reason = state["screening"]["reason"]
    claim = api.record_decision(
        runtime.context.claim_id, api.REFER, 0, SECURITY_CHECK, reason
    )
    return {"decision": claim["decision"], "status": claim["status"]}


def call_model(
    state: ClaimState,
    runtime: Runtime[ClaimContext],
    llm: Runnable[LanguageModelInput, BaseMessage],
    instructions: SystemMessage,
) -> dict[str, Any]:
    """Ask the model for its next step, up to CLAIM_MODEL_CALLS times in all, and
    record its cost and its reply on the claim."""
    calls = state["model_calls"]
    if calls >= CLAIM_MODEL_CALLS:
        message = f"The claim agent made {calls} model calls without finishing"
        raise TooManyModelCalls(message)
    reply = llm.invoke([instructions, *state["messages"]])
    record_call(runtime.context, reply)
    record_reply(runtime.context.claim_id, reply)
    return {"messages": [reply], "model_calls": 1}


def pay(state: ClaimState, runtime: Runtime[ClaimContext]) -> dict[str, Any]:
    """Pay the approved payout, which the backend refuses unless it may be paid."""
    claim = api.pay_claim(runtime.context.claim_id, state["decision"]["payout"])
    return {"status": claim["status"]}


def after_screen(state: ClaimState) -> str:
    """Refer a claim the check found an instruction in, or hand it to the model."""
    return REFER if state["screening"]["instructions_found"] else AGENT


def after_agent(state: ClaimState) -> str:
    """Run the tools the model asked for, or stop: it finished without a decision."""
    reply = state["messages"][-1]
    return TOOLS if isinstance(reply, AIMessage) and reply.tool_calls else END


def after_tools(state: ClaimState) -> str:
    """Go back to the model until a decision is recorded, then pay an approval the
    backend can pay at once, or stop: a payout it holds is paid by the handler's
    sign-off, so the claim's work ends there."""
    decision, status = state["decision"], state["status"]
    if not decision:
        return AGENT
    if decision["decision"] == api.APPROVE and status == api.Status.IN_PROGRESS:
        return PAY
    return END


def claim_graph(
    llm: BaseChatModel,
    screener: BaseChatModel,
    saver: BaseCheckpointSaver[Any],
    instructions: str,
) -> ClaimGraph:
    """Build the claim agent's graph, which saves its progress after every step: the
    check for hidden instructions on its own model, then the claim agent on its
    model, with its instructions."""
    builder = StateGraph(ClaimState, context_schema=ClaimContext)
    builder.add_node(
        SCREEN, partial(screen_claim, screener=screener), retry_policy=SCREEN_RETRY
    )
    builder.add_node(REFER, refer)
    builder.add_node(
        AGENT,
        partial(
            call_model,
            llm=llm.bind_tools(CLAIM_TOOLS),
            instructions=SystemMessage(instructions),
        ),
    )
    builder.add_node(
        TOOLS,
        ToolNode(CLAIM_TOOLS, handle_tool_errors=refusal, wrap_tool_call=record_result),
    )
    builder.add_node(PAY, pay)
    builder.add_edge(START, SCREEN)
    builder.add_conditional_edges(SCREEN, after_screen, [REFER, AGENT])
    builder.add_edge(REFER, END)
    builder.add_conditional_edges(AGENT, after_agent, [TOOLS, END])
    builder.add_conditional_edges(TOOLS, after_tools, [AGENT, PAY, END])
    builder.add_edge(PAY, END)
    return builder.compile(checkpointer=saver)


def claim_graphs(version: dict[str, Any], pool: Pool) -> NewGraph:
    """Return how to build a version's claim graph with a saver of its own on the
    pool, since a saver lets one claim at a time read or write. The check runs on
    the model the backend names for it."""
    llm, screener = model(version), model(api.get_screening())

    def new_graph() -> ClaimGraph:
        return claim_graph(llm, screener, PostgresSaver(pool), version["instructions"])

    return new_graph


def thread_of(claim: dict[str, Any]) -> RunnableConfig:
    """Address the claim's thread, where the claim graph saves its progress."""
    return {"configurable": {"thread_id": claim["thread_id"]}}


def claim_config(
    claim: dict[str, Any], name: str, run_id: str | None, tags: Tags
) -> RunnableConfig:
    """Run on the claim's thread, traced in Langfuse in the session of that thread
    and tagged with the run, if any, and any other tags, such as its round."""
    session = f"{claim['claim_id']}:{claim['thread_id']}"
    metadata: dict[str, Any] = {
        "langfuse_session_id": session,
        "langfuse_trace_name": name,
    }
    if run_id is not None:
        metadata["langfuse_tags"] = [run_id, *tags]
    return thread_of(claim) | {
        "callbacks": [CallbackHandler()],
        "metadata": metadata,
        # One tool call at a time, so two decisions in one reply can't race.
        "max_concurrency": 1,
    }


def begin(claim_id: str) -> Messages:
    """Give a claim agent its first message, naming the claim it works on."""
    return {"messages": [HumanMessage(f"Claim {claim_id}")]}


def report(claim: dict[str, Any], reason: str) -> str:
    """Say in one line how a claim ended: its decision and payout, or why it failed."""
    claim_id, status, decision = claim["claim_id"], claim["status"], claim["decision"]
    if status == api.Status.WAITING:
        return f"{claim_id}  failed: {reason}, back in the queue"
    if status == api.Status.LEFT_FOR_HANDLER:
        return f"{claim_id}  failed: {reason}, left for a handler"
    line = f"{claim_id}  {decision['decision']}  ${decision['payout']:,.2f}"
    if status == api.Status.WAITING_FOR_SIGN_OFF:
        return f"{line}, waiting for sign-off"
    if decision["decision"] == api.APPROVE and claim["payment"] is None:
        return f"{line}, not paid yet"
    return line


def run_claim_graph(
    graph: ClaimGraph, start: Start, config: RunnableConfig, context: ClaimContext
) -> str | None:
    """Run the claim graph on the claim's thread, saving each step, and say what went
    wrong, if anything. A rate limit or a timeout is raised again, leaving the claim
    in progress with its progress saved, to carry on later."""
    try:
        as_root_run(graph.invoke, start, config, context=context, durability="sync")
    except TRANSIENT:
        raise
    except Exception as error:  # a claim that fails must not stop the run
        return describe(error)
    return None


@contextmanager
def spell(claim_id: str, run_id: str | None) -> Iterator[None]:
    """Time one spell of work on a claim, and record it however it ends."""
    started = time.monotonic()
    try:
        yield
    finally:
        api.record_work_time(claim_id, run_id, time.monotonic() - started)


def settle(claim_id: str, error: str | None) -> str:
    """Fail a claim the agent left undecided, and report how the claim ended. An
    error after the decision is logged, and the claim keeps its decision."""
    claim = api.get_claim(claim_id)
    reason = error or NO_DECISION
    if claim["status"] == api.Status.IN_PROGRESS and claim["decision"] is None:
        claim = api.fail_claim(claim_id, reason)
    elif error:
        log.warning("%s  %s", claim_id, error)
    line = report(claim, reason)
    log.info(line)
    return line


def work_claim(
    claim_id: str, run_id: str | None, graph: ClaimGraph, tags: Tags = ()
) -> str:
    """Work one claim from a clean start, as a new attempt, in the run given if any,
    and report how it ended."""
    claim = api.start_claim(claim_id, str(uuid.uuid4()))
    config = claim_config(claim, WORK_CLAIM, run_id, tags)
    with spell(claim_id, run_id):
        error = run_claim_graph(
            graph, begin(claim_id), config, ClaimContext(claim_id, run_id)
        )
        return settle(claim_id, error)


def carry_on(
    claim_id: str, run_id: str | None, graph: ClaimGraph, tags: Tags = ()
) -> str:
    """Carry a claim in progress on from its saved progress, as the same attempt, and
    report how it ended. One with nothing saved, stopped before its first step,
    starts on its own thread; any other carries on, finishing a step whose writes
    were saved. A claim whose work has ended has nothing left to run."""
    claim = api.get_claim(claim_id)
    saved = graph.get_state(thread_of(claim))
    start: Start = None
    if saved.created_at is None and claim["decision"] is None:
        start = begin(claim_id)
    config = claim_config(claim, CARRY_ON, run_id, tags)
    with spell(claim_id, run_id):
        error = run_claim_graph(graph, start, config, ClaimContext(claim_id, run_id))
        return settle(claim_id, error)


def work_in_run(
    claim_id: str, run_id: str, new_graph: NewGraph, tags: Tags = ()
) -> str:
    """Work one claim in a run on a claim graph of its own, carrying it on if it is
    in progress or starting it if it is waiting, and report how it ended, with any
    tags for its trace beside the run's."""
    graph = new_graph()
    if api.get_claim(claim_id)["status"] == api.Status.IN_PROGRESS:
        return carry_on(claim_id, run_id, graph, tags)
    return work_claim(claim_id, run_id, graph, tags)
