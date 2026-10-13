"""The agent's and the Copilot's AgentCore apps as the tests call them: through
Starlette's TestClient, as the app calls them on the laptop, the agent with its key
and the Copilot with none."""

import os
import time
from dataclasses import dataclass
from typing import Any

from starlette.testclient import TestClient

# How long the tests wait for the work a request starts.
SETTLE = 60
HEALTH = {"operation": "health"}
ACCEPTED = {"accepted": True}


def work_run(run_id: str) -> dict[str, Any]:
    return {"operation": "work_run", "run_id": run_id}


def work_round(round_id: str) -> dict[str, Any]:
    return {"operation": "work_round", "round_id": round_id}


def carry_round_on(round_id: str, proposal_id: str) -> dict[str, Any]:
    return {
        "operation": "carry_round_on",
        "round_id": round_id,
        "proposal_id": proposal_id,
    }


def resume_claim(claim_id: str) -> dict[str, Any]:
    return {"operation": "resume_claim", "claim_id": claim_id}


def take_turn(conversation_id: str, turn_id: str, sign_in: str) -> dict[str, Any]:
    return {
        "operation": "take_turn",
        "conversation_id": conversation_id,
        "turn_id": turn_id,
        "sign_in": sign_in,
    }


def answer_confirmation(
    conversation_id: str, turn_id: str, sign_in: str
) -> dict[str, Any]:
    return take_turn(conversation_id, turn_id, sign_in) | {
        "operation": "answer_confirmation"
    }


def key_headers() -> dict[str, str]:
    """The agent's key as the app sends it, read as the tests set it."""
    return {"Authorization": f"Bearer {os.environ['UNDERCOVER_API_KEY']}"}


@dataclass
class Agent:
    """An AgentCore app, which waits after each request for the work it started, by
    asking its /ping until the app is no longer busy."""

    client: TestClient
    with_key: bool = True

    def invoke(self, payload: Any, wait: bool = True, headers=None):
        """Post a payload to /invocations, with the agent's key if the app takes it,
        unless other headers are given, and wait for its work unless told not
        to."""
        if headers is None:
            headers = key_headers() if self.with_key else {}
        response = self.client.post("/invocations", json=payload, headers=headers)
        if wait:
            self.settle()
        return response

    def ping(self) -> str:
        return self.client.get("/ping").json()["status"]

    def settle(self) -> None:
        """Wait until no work is going on."""
        deadline = time.monotonic() + SETTLE
        while self.ping() != "Healthy":
            if time.monotonic() > deadline:
                raise TimeoutError("The agent's work didn't finish")
            time.sleep(0.01)
