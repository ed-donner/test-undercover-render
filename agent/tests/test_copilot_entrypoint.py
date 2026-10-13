"""The Copilot's AgentCore app: nothing happens as it's imported, it gets ready on
its first request, checks the sign-in and the turn with the app before it answers,
keeps one turn at a time for each conversation in its process, and works each turn
on a thread of its own, which its /ping reports as busy until it ends."""

import logging
import os
import random
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest

from agent import connection
from agent.copilot import turns
from agent.tests.copilot_driver import Copilot
from agent.tests.credentials import CREDENTIALS
from agent.tests.invoking import (
    ACCEPTED,
    HEALTH,
    SETTLE,
    answer_confirmation,
    take_turn,
)
from agent.tests.local_server import serving
from agent.tests.records import payments_of
from agent.tests.stubs import call, stub
from backend import copilot_service
from backend.tests.claim_requests import held
from backend.tests.copilot_requests import (
    answer,
    conversation_of,
    finish_turn,
    latest,
    send_message,
    start_conversation,
    started,
)
from backend.tests.sign_in import DANA, MARCUS, OTHER_KEY, bearer, token

ROOT = Path(__file__).resolve().parents[2]
# Imports the file Runtime starts for the Copilot with sockets that refuse to
# connect, and checks it started no thread.
IMPORT_IT = """
import socket, threading

def refuse(*args, **kwargs):
    raise ConnectionRefusedError("Nothing may connect as the Copilot is imported")

socket.socket.connect = refuse
socket.create_connection = refuse
threads = set(threading.enumerate())
import runtime.copilot
import agent.copilot.entrypoint
assert runtime.copilot.app is agent.copilot.entrypoint.app
assert set(threading.enumerate()) <= threads
"""


def test_importing_the_copilot_reads_no_setting_opens_nothing_and_starts_nothing():
    """In a process of its own with no settings but PATH and those the deployment
    gives on Runtime, as each Runtime session starts from a snapshot taken after
    import."""
    settings = {"PATH": os.environ["PATH"]} | {
        f"AGENTCORE_CREDENTIAL_{setting}_NAME": provider
        for setting, provider in CREDENTIALS.items()
    }
    if sys.platform == "win32":  # Windows can't start its sockets without it
        settings["SYSTEMROOT"] = os.environ["SYSTEMROOT"]
    imported = subprocess.run(  # noqa: S603 - the tests' own Python and code
        [sys.executable, "-c", IMPORT_IT],
        cwd=ROOT,
        env=settings,
        capture_output=True,
        text=True,
        check=False,
    )
    assert imported.returncode == 0, imported.stderr


def test_on_runtime_the_first_request_fetches_its_two_credentials_once(
    on_runtime, copilot_app, monkeypatch
):
    opened, reseeded = [], []
    app = copilot_app()
    monkeypatch.setattr(app.module, "open_checkpoint_pool", lambda: opened.append(1))
    monkeypatch.setattr(random, "seed", lambda: reseeded.append(opened.copy()))
    for setting in CREDENTIALS:
        monkeypatch.delenv(setting, raising=False)
    assert app.invoke(HEALTH).json() == {"healthy": True}
    assert sorted(on_runtime) == [
        CREDENTIALS["DATABASE_URL"],
        CREDENTIALS["OPENROUTER_API_KEY"],
    ]
    assert os.environ["OPENROUTER_API_KEY"] == "openrouter-key"
    assert "UNDERCOVER_API_KEY" not in os.environ
    assert (reseeded, opened) == ([[]], [1])
    assert app.invoke(HEALTH).json() == {"healthy": True}
    assert len(on_runtime) == 2
    assert opened == [1]


def test_a_failure_to_get_ready_answers_503_and_the_next_request_tries_again(
    copilot_app, monkeypatch
):
    def unreachable():
        raise ConnectionError("Supabase isn't answering")

    app = copilot_app()
    monkeypatch.setattr(app.module, "open_checkpoint_pool", unreachable)
    failed = app.invoke(HEALTH)
    assert (failed.status_code, failed.json()) == (
        503,
        {"error": "The Copilot couldn't get ready: ConnectionError: Supabase isn't "
         "answering"},
    )  # fmt: skip
    monkeypatch.setattr(app.module, "open_checkpoint_pool", object)
    assert app.invoke(HEALTH).json() == {"healthy": True}


class HeldTurns:
    """Holds each turn the Copilot works open until the test releases it."""

    def __init__(self) -> None:
        self.working = threading.Event()
        self.release = threading.Event()

    def take_turn(self, turn, saver):
        self.working.set()
        self.release.wait(SETTLE)
        return take(turn, saver)


take = turns.take_turn


@pytest.fixture
def held_turns(monkeypatch):
    held = HeldTurns()
    monkeypatch.setattr(turns, "take_turn", held.take_turn)
    yield held
    held.release.set()


class Requests:
    """The test backend, keeping each request the Copilot sends, with its
    headers."""

    def __init__(self, backend):
        self.backend = backend
        self.sent: list[tuple[str, str, dict[str, str]]] = []

    def request(self, method, path, headers, **request):
        self.sent.append((method, path, headers))
        return self.backend.request(method, path, headers=headers, **request)


def a_turn(copilot: Copilot, message="Hello", email=DANA):
    """A conversation's working turn the app asked the Copilot to take, as its
    payload."""
    started(copilot.dashboard, message, email)
    payload = copilot.last_payload()
    return take_turn(payload["conversation_id"], payload["turn_id"], payload["sign_in"])


def test_a_turn_is_checked_then_worked_in_the_background(
    copilot: Copilot, copilot_app, held_turns, monkeypatch
):
    sent = Requests(connection.backend)
    monkeypatch.setattr(connection, "backend", sent)
    copilot.model = stub("Hello, Dana.")
    app = copilot_app()
    payload = a_turn(copilot)
    assert app.invoke(payload, wait=False).json() == ACCEPTED
    conversation = f"/copilot/conversations/{payload['conversation_id']}"
    signed_in = {"Authorization": f"Bearer {payload['sign_in']}"}
    assert sent.sent[:2] == [
        ("GET", "/me", signed_in),
        ("GET", conversation, signed_in),
    ]
    assert held_turns.working.wait(SETTLE)
    assert app.ping() == "HealthyBusy"
    held_turns.release.set()
    app.settle()
    assert app.ping() == "Healthy"
    assert latest(copilot.read(payload["conversation_id"]))["answer"] == "Hello, Dana."


@pytest.mark.filterwarnings("error::pytest.PytestUnhandledThreadExceptionWarning")
def test_a_turn_that_raised_is_logged_and_its_conversation_goes_on(
    copilot: Copilot, copilot_app, monkeypatch, caplog
):
    def broken(turn, saver):
        raise RuntimeError("The app can't be reached")

    monkeypatch.setattr(turns, "take_turn", broken)
    app = copilot_app()
    payload = a_turn(copilot)
    assert app.invoke(payload).json() == ACCEPTED
    assert app.ping() == "Healthy"
    [logged] = [r for r in caplog.records if r.name == app.module.log.name]
    assert logged.getMessage() == f"Turn {payload['turn_id']} stopped"
    monkeypatch.setattr(turns, "take_turn", take)
    finish_turn(copilot.dashboard, payload["turn_id"])
    copilot.model = stub("Hello again.")
    send_message(copilot.dashboard, payload["conversation_id"], "Hello again")
    assert app.invoke(copilot.last_payload()).json() == ACCEPTED
    assert latest(copilot.read(payload["conversation_id"]))["answer"] == "Hello again."


def test_a_turn_it_wont_take(copilot: Copilot, copilot_app, held_turns):
    app = copilot_app()
    finished = a_turn(copilot)
    finish_turn(copilot.dashboard, finished["turn_id"])
    payload = a_turn(copilot)
    conversation_id, turn_id = payload["conversation_id"], payload["turn_id"]
    signed_out = take_turn(conversation_id, turn_id, token(DANA, key=OTHER_KEY))
    assert app.invoke(signed_out).json() == {
        "refused": "The sign-in isn't valid. Please sign in again."
    }
    marcus = take_turn(conversation_id, turn_id, token(MARCUS))
    assert app.invoke(marcus).json() == {
        "refused": f"Conversation {conversation_id} not found"
    }
    done = finished["turn_id"]
    not_working = take_turn(finished["conversation_id"], done, finished["sign_in"])
    assert app.invoke(not_working).json() == {
        "refused": f"Turn {done} isn't the conversation's latest working turn"
    }
    assert app.invoke(payload, wait=False).json() == ACCEPTED
    assert held_turns.working.wait(SETTLE)
    assert app.invoke(payload, wait=False).json() == {
        "refused": f"Conversation {conversation_id} already has a turn working"
    }
    copilot.model = stub("Hello.", "Hello again.")
    assert app.invoke(a_turn(copilot), wait=False).json() == ACCEPTED
    held_turns.release.set()
    app.settle()


UNKNOWN = (
    "Unknown operation: it must be one of 'health', 'take_turn', 'answer_confirmation'"
)
NOT_A_SIGN_IN = "sign_in: String should match pattern '^[A-Za-z0-9_.-]+$'"


@pytest.mark.parametrize(
    ("payload", "error"),
    [
        ({"operation": "dance-secret"}, UNKNOWN),
        ({"operation": "take_turn", "conversation_id": "c", "turn_id": "t"},
         "sign_in: Field required"),
        ({"operation": "take_turn", "conversation_id": "c", "turn_id": "t",
          "sign_in": "secret-token", "extra": "secret-value"},
         "extra: Extra inputs are not permitted"),
        ({"operation": "answer_confirmation", "conversation_id": "c",
          "turn_id": "t", "sign_in": 7},
         "sign_in: Input should be a valid string"),
        ({"operation": "take_turn", "conversation_id": "c", "turn_id": "t",
          "sign_in": "secret\r\nX-Injected: yes"},
         NOT_A_SIGN_IN),
    ],
)  # fmt: skip
def test_a_payload_it_cant_read_gets_a_400_without_its_values(
    copilot_app, payload, error
):
    refused = copilot_app().invoke(payload)
    assert (refused.status_code, refused.json()) == (400, {"error": error})
    assert "secret" not in refused.text


def test_an_answer_resumes_the_paused_conversation(
    client, copilot: Copilot, copilot_app
):
    held(client, "CLM-1003", 3750.0)
    copilot.model = stub(call("sign_off_claim", claim_id="CLM-1003"))
    app = copilot_app()
    assert app.invoke(a_turn(copilot, "Sign off CLM-1003")).json() == ACCEPTED
    conversation_id = copilot.last_payload()["conversation_id"]
    turn_id = latest(copilot.read(conversation_id))["turn_id"]
    copilot.model = stub("Signed off and paid.")
    copilot.answer_in_the_app(conversation_id, turn_id, "sign_off")
    payload = copilot.last_payload()
    assert payload["operation"] == "answer_confirmation"
    assert copilot_app().invoke(payload).json() == ACCEPTED
    assert latest(copilot.read(conversation_id))["answer"] == "Signed off and paid."
    assert len(payments_of("CLM-1003")) == 1


def test_an_answer_with_none_recorded_or_nothing_paused_is_refused(
    client, copilot: Copilot, copilot_app, monkeypatch
):
    app = copilot_app()
    payload = a_turn(copilot)
    early = answer_confirmation(
        payload["conversation_id"], payload["turn_id"], payload["sign_in"]
    )
    assert app.invoke(early).json() == {
        "refused": f"Turn {payload['turn_id']} has no answer to its confirmation yet"
    }
    held(client, "CLM-1003", 3750.0)
    copilot.model = stub(call("sign_off_claim", claim_id="CLM-1003"))
    app.invoke(a_turn(copilot, "Sign off CLM-1003"))
    conversation_id = copilot.last_payload()["conversation_id"]
    turn_id = latest(copilot.read(conversation_id))["turn_id"]
    copilot.answer_in_the_app(conversation_id, turn_id, "sign_off")
    elsewhere = copilot_app()
    monkeypatch.setattr(
        elsewhere.module, "saver_on", lambda pool: type(copilot.saver)()
    )
    assert elsewhere.invoke(copilot.last_payload()).json() == {
        "refused": "No sign-off is waiting for an answer in this conversation"
    }


def test_a_pause_in_one_process_is_answered_in_another(
    client, copilot: Copilot, copilot_app
):
    held(client, "CLM-1008", 2240.0)
    copilot.model = stub(call("sign_off_claim", claim_id="CLM-1008"))
    first = copilot_app()
    first.invoke(a_turn(copilot, "Sign off CLM-1008"))
    conversation_id = copilot.last_payload()["conversation_id"]
    turn_id = latest(copilot.read(conversation_id))["turn_id"]
    copilot.answer_in_the_app(conversation_id, turn_id, "sign_off")
    copilot.model = stub("Paid.")
    second = copilot_app()
    assert second.module is not first.module
    assert second.invoke(copilot.last_payload()).json() == ACCEPTED
    [payment] = payments_of("CLM-1008")
    assert payment["amount"] == 2240.0
    decision = client.get("/api/claims/CLM-1008").json()["decision"]
    assert decision["signed_off_by"] == "Dana Whitfield"


def ended(dashboard, conversation_id):
    """The conversation's latest turn, once the Copilot has stopped working on it."""
    deadline = time.monotonic() + SETTLE
    while (turn := latest(conversation_of(dashboard, conversation_id).json()))[
        "status"
    ] == "working":
        assert time.monotonic() < deadline, "The Copilot didn't end the turn"
        time.sleep(0.01)
    return turn


def test_the_app_and_the_copilot_on_the_laptop_end_to_end(
    client, copilot: Copilot, copilot_app, monkeypatch, caplog
):
    """The backend posts to the Copilot's AgentCore app on a local port, with no
    key, and the Copilot works each turn through the backend as the handler."""
    caplog.set_level(logging.DEBUG)
    dashboard = copilot.dashboard
    sent_headers = []
    real = httpx.Client(
        event_hooks={"request": [lambda request: sent_headers.append(request.headers)]}
    )
    monkeypatch.setattr(copilot_service, "copilot", real)
    app = copilot_app()
    held(client, "CLM-1008", 2240.0)
    own = token(DANA)
    with serving(app.module.app) as address:
        monkeypatch.setenv(copilot_service.COPILOT, address)
        copilot.model = stub("Nothing needs you.")
        started_one = start_conversation(dashboard, access_token=own)
        conversation_id = started_one.json()["conversation_id"]
        assert ended(dashboard, conversation_id)["answer"] == "Nothing needs you."
        copilot.model = stub(call("sign_off_claim", claim_id="CLM-1008"), "Paid.")
        headers = bearer(own)
        sent = dashboard.post(
            f"/api/copilot/conversations/{conversation_id}/messages",
            json={"message": "Sign off CLM-1008"},
            headers=headers,
        )
        assert sent.status_code == 202
        paused = ended(dashboard, conversation_id)
        assert paused["status"] == "waiting_for_confirmation"
        answer(dashboard, conversation_id, paused["turn_id"], "sign_off", headers)
        assert ended(dashboard, conversation_id)["answer"] == "Paid."
    assert [p["amount"] for p in payments_of("CLM-1008")] == [2240.0]
    decision = client.get("/api/claims/CLM-1008").json()["decision"]
    assert decision["signed_off_by"] == "Dana Whitfield"
    assert sent_headers
    for headers in sent_headers:
        assert "authorization" not in headers
        assert "x-api-key" not in headers
    assert [r for r in caplog.records if own in r.getMessage()] == []
