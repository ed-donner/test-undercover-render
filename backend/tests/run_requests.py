"""Requests the backend's tests send to start runs, as a handler does, to record
their work, as the agent does, and to read them, as the dashboard does."""

from backend.database import engine
from backend.lookups import current_version_number, version_row
from backend.models import RunKind
from backend.runs import new_run
from backend.tests.dashboard_reads import read
from backend.tests.rows import newest_run
from backend.tests.sign_in import DANA, MARCUS, signed_in


def run_path(run_id):
    return f"/api/runs/{run_id}"


def started_run(client, started):
    """The run a start created, as the agent reads it, or the start's refusal."""
    if started.status_code != 202:
        return started
    return client.get(run_path(newest_run()))


def start_dispatch(client, agents=3, email=MARCUS):
    """Start a dispatch as a handler does, and return the start's answer."""
    return client.post(
        "/api/dispatches", json={"agents": agents}, headers=signed_in(email)
    )


def create_dispatch(client, agents=3):
    """Start a dispatch as a handler does, which the app creates, and return it."""
    return started_run(client, start_dispatch(client, agents, DANA))


def dispatch_of(client, *claim_ids):
    """Create a dispatch and record its claims, and return its id."""
    run_id = create_dispatch(client).json()["run_id"]
    record_claims(client, run_id, *claim_ids)
    return run_id


def record_claims(client, run_id, *claim_ids):
    return client.put(f"{run_path(run_id)}/claims", json={"claim_ids": claim_ids})


def finish(client, run_id):
    return client.post(f"{run_path(run_id)}/finish")


def fail_run(client, run_id, reason="RuntimeError: The dispatcher broke"):
    """Stop a run whose work failed, as the agent does."""
    return client.post(f"{run_path(run_id)}/failure", json={"reason": reason})


def another_running_dispatch(agents=3):
    """Make a dispatch straight in the tables, running beside another, as the app
    never would, and return its id."""
    with engine().begin() as db:
        current = version_row(db, current_version_number(db))
        return new_run(db, RunKind.DISPATCH, {"agents": agents}, current)["run_id"]


def latest_dispatch(client):
    return read(client, "/api/dispatches/latest").json()


def start_evaluation(
    client, evaluation_set="held_out", tiny=True, agents=5, email=MARCUS
):
    """Start an evaluation as a handler does, and return the start's answer."""
    return client.post(
        "/api/evaluations",
        json={"evaluation_set": evaluation_set, "tiny": tiny, "agents": agents},
        headers=signed_in(email),
    )


def create_evaluation(client, evaluation_set="held_out", tiny=True, agents=5):
    """Start an evaluation as a handler does, which the app creates with its
    copies, and return it."""
    started = start_evaluation(client, evaluation_set, tiny, agents, DANA)
    return started_run(client, started)


def get_evaluation(client, run_id):
    return read(client, f"/api/evaluations/{run_id}").json()


def queue(client):
    return client.get("/api/claims").json()
