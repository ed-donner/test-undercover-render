"""Waiting for the agent's work in code: the wait for a dispatch the Copilot started,
what needs a handler after it, and a run still going or stopped."""

import json
import threading
import time

import pytest

from agent import connection
from agent.copilot import waiting
from agent.tests.copilot_driver import Copilot, started_run
from agent.tests.stubs import call, stub
from backend.tests.claim_requests import decide, fail, held, pay, send_back, start
from backend.tests.run_requests import fail_run, finish, record_claims, run_path

SUMMARY = "CLM-1003 is held for your sign-off and CLM-1018 was referred."


@pytest.fixture(autouse=True)
def quick_waits(monkeypatch):
    """Read the run every hundredth of a second, for up to five seconds."""
    monkeypatch.setattr(waiting, "POLL", 0.01)
    monkeypatch.setattr(waiting, "WAIT", 5)


def wait_for_the_run(prompt):
    """The model's call to wait for the run its last tool started."""
    return call("wait_for_run", run_id=json.loads(prompt[-1].text)["run_id"])


class Reads:
    """The test backend, keeping each request the Copilot sends."""

    def __init__(self, backend):
        self.backend = backend
        self.sent: list[tuple[str, str, dict[str, str]]] = []

    def request(self, method, path, headers, **request):
        self.sent.append((method, path, headers))
        return self.backend.request(method, path, headers=headers, **request)


def test_the_wait_for_a_dispatch(client, copilot: Copilot, agent_calls, monkeypatch):
    reads = Reads(connection.backend)
    monkeypatch.setattr(connection, "backend", reads)
    working = []

    def play_the_dispatch_out():
        run_id = started_run(agent_calls)
        record_claims(client, run_id, "CLM-1003", "CLM-1018")
        while not [s for _, s, _ in reads.sent if s == f"/runs/{run_id}"]:
            time.sleep(0.01)
        conversation = copilot.read(copilot.last_payload()["conversation_id"])
        working.append(conversation["turns"][-1]["steps"][-1])
        held(client, "CLM-1003", 3750.0)
        start(client, "CLM-1018")
        decide(client, "CLM-1018", "refer", 0)
        finish(client, run_id)

    dispatch = threading.Thread(target=play_the_dispatch_out)
    dispatch.start()
    copilot.model = stub(call("start_dispatch", agents=10), wait_for_the_run, SUMMARY)
    [turn] = copilot.ask("Work the queue with 10 agents and tell me what needs me")[
        "turns"
    ]
    dispatch.join(10)
    [card] = working
    assert (card["tool"], card["status"]) == ("wait_for_run", "working")
    assert [(c["tool"], c["status"]) for c in turn["steps"]] == [
        ("start_dispatch", "done"),
        ("wait_for_run", "done"),
    ]
    assert (turn["answer"], turn["model_calls"]) == (SUMMARY, 3)
    went = json.loads(copilot.model.prompts[2][-1].text)
    assert went["status"] == "finished"
    assert went["summary"]["waiting_for_sign_off"] == [
        {"claim_id": "CLM-1003", "payout": 3750.0}
    ]
    assert went["needs_a_handler"] == {
        "held_for_sign_off": [{"claim_id": "CLM-1003", "payout": 3750.0}],
        "referred": ["CLM-1018"],
        "left_for_a_handler": [],
        "sent_back_not_taken_up": [],
    }
    run_reads = [h for _, path, h in reads.sent if path.startswith("/runs/")]
    assert len(run_reads) > 1
    sign_in = copilot.last_payload()["sign_in"]
    assert all(h == {"Authorization": f"Bearer {sign_in}"} for h in run_reads)


def test_what_needs_a_handler(client, copilot: Copilot):
    held(client, "CLM-1008", 2240.0)
    send_back(client, "CLM-1008")
    for _ in range(2):
        start(client, "CLM-1001")
        fail(client, "CLM-1001")
    start(client, "CLM-1002")
    decide(client, "CLM-1002", "approve", 420.0)
    pay(client, "CLM-1002", 420.0)
    copilot.model = stub(call("what_needs_a_handler"), "Two claims need you.")
    [turn] = copilot.ask("What needs me today?")["turns"]
    assert [(c["tool"], c["kind"]) for c in turn["steps"]] == [
        ("what_needs_a_handler", "claims")
    ]
    assert json.loads(copilot.model.prompts[1][-1].text) == {
        "held_for_sign_off": [],
        "referred": [],
        "left_for_a_handler": ["CLM-1001"],
        "sent_back_not_taken_up": ["CLM-1008"],
    }


def test_a_run_still_going_and_a_run_that_stopped(
    client, copilot: Copilot, agent_calls, monkeypatch
):
    monkeypatch.setattr(waiting, "WAIT", 0.05)
    copilot.model = stub(call("start_dispatch", agents=10), wait_for_the_run, "Still.")
    conversation_id = copilot.ask("Work the queue")["conversation_id"]
    went = json.loads(copilot.model.prompts[2][-1].text)
    assert went["status"] == "running"
    assert went["note"].endswith("Follow it on the queue page.")
    run_id = started_run(agent_calls)
    fail_run(client, run_id, "RuntimeError: The dispatcher broke")
    copilot.model = stub(call("wait_for_run", run_id=run_id), "It stopped.")
    copilot.ask("How did it go?", conversation_id)
    went = json.loads(copilot.model.prompts[1][-1].text)
    assert (went["status"], went["stopped_because"]) == (
        "stopped",
        "RuntimeError: The dispatcher broke",
    )


def test_the_wait_for_an_evaluation_gives_its_measures(
    client, copilot: Copilot, agent_calls
):
    def play_the_evaluation_out():
        run_id = started_run(agent_calls)
        for copy in client.get(run_path(run_id)).json()["claims"]:
            start(client, copy["claim_id"])
            decide(client, copy["claim_id"], "refer", 0)
        finish(client, run_id)

    evaluation = threading.Thread(target=play_the_evaluation_out)
    evaluation.start()
    copilot.model = stub(
        call("start_evaluation", evaluation_set="held_out", tiny=True, agents=5),
        wait_for_the_run,
        "Done.",
    )
    copilot.ask("Evaluate the held-out set's tiny claims")
    evaluation.join(10)
    went = json.loads(copilot.model.prompts[2][-1].text)
    assert (went["kind"], went["status"]) == ("evaluation", "finished")
    assert went["measures"]["straight_through"] == 0
