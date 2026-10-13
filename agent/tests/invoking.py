"""The agent's AgentCore app as the tests call it: through Starlette's TestClient, as
the app calls it on the laptop, with the agent's key."""

import os
import time
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


def key_headers() -> dict[str, str]:
    """The agent's key as the app sends it, read as the tests set it."""
    return {"Authorization": f"Bearer {os.environ['UNDERCOVER_API_KEY']}"}


class Agent:
    """The agent's AgentCore app, which waits after each request for the work it
    started, by asking its /ping until the app is no longer busy."""

    def __init__(self, client: TestClient) -> None:
        self.client = client

    def invoke(self, payload: Any, wait: bool = True, headers=None):
        """Post a payload to /invocations, with the agent's key unless other headers
        are given, and wait for its work unless told not to."""
        response = self.client.post(
            "/invocations",
            json=payload,
            headers=key_headers() if headers is None else headers,
        )
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
