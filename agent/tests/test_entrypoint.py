"""The agent's AgentCore app: it gets ready on its first request, reads each payload,
checks the key off Runtime, and starts each operation's work on a thread of its own,
which its /ping reports as busy until it ends."""

import importlib
import os
import random
import socket
import sys
import threading
import time
from functools import partial
from typing import cast

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from agent import (
    api,
    checkpoints,
    entrypoint,
    harness,
    heartbeat,
    improver_api,
    work,
)
from agent.tests.credentials import CREDENTIALS
from agent.tests.dispatching import (
    new_dispatch,
    new_evaluation,
)
from agent.tests.held import StopAtThePause, hold, resume_claim
from agent.tests.invoking import (
    ACCEPTED,
    HEALTH,
    carry_round_on,
    work_round,
    work_run,
)
from agent.tests.queue_setup import leave_waiting
from agent.tests.records import claim_of, model_calls_of, work_times_of
from agent.tests.stubs import agent_on, approve, decide, stub, swarm
from backend.tests.claim_requests import sign_off
from backend.tests.dashboard_reads import evaluations
from backend.tests.round_requests import (
    create_round,
    fail_round,
    propose_change,
    round_path,
)
from backend.tests.run_requests import (
    another_running_dispatch,
    latest_dispatch,
    run_path,
)
from backend.tests.versions import add_version


def refuse(*args, **kwargs):
    raise ConnectionRefusedError("Nothing may connect as the agent is imported")


def test_importing_the_agent_reads_no_setting_opens_nothing_and_starts_nothing(
    monkeypatch,
):
    for name in list(os.environ):
        if name != "PATH":
            monkeypatch.delenv(name)
    for setting, provider in CREDENTIALS.items():
        monkeypatch.setenv(f"AGENTCORE_CREDENTIAL_{setting}_NAME", provider)
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    for name in list(sys.modules):
        if name.split(".")[0] in ("agent", "runtime"):
            monkeypatch.delitem(sys.modules, name)
    threads = set(threading.enumerate())

    main = importlib.import_module("runtime.main")
    assert main.app is sys.modules["agent.entrypoint"].app
    assert set(threading.enumerate()) <= threads


def test_on_runtime_the_first_request_fetches_each_credential_once(
    on_runtime, workers_from, fresh_agent, monkeypatch, agent_key
):
    opened, reseeded = [], []
    workers_from(stub(), InMemorySaver(), stub())
    monkeypatch.setattr(entrypoint, "open_checkpoint_pool", lambda: opened.append(1))
    monkeypatch.setattr(random, "seed", lambda: reseeded.append(opened.copy()))
    for setting in CREDENTIALS:
        monkeypatch.delenv(setting, raising=False)

    agent = fresh_agent()
    assert agent.invoke(HEALTH, headers={}).json() == {"healthy": True}
    assert sorted(on_runtime) == sorted(CREDENTIALS.values())
    assert os.environ["UNDERCOVER_API_KEY"] == agent_key
    assert os.environ["OPENROUTER_API_KEY"] == "openrouter-key"
    assert os.environ["DATABASE_URL"] == ""
    assert (reseeded, opened) == ([[]], [1])

    assert agent.invoke(HEALTH, headers={}).json() == {"healthy": True}
    assert len(on_runtime) == 3
    assert opened == [1]


def test_on_runtime_a_request_needs_no_key(on_runtime, serve):
    leave_waiting()
    agent = serve(stub())
    accepted = agent.invoke(work_run(new_dispatch()["run_id"]), headers={})
    assert (accepted.status_code, accepted.json()) == (200, ACCEPTED)


def test_a_failure_to_get_ready_answers_503_and_the_next_request_tries_again(
    workers_from, fresh_agent, monkeypatch
):
    workers_from(stub(), InMemorySaver(), stub())

    def unreachable():
        raise ConnectionError("Supabase isn't answering")

    monkeypatch.setattr(entrypoint, "open_checkpoint_pool", unreachable)
    agent = fresh_agent()
    failed = agent.invoke(HEALTH)
    assert (failed.status_code, failed.json()) == (
        503,
        {"error": "The agent couldn't get ready: ConnectionError: Supabase isn't "
         "answering"},
    )  # fmt: skip
    monkeypatch.setattr(entrypoint, "open_checkpoint_pool", object)
    assert agent.invoke(HEALTH).json() == {"healthy": True}


def test_getting_ready_needs_the_agents_key(workers_from, fresh_agent, monkeypatch):
    workers_from(stub(), InMemorySaver(), stub())
    monkeypatch.delenv("UNDERCOVER_API_KEY")
    failed = fresh_agent().invoke(HEALTH, headers={})
    assert failed.status_code == 503
    assert "UNDERCOVER_API_KEY is missing" in failed.json()["error"]


def test_the_health_check_needs_no_key(serve):
    agent = serve(stub())
    healthy = agent.invoke(HEALTH, headers={})
    assert (healthy.status_code, healthy.json()) == (200, {"healthy": True})


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer not-the-key"}, {"Authorization": "the-key"}],
)
def test_off_runtime_a_request_without_the_key_is_refused(client, serve, headers):
    agent = serve(stub())
    run_id = new_dispatch()["run_id"]
    refused = agent.invoke(work_run(run_id), headers=headers)
    assert (refused.status_code, refused.json()) == (
        401,
        {"error": "This needs the agent's API key"},
    )
    assert latest_dispatch(client)["claims"] == []


def test_off_runtime_a_payload_it_cant_read_without_the_key_is_refused(serve):
    refused = serve(stub()).invoke({"operation": "dance"}, headers={})
    assert (refused.status_code, refused.json()) == (
        401,
        {"error": "This needs the agent's API key"},
    )


UNKNOWN = (
    "Unknown operation: it must be one of 'health', 'work_run', 'work_round', "
    "'carry_round_on', 'resume_claim'"
)


@pytest.mark.parametrize(
    ("payload", "error"),
    [
        ({"operation": "dance"}, UNKNOWN),
        ({"operation": "start_dispatch", "agents": 3}, UNKNOWN),
        ({"run_id": "run-1"}, "The payload names no operation"),
        ([{"operation": "health"}], "The payload isn't a JSON object"),
        ({"operation": "work_run"}, "run_id: Field required"),
        ({"operation": "work_run", "run_id": 7}, "run_id: Input should be a valid "
         "string"),
        (
            {"operation": "work_run", "run_id": "run-1", "agents": 3},
            "agents: Extra inputs are not permitted",
        ),
        ({"operation": "carry_round_on", "round_id": "round-1"}, "proposal_id: "
         "Field required"),
        ({"operation": "resume_claim"}, "claim_id: Field required"),
    ],
)  # fmt: skip
def test_a_payload_it_cant_read_gets_a_400_saying_why(serve, payload, error):
    refused = serve(stub()).invoke(payload)
    assert (refused.status_code, refused.json()) == (400, {"error": error})
    assert "dance" not in refused.text


def test_work_a_dispatch_the_app_created(client, serve):
    ids = ["CLM-1001", "CLM-1003", "CLM-1004"]
    leave_waiting(*ids)
    model = swarm({claim_id: decide("refer", 0) for claim_id in ids}, pause=0.05)
    agent = serve(model)
    response = agent.invoke(work_run(new_dispatch(2)["run_id"]))
    assert (response.status_code, response.json()) == (200, ACCEPTED)

    dispatch = latest_dispatch(client)
    assert (dispatch["status"], dispatch["agents"]) == ("finished", 2)
    assert (dispatch["version"], dispatch["model"]) == (1, "openai/gpt-6-luna")
    assert [c["status"] for c in dispatch["claims"]] == ["decided"] * 3
    assert model.most_at_once == 2


TINY_HELD_OUT = ["CLM-1104", "CLM-1106", "CLM-1110", "CLM-1112", "CLM-1114"]


def test_work_an_evaluation_the_app_created(client, serve):
    model = swarm({f"{c}-E1": decide("refer", 0) for c in TINY_HELD_OUT})
    agent = serve(model)
    assert agent.invoke(work_run(new_evaluation()["run_id"])).json() == ACCEPTED
    [evaluation] = evaluations(client)
    assert (evaluation["status"], evaluation["size"], evaluation["agents"]) == (
        "finished",
        5,
        5,
    )


def test_ping_is_busy_while_work_goes_on_and_healthy_once_it_ends(
    client, serve, held_run
):
    leave_waiting()
    agent = serve(stub())
    assert agent.ping() == "Healthy"
    run_id = new_dispatch()["run_id"]
    assert agent.invoke(work_run(run_id), wait=False).json() == ACCEPTED
    assert held_run.working.wait(5)
    assert agent.ping() == "HealthyBusy"
    held_run.release.set()
    agent.settle()
    assert latest_dispatch(client)["status"] == "finished"


@pytest.mark.filterwarnings("error::pytest.PytestUnhandledThreadExceptionWarning")
def test_a_resume_that_raised_is_logged_and_its_task_completed(
    client, serve, monkeypatch, caplog
):
    saver = InMemorySaver()
    hold(saver=saver)
    sign_off(client, "CLM-1003")
    raised = threading.Event()

    def broken(claim_id, agent):
        raised.set()
        raise RuntimeError("The backend is unreachable")

    monkeypatch.setattr(work, "resume", broken)
    agent = serve(stub(), saver)
    # Its answer waits until /ping says Healthy, once the task is completed.
    assert resume_claim(agent, "CLM-1003").json() == ACCEPTED
    assert raised.is_set()
    [logged] = [r for r in caplog.records if r.name == work.log.name]
    assert logged.getMessage() == "The resume of CLM-1003 stopped"
    assert "The backend is unreachable" in str(logged.exc_info[1])


def test_the_agent_keeps_no_one_at_a_time_itself(client, serve, held_run):
    leave_waiting()
    agent = serve(stub())
    first = new_dispatch()["run_id"]
    second = another_running_dispatch()
    assert agent.invoke(work_run(first), wait=False).json() == ACCEPTED
    assert held_run.working.wait(5)
    assert agent.invoke(work_run(second), wait=False).json() == ACCEPTED
    held_run.release.set()
    agent.settle()
    for run_id in (first, second):
        assert client.get(f"/api/runs/{run_id}").json()["status"] == "finished"


def test_work_run_refuses_a_run_that_isnt_running(client, serve):
    agent = serve(stub())
    run_id = new_dispatch()["run_id"]
    client.post(f"/api/runs/{run_id}/finish")
    refused = agent.invoke(work_run(run_id))
    assert refused.json() == {"refused": f"Run {run_id} isn't running"}
    unknown = agent.invoke(work_run("run-9"))
    assert unknown.json() == {"refused": "Run run-9 not found"}


def test_work_round_refuses_a_round_that_isnt_open(client, serve):
    agent = serve(stub())
    round_id = create_round(client).json()["round_id"]
    fail_round(client, round_id, "Broken")
    refused = agent.invoke(work_round(round_id))
    assert refused.json() == {"refused": "Round 1 isn't open"}
    assert agent.invoke(carry_round_on(round_id, "p-1")).json() == {
        "refused": "Round 1 isn't open"
    }


def test_carry_round_on_refuses_a_proposal_with_no_review(client, serve):
    agent = serve(stub())
    round_id = create_round(client).json()["round_id"]
    proposal = propose_change(client, round_id).json()["proposal_id"]
    refused = agent.invoke(carry_round_on(round_id, proposal))
    assert refused.json() == {"refused": f"Proposal {proposal} has no review"}


def test_a_dispatch_whose_dispatcher_fails_is_stopped_by_its_id(
    client, serve, monkeypatch
):
    round_id = create_round(client).json()["round_id"]
    propose_change(client, round_id)

    def broken(run, work):
        raise RuntimeError("The backend is unreachable")

    monkeypatch.setattr(work, "work_run", broken)
    agent = serve(stub())
    failed = new_dispatch()["run_id"]
    beside = another_running_dispatch()
    assert agent.invoke(work_run(failed)).json() == ACCEPTED
    stopped = client.get(f"/api/runs/{failed}").json()
    assert (stopped["status"], stopped["stopped_because"]) == (
        "stopped",
        "RuntimeError: The backend is unreachable",
    )
    assert client.get(run_path(beside)).json()["status"] == "running"
    assert client.get(round_path(round_id)).json()["status"] == "open"


def test_a_run_whose_context_layer_isnt_answering_stops_with_one_line(
    client, serve, caplog
):
    agent = serve(stub())

    def down(version, kind):
        raise ConnectionError("The context layer isn't answering at http://x/mcp")

    entrypoint.ready.get().claim_agents = down
    assert agent.invoke(work_run(new_dispatch()["run_id"])).json() == ACCEPTED
    assert latest_dispatch(client)["stopped_because"] == (
        "ConnectionError: The context layer isn't answering at http://x/mcp"
    )
    assert "The run stopped: The context layer isn't answering at http://x/mcp" in (
        caplog.messages
    )


def test_getting_ready_stops_nothing(client, workers_from, fresh_agent):
    run_id = new_dispatch()["run_id"]
    workers_from(stub(), InMemorySaver(), stub())
    fresh_agent().invoke(HEALTH)
    dispatch = latest_dispatch(client)
    assert (dispatch["run_id"], dispatch["status"]) == (run_id, "running")


def test_a_dispatch_works_on_the_version_the_app_gave_it(client, serve):
    add_version("Version 2's instructions", verdict="kept")
    leave_waiting("CLM-1001")
    model = swarm({"CLM-1001": decide("refer", 0)})
    assert serve(model).invoke(work_run(new_dispatch()["run_id"])).json() == ACCEPTED

    dispatch = latest_dispatch(client)
    assert (dispatch["version"], dispatch["model"], dispatch["reasoning_effort"]) == (
        2,
        "google/gemini-3.5-flash-lite",
        "minimal",
    )
    version_2 = client.get("/api/versions/2").json()["instructions"]
    assert version_2.startswith("Version 2's instructions\n")
    assert [prompt[0].content for prompt in model.prompts] == [version_2] * 2


def test_a_run_keeps_its_version_when_another_is_kept_meanwhile(client, serve):
    leave_waiting("CLM-1001")
    run_id = new_dispatch()["run_id"]
    add_version("Version 2's instructions", verdict="kept")
    model = swarm({"CLM-1001": decide("refer", 0)})
    assert serve(model).invoke(work_run(run_id)).json() == ACCEPTED
    version_1 = client.get("/api/versions/1").json()["instructions"]
    assert [prompt[0].content for prompt in model.prompts] == [version_1] * 2


def test_the_workers_are_built_on_the_processs_pool(monkeypatch):
    pool = cast(checkpoints.Pool, object())
    monkeypatch.setattr(
        entrypoint, "claim_graphs", lambda version, kind, pool: (version, kind, pool)
    )
    monkeypatch.setattr(entrypoint, "PostgresSaver", lambda on: ("saver", on))
    workers = entrypoint.workers_on(pool)
    assert workers.claim_agents({"number": 2}, "evaluation") == (
        {"number": 2},
        "evaluation",
        pool,
    )
    assert workers.saver == ("saver", pool)


@pytest.fixture
def heard(monkeypatch):
    """Beat every hundredth of a second, keeping each piece of work the app heard
    of."""
    monkeypatch.setattr(heartbeat, "INTERVAL", 0.01)
    told = []
    for module, name in (
        (api, "record_run_heartbeat"),
        (api, "record_claim_heartbeat"),
        (improver_api, "record_round_heartbeat"),
    ):
        real = getattr(module, name)

        def tell(work_id, real=real):
            told.append(work_id)
            return real(work_id)

        monkeypatch.setattr(module, name, tell)
    return told


def heard_while_working(agent, held, heard, payload):
    """Start some work, held open, and say how often the app heard of it while it
    went on, then make sure it hears nothing once the work has ended."""
    assert agent.invoke(payload, wait=False).json() == ACCEPTED
    assert held.working.wait(5)
    time.sleep(0.1)
    while_working = len(heard)
    held.release.set()
    agent.settle()
    after = len(heard)
    time.sleep(0.05)
    assert len(heard) == after
    return while_working


def test_the_app_hears_from_a_run_while_it_works(client, serve, held_run, heard):
    leave_waiting()
    run_id = new_dispatch()["run_id"]
    assert heard_while_working(serve(stub()), held_run, heard, work_run(run_id)) > 2
    assert set(heard) == {run_id}


def test_the_app_hears_from_a_round_while_it_works(client, serve, held_run, heard):
    round_id = create_round(client).json()["round_id"]
    agent = serve(stub())
    entrypoint.ready.get().improver_model = lambda round: stub("No change.")
    assert heard_while_working(agent, held_run, heard, work_round(round_id)) > 2
    assert set(heard) == {round_id}


def test_the_app_hears_from_a_resume_while_it_works(client, serve, monkeypatch, heard):
    saver = InMemorySaver()
    hold(saver=saver)
    sign_off(client, "CLM-1003")
    held = HeldWork()
    monkeypatch.setattr(work, "resume", held.work)
    agent = serve(stub(), saver)
    payload = {"operation": "resume_claim", "claim_id": "CLM-1003"}
    assert heard_while_working(agent, held, heard, payload) > 2
    assert set(heard) == {"CLM-1003"}


class HeldWork:
    """Work held open until the test releases it."""

    def __init__(self):
        self.working, self.release = threading.Event(), threading.Event()

    def work(self, *args):
        self.working.set()
        self.release.wait(5)


def built_on(saver, built):
    """Claim agents on a stub model, sharing a saver, that keep the version and the
    kind of run each was built for."""

    def claim_agents(version, kind):
        built.append((version["number"], kind))
        return partial(agent_on, stub(), saver, version)

    return claim_agents


def test_a_signed_off_claim_is_resumed_in_the_background(client, serve):
    add_version("Version 2's instructions", verdict="kept")
    saver = InMemorySaver()
    hold(saver=saver)
    sign_off(client, "CLM-1003")
    calls, times = model_calls_of("CLM-1003"), work_times_of("CLM-1003")
    agent, built = serve(stub(), saver), []
    entrypoint.ready.get().claim_agents = built_on(saver, built)
    response = resume_claim(agent, "CLM-1003")
    assert (response.status_code, response.json()) == (200, ACCEPTED)
    assert built == [(2, None)]
    claim = claim_of(client, "CLM-1003")
    assert claim["status"] == "decided"
    assert not harness.paused(claim, agent_on(stub(), saver))
    assert work_times_of("CLM-1003")[: len(times)] == times
    [resumed] = work_times_of("CLM-1003")[len(times) :]
    assert resumed["run_id"] is None
    # A sign-off has already paid the claim, so the resume calls no model.
    assert model_calls_of("CLM-1003") == calls


def test_resume_claim_refuses_a_claim_that_isnt_paused_with_an_answer(client, serve):
    saver = StopAtThePause()
    with pytest.raises(KeyboardInterrupt):
        hold("CLM-1002", 1350.0, saver)
    sign_off(client, "CLM-1002")
    hold(saver=saver)
    harness.work_claim("CLM-1001", None, agent_on(stub(*decide("decline", 0)), saver))
    run_id = new_evaluation("evaluation")["run_id"]
    copy = agent_on(stub(*approve("CLM-1020", 1240.0)), saver, pauses=False)
    harness.work_in_run("CLM-1020-E1", run_id, lambda: copy)

    agent = serve(stub(), saver)
    for claim_id, reason in [
        ("CLM-1003", "Claim CLM-1003 has no answer from a handler yet"),
        ("CLM-1001", "Claim CLM-1001 isn't paused for a handler"),
        ("CLM-1020-E1", "Claim CLM-1020-E1 isn't paused for a handler"),
        ("CLM-1002", "Claim CLM-1002 isn't paused for a handler"),
        ("CLM-9999", "Claim CLM-9999 not found"),
    ]:
        refused = resume_claim(agent, claim_id)
        assert (refused.status_code, refused.json()) == (200, {"refused": reason})
    assert claim_of(client, "CLM-1003")["status"] == "waiting_for_sign_off"


def test_a_resume_is_accepted_while_a_dispatch_is_running(client, serve, held_run):
    leave_waiting("CLM-1003")
    saver = InMemorySaver()
    hold(saver=saver)
    sign_off(client, "CLM-1003")
    agent = serve(stub(), saver)
    run_id = new_dispatch()["run_id"]
    assert agent.invoke(work_run(run_id), wait=False).json() == ACCEPTED
    assert held_run.working.wait(5)

    resumed = agent.invoke(
        {"operation": "resume_claim", "claim_id": "CLM-1003"}, wait=False
    )
    assert resumed.json() == ACCEPTED
    held_run.release.set()
    agent.settle()
    assert not harness.paused(claim_of(client, "CLM-1003"), agent_on(stub(), saver))
    assert latest_dispatch(client)["status"] == "finished"
