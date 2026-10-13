"""The dispatcher: a LangGraph graph with no model that works a dispatch or an
evaluation, handing each claim to a claim agent of its own, up to N at once."""

import logging
import operator
from collections.abc import Callable
from dataclasses import dataclass
from http import HTTPStatus
from typing import Annotated, Any, TypedDict, cast

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import ExecutionInfo, Runtime
from langgraph.types import RetryPolicy, Send

from agent import api, harness
from agent.connection import Refused
from agent.console import describe
from agent.root_run import as_root_run

log = logging.getLogger(__name__)

LIST_CLAIMS = "list_claims"
WORK_CLAIM = "work_claim"
FINISH_RUN = "finish_run"
TO_WORK = (api.Status.IN_PROGRESS, api.Status.WAITING, api.Status.SENT_BACK)
TAKEN_BY_A_RESUME = "{claim_id}  taken by a resume"

# A rate limit or a timeout waits about 10 seconds, then about 20, on top of the
# model client's own retries, and carries the claim on from its last saved step.
RETRY = RetryPolicy(max_attempts=3, initial_interval=10, retry_on=harness.TRANSIENT)


class Dispatch(TypedDict):
    """What the dispatcher keeps for one run: the claims to work, and a report line
    for each, added together as the claim agents finish."""

    claims: list[str]
    reports: Annotated[list[str], operator.add]


class ClaimToWork(TypedDict):
    """What the dispatcher sends a claim agent: the claim it works."""

    claim_id: str


# Works one claim in a run, given the claim's id and the run's, and reports how it
# ended: the harness's work_in_run, bound to how its claim agents are built.
WorkInRun = Callable[[str, str], str]

# How a claim still failing after its tries is left, by the kind of run.
LEFT = {api.DISPATCH: "left for the next dispatch", api.EVALUATION: "left in progress"}


@dataclass
class DispatchContext:
    """The run being worked, and how to work one of its claims."""

    run: dict[str, Any]
    work: WorkInRun


Dispatcher = CompiledStateGraph[Dispatch, DispatchContext, Any, Any]


def list_claims(state: Dispatch, runtime: Runtime[DispatchContext]) -> dict[str, Any]:
    """Choose the claims to work: an evaluation's copies, which the backend made, or
    the queue's claims in progress, waiting and sent back, oldest submitted first,
    which the dispatch records. It leaves out a claim a resume is working on, and
    takes each sent-back claim as it lists it, so a resume can't take it
    afterwards; one a resume took first is reported and left out."""
    run = runtime.context.run
    if run["kind"] == api.EVALUATION:
        return {"claims": [claim["claim_id"] for claim in run["claims"]]}
    queue = sorted(api.list_claims(), key=lambda c: (c["submitted_on"], c["claim_id"]))
    claims, reports = [], []
    for claim in queue:
        if claim["status"] not in TO_WORK or claim["resuming"]:
            continue
        claim_id = claim["claim_id"]
        if claim["status"] == api.Status.SENT_BACK and not took(claim_id, run):
            reports.append(TAKEN_BY_A_RESUME.format(claim_id=claim_id))
        else:
            claims.append(claim_id)
    api.record_run_claims(run["run_id"], claims)
    return {"claims": claims, "reports": reports}


def took(claim_id: str, run: dict[str, Any]) -> bool:
    """Take a sent-back claim for the run, and say whether the run got it rather
    than a resume."""
    try:
        api.take_claim(claim_id, run["run_id"])
    except Refused as refusal:
        if refusal.status_code != HTTPStatus.CONFLICT:
            raise
        log.info(TAKEN_BY_A_RESUME.format(claim_id=claim_id))
        return False
    return True


def fan_out(state: Dispatch) -> list[Send] | str:
    """Send each claim to a claim agent of its own, or finish a run with none."""
    sends = [Send(WORK_CLAIM, ClaimToWork(claim_id=c)) for c in state["claims"]]
    return sends or FINISH_RUN


def hand_over(claim_id: str, context: DispatchContext) -> str:
    """Hand a claim to the claim agent, and once more if its first attempt failed and
    put it back in the queue."""
    run_id = context.run["run_id"]
    report = context.work(claim_id, run_id)
    if api.get_claim(claim_id)["status"] == api.Status.WAITING:
        report = context.work(claim_id, run_id)
    return report


def work_claim(state: ClaimToWork, runtime: Runtime[DispatchContext]) -> dict[str, Any]:
    """Work one claim. A rate limit or a timeout goes to the RetryPolicy, which waits
    and carries the claim on, until the last try leaves it in progress. No error
    stops the dispatch."""
    claim_id = state["claim_id"]
    try:
        report = hand_over(claim_id, runtime.context)
    except Exception as error:
        # LangGraph sets the execution info in every node.
        attempt = cast(ExecutionInfo, runtime.execution_info).node_attempt
        if isinstance(error, harness.TRANSIENT) and attempt < RETRY.max_attempts:
            raise
        left = LEFT[runtime.context.run["kind"]]
        report = f"{claim_id}  {left}: {describe(error)}"
        log.warning(report)
    return {"reports": [report]}


def finish_run(state: Dispatch, runtime: Runtime[DispatchContext]) -> None:
    """Finish the run once every claim has been handed over and come back."""
    api.finish_run(runtime.context.run["run_id"])


def dispatcher() -> Dispatcher:
    """Build the dispatcher's graph."""
    builder = StateGraph(Dispatch, context_schema=DispatchContext)
    builder.add_node(LIST_CLAIMS, list_claims)
    builder.add_node(WORK_CLAIM, work_claim, retry_policy=RETRY)
    builder.add_node(FINISH_RUN, finish_run)
    builder.add_edge(START, LIST_CLAIMS)
    builder.add_conditional_edges(LIST_CLAIMS, fan_out, [WORK_CLAIM, FINISH_RUN])
    builder.add_edge(WORK_CLAIM, FINISH_RUN)
    builder.add_edge(FINISH_RUN, END)
    return builder.compile()


def work_run(run: dict[str, Any], work: WorkInRun) -> list[str]:
    """Work a dispatch or an evaluation with up to its N claim agents at once, and
    return each claim's report line."""
    context = DispatchContext(run, work)
    config: RunnableConfig = {"max_concurrency": run["agents"]}
    state = as_root_run(
        dispatcher().invoke, {"claims": [], "reports": []}, config, context=context
    )
    return state["reports"]
