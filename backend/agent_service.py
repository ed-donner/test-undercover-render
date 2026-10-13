"""The agent, as the app calls it: one JSON payload for each operation, posted to its
AgentCore app on the laptop, with the agent's key, or sent to its runtime on
AgentCore Runtime, in a session of its own, when UNDERCOVER_AGENT_RUNTIME names one.
Each answer says whether the agent took the work."""

import os
import uuid

import httpx

from backend import runtime_calls
from backend.api_key import the_agents_key
from backend.runtime_calls import Payload, Wording

AGENT = "UNDERCOVER_AGENT"
# The agent's AgentCore app on the laptop, as npm run dev serves it.
LOCAL_AGENT = "http://127.0.0.1:8080"
RUNTIME = "UNDERCOVER_AGENT_RUNTIME"
NOT_RUNNING = "The agent's service isn't running"
NO_ANSWER = (
    "The agent's service didn't answer in time. Reload the page to see whether "
    "it went through."
)
COULDNT_TAKE = "The agent couldn't take the work: {reason}"
WORDING = Wording(NOT_RUNNING, COULDNT_TAKE, NO_ANSWER)

agent = httpx.Client()


def ask(payload: Payload) -> None:
    """Ask the agent to take some work, on Runtime in a new session when
    UNDERCOVER_AGENT_RUNTIME names its runtime, read now, or else on the laptop at
    UNDERCOVER_AGENT, with the agent's key. Raise NotTaken or MayHaveStarted when
    it didn't, or may not have."""
    if arn := os.getenv(RUNTIME):
        runtime_calls.invoke(arn, str(uuid.uuid4()), payload, WORDING)
    else:
        url = os.getenv(AGENT, LOCAL_AGENT)
        headers = {"Authorization": f"Bearer {the_agents_key()}"}
        runtime_calls.post(agent, url, payload, headers, WORDING)


def work_run(run_id: str) -> None:
    """Ask the agent to work a dispatch or an evaluation the app created."""
    ask({"operation": "work_run", "run_id": run_id})


def work_round(round_id: str) -> None:
    """Ask the agent to work a round of the improver the app created."""
    ask({"operation": "work_round", "round_id": round_id})


def carry_round_on(round_id: str, proposal_id: str) -> None:
    """Ask the agent to carry a round on after the review the app recorded."""
    ask(
        {
            "operation": "carry_round_on",
            "round_id": round_id,
            "proposal_id": proposal_id,
        }
    )


def resume_claim(claim_id: str) -> None:
    """Ask the agent to resume a paused claim with its handler's answer, which it
    reads from the claim."""
    ask({"operation": "resume_claim", "claim_id": claim_id})
