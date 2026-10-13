"""The harness: it builds the claim agent's graph, with the check for hidden
instructions as its first step, and works a claim with it."""

import logging
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
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
from langgraph.store.base import BaseStore
from langgraph.types import Command, Overwrite, RetryPolicy, interrupt

from agent import api, app_terms, handler_answer, memory, tool_route
from agent.checkpoints import Pool
from agent.connection import Refused
from agent.console import describe
from agent.json_text import as_json
from agent.openrouter import chat_model, usage_of
from agent.refusals import REFUSED
from agent.root_run import as_root_run
from agent.routes import GatewayRefused, Route, Target
from agent.screening import screen
from agent.tools import (
    TARGETS,
    ClaimContext,
    ClaimState,
    claim_as_read,
    claim_tools,
)

log = logging.getLogger(__name__)

ClaimGraph = CompiledStateGraph[ClaimState, ClaimContext, Any, Any]
Messages = dict[str, list[BaseMessage]]
Start = Messages | Command | None
# Tags for a claim's trace beside its run's, such as the round it works in.
Tags = tuple[str, ...]

# The model's errors that pass with time: a claim that hits one is left in progress,
# with its progress saved, to carry on later.
TRANSIENT = (ModelRateLimitError, ModelTimeoutError)

CLAIM_MODEL_CALLS = 30
NO_DECISION = "The agent finished without recording a decision"
WORK_CLAIM = "Work claim"
CARRY_ON = "Carry on"
RESUME = "Resume"
SCREEN = "screen"
REFER = "refer"
AGENT = "agent"
TOOLS = "tools"
PAY = "pay"
REMEMBER = "remember"
WAIT_FOR_HANDLER = "wait_for_handler"
# Where a decision goes when its payout is held for a handler's sign-off.
HELD = "held"
PAY_CLAIM = "pay_claim"
REFUSAL = "refusal"


# The check's result as the claim's first step, and the section and the maker of
# the referral it makes when it finds an instruction, which sits outside the
# versions of the claim agent.
FOUND = "Instructions found. {reason}"
NONE_FOUND = "No instructions found. {reason}"
SECURITY_CHECK = "Security check: no section of the wording or the manual applies"
CHECK_DECIDES = "Security check"
# Who makes the claim agent's decisions: the version of its configuration.
AGENT_DECIDES = "UnderCover Agent, version {number}"


class TooManyModelCalls(Exception):
    """The claim agent made as many model calls as it may without finishing."""


class UnreadableScreening(Exception):
    """The check for hidden instructions gave an answer that can't be read."""


# Tries the check three times in all when its answer can't be read, and for nothing
# else: a rate limit, a timeout or a refusal goes on like any error in the graph.
SCREEN_RETRY = RetryPolicy(max_attempts=3, retry_on=UnreadableScreening)


def model(named: dict[str, Any]) -> ChatOpenAI:
    """Return the model a version or get_screening names, at its reasoning effort."""
    return chat_model(named["model"], named["reasoning_effort"])


def refusal(error: Exception) -> str:
    """Show the model why a tool was refused, by the app, the Gateway or the tool's
    own checks, and let any other error stop the agent."""
    if isinstance(error, Refused):
        return f"Refused with status {error}"
    if isinstance(error, GatewayRefused):
        return error.answer
    if isinstance(error, ToolException):
        return REFUSED.format(reason=error)
    raise error


def named(context: ClaimContext, tool: str) -> str:
    """Name a call to one of the claim agent's tools as its route names it, or as
    the model did for a tool the claim agent doesn't have."""
    target = TARGETS.get(tool)
    return context.route.name(target, tool) if target else tool


def record_reply(context: ClaimContext, reply: BaseMessage) -> None:
    """Record the model's reply on the claim: its text, then each tool it calls,
    named as the route names it."""
    if reply.text:
        api.record_step(context.claim_id, "message", reply.text, [])
    if isinstance(reply, AIMessage):
        for call in reply.tool_calls:
            args = ", ".join(f"{k}={as_json(v)}" for k, v in call["args"].items())
            name = named(context, call["name"])
            api.record_step(context.claim_id, "tool_call", f"{name}({args})", [])


def record_result(
    request: ToolCallRequest,
    execute: Callable[[ToolCallRequest], ToolMessage | Command],
) -> ToolMessage | Command:
    """Run a tool and record its result on the claim, or its refusal, named as the
    route names the tool, then any step it gives as its artifact, such as what it
    looked up and the files that came from."""
    result = execute(request)
    if isinstance(result, ToolMessage):
        message = result
    else:
        message = cast(dict[str, Any], result.update)["messages"][0]
    context = cast(ClaimContext, request.runtime.context)
    kind = REFUSAL if message.status == "error" else "tool_result"
    name = named(context, request.tool_call["name"])
    api.record_step(context.claim_id, kind, f"{name}: {message.text}", [])
    if message.artifact:
        api.record_step(context.claim_id, *message.artifact)
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
    reply, screening = screen(screener, claim_as_read(api.get_claim(context.claim_id)))
    record_call(context, reply)
    if screening is None:
        raise UnreadableScreening("The security check's answer couldn't be read")
    line = FOUND if screening.instructions_found else NONE_FOUND
    checked = line.format(reason=screening.reason)
    api.record_step(context.claim_id, "screening", checked, [])
    return {"screening": screening.model_dump()}


def refer(state: ClaimState, runtime: Runtime[ClaimContext]) -> dict[str, Any]:
    """Refer a claim the check flagged to a handler, with the check's reason."""
    reason = state["screening"]["reason"]
    claim = api.record_decision(
        runtime.context.claim_id,
        decision=app_terms.REFER,
        payout=0,
        section=SECURITY_CHECK,
        reason=reason,
        decided_by=CHECK_DECIDES,
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
    record_reply(runtime.context, reply)
    return {"messages": [reply], "model_calls": 1}


def pay(state: ClaimState, runtime: Runtime[ClaimContext]) -> dict[str, Any]:
    """Pay the approved payout on the claim agent's route, which the app refuses
    unless it may be paid, and hold a payment the Gateway refuses."""
    context = runtime.context
    payment = {"claim_id": context.claim_id, "amount": state["decision"]["payout"]}
    try:
        claim = context.route.call(Target.APP, PAY_CLAIM, payment)
    except GatewayRefused as refused:
        claim = hold(context, refused)
    return {"status": claim["status"]}


def hold(context: ClaimContext, refused: GatewayRefused) -> dict[str, Any]:
    """Record the Gateway's refusal of a payment on the claim, and hold the payment
    for a handler's sign-off with the Gateway's reason."""
    name = context.route.name(Target.APP, PAY_CLAIM)
    api.record_step(context.claim_id, REFUSAL, f"{name}: {refused.answer}", [])
    return api.hold_payment(context.claim_id, str(refused))


def after_screen(state: ClaimState) -> str:
    """Refer a claim the check found an instruction in, or hand it to the model."""
    return REFER if state["screening"]["instructions_found"] else AGENT


def after_agent(state: ClaimState) -> str:
    """Run the tools the model asked for, or stop: it finished without a decision."""
    reply = state["messages"][-1]
    return TOOLS if isinstance(reply, AIMessage) and reply.tool_calls else END


def after_tools(state: ClaimState) -> str:
    """Go back to the model until a decision is recorded, then pay an approval the
    backend can pay at once, hold one it holds for a handler's sign-off, or end the
    claim agent's work. The graph maps a held payout to the pause, or to the end
    for a graph that doesn't pause, and the end to `remember` when it has a
    memory."""
    decision, status = state["decision"], state["status"]
    if not decision:
        return AGENT
    if status == app_terms.Status.WAITING_FOR_SIGN_OFF:
        return HELD
    if (
        decision["decision"] == app_terms.APPROVE
        and status == app_terms.Status.IN_PROGRESS
    ):
        return PAY
    return END


def after_pay(state: ClaimState) -> str:
    """Hold a payment the Gateway refused for a handler's sign-off, or end the claim
    agent's work on a claim that is paid."""
    return HELD if state["status"] == app_terms.Status.WAITING_FOR_SIGN_OFF else END


def wait_for_handler(
    state: ClaimState, runtime: Runtime[ClaimContext]
) -> dict[str, Any]:
    """Pause the claim's work until a handler answers its held approval. A resume
    runs this node again from the top, so nothing goes before the interrupt. A
    sign-off has already paid the claim, so the work then ends. A send back forgets
    the decision, so nothing can pay it, gives the claim agent its full allowance
    of model calls again and hands the model the note."""
    answer = interrupt({"claim_id": runtime.context.claim_id})
    if answer["answer"] != handler_answer.SENT_BACK:
        return {}
    return {
        "decision": {},
        "status": "",
        "model_calls": Overwrite(0),
        "messages": [handler_answer.note_message(answer)],
    }


def after_handler(state: ClaimState) -> str:
    """Hand a decision sent back to the model, or end the work after a sign-off."""
    return END if state["decision"] else AGENT


def remember(state: ClaimState, runtime: Runtime[ClaimContext]) -> None:
    """Save the claim the claim agent decided to its customer's memory, and record
    what was saved on the claim. When the memory can't be reached, the claim keeps
    its decision and the error is logged as a warning, as any error after the
    decision is."""
    claim = api.get_claim(runtime.context.claim_id)
    saved = memory.remember(cast(BaseStore, runtime.store), claim)
    api.record_step(claim["claim_id"], "memory_save", saved, [])


@dataclass(frozen=True)
class RunTraits:
    """What the kind of run a claim graph works in gives it: a memory of each
    customer, or none, and whether a payout held for sign-off pauses for a
    handler's answer."""

    store: BaseStore | None
    pauses: bool


def traits_of(kind: app_terms.RunKind | None) -> RunTraits:
    """An evaluation's claim graphs have no memory, so its scores don't depend on
    it, and don't pause, since nobody signs off a copy. Any other's have the memory
    the environment names, read now, and pause."""
    if kind == app_terms.EVALUATION:
        return RunTraits(store=None, pauses=False)
    return RunTraits(store=memory.memory_store(), pauses=True)


def claim_graph(
    llm: BaseChatModel,
    screener: BaseChatModel,
    saver: BaseCheckpointSaver[Any],
    instructions: str,
    traits: RunTraits,
) -> ClaimGraph:
    """Build the claim agent's graph, which saves its progress after every step: the
    check for hidden instructions on its own model, then the claim agent on its
    model, with its instructions. With a memory, it can search the customer's, and
    a claim it decides is remembered once its work ends. A graph that pauses waits
    for a handler's answer to a payout held for sign-off; any other ends its work
    there."""
    remembers = traits.store is not None
    tools = claim_tools(remembers)
    decided = REMEMBER if remembers else END
    held = WAIT_FOR_HANDLER if traits.pauses else decided
    builder = StateGraph(ClaimState, context_schema=ClaimContext)
    builder.add_node(
        SCREEN, partial(screen_claim, screener=screener), retry_policy=SCREEN_RETRY
    )
    builder.add_node(REFER, refer)
    builder.add_node(
        AGENT,
        partial(
            call_model,
            llm=llm.bind_tools(tools),
            instructions=SystemMessage(instructions),
        ),
    )
    builder.add_node(
        TOOLS,
        ToolNode(tools, handle_tool_errors=refusal, wrap_tool_call=record_result),
    )
    builder.add_node(PAY, pay)
    builder.add_edge(START, SCREEN)
    builder.add_conditional_edges(SCREEN, after_screen, [REFER, AGENT])
    builder.add_edge(REFER, END)
    builder.add_conditional_edges(AGENT, after_agent, [TOOLS, END])
    builder.add_conditional_edges(
        TOOLS, after_tools, {AGENT: AGENT, PAY: PAY, HELD: held, END: decided}
    )
    builder.add_conditional_edges(PAY, after_pay, {HELD: held, END: decided})
    if traits.pauses:
        builder.add_node(WAIT_FOR_HANDLER, wait_for_handler)
        builder.add_conditional_edges(
            WAIT_FOR_HANDLER, after_handler, {AGENT: AGENT, END: decided}
        )
    if remembers:
        builder.add_node(REMEMBER, remember)
        builder.add_edge(REMEMBER, END)
    return builder.compile(checkpointer=saver, store=traits.store)


@dataclass
class ClaimAgent:
    """A claim graph with a saver of its own, and what its claims' contexts need:
    the route its tools and payment take, and who its decisions are made by."""

    graph: ClaimGraph
    route: Route
    decided_by: str


NewAgent = Callable[[], ClaimAgent]


def maker_of(version: dict[str, Any]) -> str:
    """Say who makes the decisions of a version of the claim agent."""
    return AGENT_DECIDES.format(number=version["number"])


def claim_graphs(
    version: dict[str, Any], kind: app_terms.RunKind | None, pool: Pool
) -> NewAgent:
    """Return how to build a version's claim agent for a kind of run, or none: a
    claim graph with a saver of its own on the pool, since a saver lets one claim
    at a time read or write, on the route and with the memory read when the run's
    agents are built. The check runs on the model the backend names for it."""
    llm, screener = model(version), model(api.get_screening())
    route = tool_route.from_environment()
    traits = traits_of(kind)
    decided_by = maker_of(version)

    def new_agent() -> ClaimAgent:
        saver = PostgresSaver(pool)
        graph = claim_graph(llm, screener, saver, version["instructions"], traits)
        return ClaimAgent(graph, route, decided_by)

    return new_agent


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


def context_of(
    claim: dict[str, Any], run_id: str | None, agent: ClaimAgent
) -> ClaimContext:
    """What the claim agent knows of the claim it works on, in the run given if
    any."""
    return ClaimContext(
        claim["claim_id"],
        run_id,
        claim["policy_id"],
        claim["customer_id"],
        agent.route,
        agent.decided_by,
    )


def begin(claim_id: str) -> Messages:
    """Give a claim agent its first message, naming the claim it works on."""
    return {"messages": [HumanMessage(f"Claim {claim_id}")]}


def report(claim: dict[str, Any], reason: str) -> str:
    """Say in one line how a claim ended: its decision and payout, or why it failed."""
    claim_id, status, decision = claim["claim_id"], claim["status"], claim["decision"]
    if status == app_terms.Status.WAITING:
        return f"{claim_id}  failed: {reason}, back in the queue"
    if status == app_terms.Status.LEFT_FOR_HANDLER:
        return f"{claim_id}  failed: {reason}, left for a handler"
    line = f"{claim_id}  {decision['decision']}  ${decision['payout']:,.2f}"
    if status == app_terms.Status.WAITING_FOR_SIGN_OFF:
        return f"{line}, waiting for sign-off"
    if decision["decision"] == app_terms.APPROVE and claim["payment"] is None:
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
    if claim["status"] == app_terms.Status.IN_PROGRESS and claim["decision"] is None:
        claim = api.fail_claim(claim_id, reason)
    elif error:
        log.warning("%s  %s", claim_id, error)
    line = report(claim, reason)
    log.info(line)
    return line


def work_on(
    claim: dict[str, Any],
    start: Start,
    config: RunnableConfig,
    run_id: str | None,
    agent: ClaimAgent,
) -> str:
    """Run the claim graph on the claim's thread from a start, in the run given if
    any, timed as one spell of work, then settle the claim and report how it
    ended."""
    claim_id = claim["claim_id"]
    context = context_of(claim, run_id, agent)
    with spell(claim_id, run_id):
        error = run_claim_graph(agent.graph, start, config, context)
        return settle(claim_id, error)


def work_claim(
    claim_id: str, run_id: str | None, agent: ClaimAgent, tags: Tags = ()
) -> str:
    """Work one claim from a clean start, as a new attempt, in the run given if any,
    and report how it ended."""
    claim = api.start_claim(claim_id, str(uuid.uuid4()))
    config = claim_config(claim, WORK_CLAIM, run_id, tags)
    return work_on(claim, begin(claim_id), config, run_id, agent)


def carry_on(
    claim_id: str, run_id: str | None, agent: ClaimAgent, tags: Tags = ()
) -> str:
    """Carry a claim in progress on from its saved progress, as the same attempt, and
    report how it ended. One whose next step is the pause resumes with its
    handler's answer, whether the pause has run or not: LangGraph keeps an answer
    given before the pause for the pause to return at once. One with nothing
    saved, stopped before its first step, starts on its own thread; any other
    carries on, finishing a step whose writes were saved. A claim whose work has
    ended has nothing left to run."""
    claim = api.get_claim(claim_id)
    saved = agent.graph.get_state(thread_of(claim))
    answer = handler_answer.answer_of(claim)
    start: Start = None
    if saved.next == (WAIT_FOR_HANDLER,) and answer:
        start = Command(resume=answer)
    elif saved.created_at is None and claim["decision"] is None:
        start = begin(claim_id)
    config = claim_config(claim, CARRY_ON, run_id, tags)
    return work_on(claim, start, config, run_id, agent)


def paused(claim: dict[str, Any], agent: ClaimAgent) -> bool:
    """Say whether the claim's work is paused for a handler's answer: an interrupt
    waits on its thread. The next step names the pause as soon as the step before
    it is saved, before the pause has run, so it isn't enough."""
    if claim["thread_id"] is None:
        return False
    return bool(agent.graph.get_state(thread_of(claim)).interrupts)


def resume(claim_id: str, agent: ClaimAgent) -> str:
    """Resume a paused claim with the handler's answer from the app's record, with
    no run, and report how it ended."""
    claim = api.get_claim(claim_id)
    start = Command(resume=handler_answer.answer_of(claim))
    return work_on(claim, start, claim_config(claim, RESUME, None, ()), None, agent)


def work_in_run(
    claim_id: str, run_id: str, new_agent: NewAgent, tags: Tags = ()
) -> str:
    """Work one claim in a run with a claim agent of its own, carrying it on if it
    is in progress, as a sent-back claim the run took is, or starting it if it is
    waiting, and report how it ended, with any tags for its trace beside the
    run's."""
    agent = new_agent()
    if api.get_claim(claim_id)["status"] == app_terms.Status.IN_PROGRESS:
        return carry_on(claim_id, run_id, agent, tags)
    return work_claim(claim_id, run_id, agent, tags)
