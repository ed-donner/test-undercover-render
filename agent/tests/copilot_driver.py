"""The Copilot as the tests drive it: a handler sends a message, or answers a
confirmation, through the app as the sidebar does; the app asks the stand-in for the
Copilot, which keeps the payload; and the test has the Copilot work that turn as
its entry point would, with the sign-in the app passed on, on a stub model, saving
its state in memory."""

import time
from dataclasses import dataclass, field
from typing import Any

from fastapi.testclient import TestClient
from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.base import BaseStore
from langgraph.types import StateSnapshot

from agent.copilot import turns
from agent.copilot.graph import copilot_graph
from agent.tests.stubs import StubModel, stub
from backend.tests.copilot_requests import (
    answer,
    conversation_of,
    send_message,
    start_conversation,
)
from backend.tests.sign_in import DANA, signed_in

# How long a test waits for the Copilot to start a run.
WAIT_FOR_A_START = 10


@dataclass
class Copilot:
    """Drives turns through the app and the Copilot. Each turn builds its graph
    afresh on the same saver, as a fresh Copilot would, on the model and with the
    memory the test gives it."""

    dashboard: TestClient
    payloads: list[dict[str, Any]]
    model: StubModel = field(default_factory=stub)
    saver: InMemorySaver = field(default_factory=InMemorySaver)
    store: BaseStore | None = None

    def model_for(self, sign_in: str) -> BaseChatModel:
        return self.model

    def last_payload(self) -> dict[str, Any]:
        return self.payloads[-1]

    def turn(self) -> turns.Turn:
        """The turn the app last asked the Copilot to work, checked with the app."""
        payload = self.last_payload()
        return turns.the_turn(
            payload["sign_in"], payload["conversation_id"], payload["turn_id"]
        )

    def ask(self, message: str, conversation_id: str | None = None, email=DANA):
        """Send a message as a handler, in a new conversation or the one given,
        have the Copilot work the turn, and return the conversation."""
        if conversation_id is None:
            sent = start_conversation(self.dashboard, message, email)
        else:
            sent = send_message(self.dashboard, conversation_id, message, email)
        assert sent.status_code == 202, sent.json()
        turns.take_turn(self.turn(), self.saver)
        return self.read(self.last_payload()["conversation_id"], email)

    def answer(self, conversation_id: str, given: str, email=DANA):
        """Answer the conversation's confirmation as a handler, have the Copilot
        carry the turn on, and return the conversation."""
        turn_id = self.read(conversation_id, email)["turns"][-1]["turn_id"]
        self.answer_in_the_app(conversation_id, turn_id, given, email)
        self.carry_on()
        return self.read(conversation_id, email)

    def answer_in_the_app(self, conversation_id, turn_id, given, email=DANA) -> None:
        """Answer a turn's confirmation as a handler, which the app records."""
        answered = answer(
            self.dashboard, conversation_id, turn_id, given, signed_in(email)
        )
        assert answered.status_code == 202, answered.json()

    def carry_on(self) -> None:
        """Have the Copilot carry on the turn the app last asked about with the
        answer the app recorded."""
        turns.answer_confirmation(self.turn(), self.saver)

    def graph_state(self, conversation_id: str) -> StateSnapshot:
        """The conversation's graph's saved state."""
        graph = copilot_graph(stub(), self.saver, self.store)
        return graph.get_state(turns.thread_of(conversation_id))

    def read(self, conversation_id: str, email=DANA) -> dict[str, Any]:
        return conversation_of(self.dashboard, conversation_id, email).json()


def started_run(agent_calls: list[dict[str, Any]]) -> str:
    """The run the app last asked the agent to work, waiting for the app to ask."""
    deadline = time.monotonic() + WAIT_FOR_A_START
    while not (asked := [c for c in agent_calls if c["operation"] == "work_run"]):
        assert time.monotonic() < deadline, "No run was started"
        time.sleep(0.01)
    return asked[-1]["run_id"]
