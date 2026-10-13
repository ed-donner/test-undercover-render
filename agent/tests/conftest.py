import threading
from dataclasses import dataclass, field
from functools import partial
from typing import Any

import pytest
from fastapi.testclient import TestClient
from langchain_core.callbacks import BaseCallbackHandler
from langgraph.checkpoint.memory import InMemorySaver

from agent import connection, dispatcher, harness, improver, service
from agent.tests.stubs import graph_on
from backend.main import app


@pytest.fixture(autouse=True)
def backend(monkeypatch):
    """Send the agent's requests to the test backend, at the same address."""
    test_backend = TestClient(app, base_url=str(connection.backend.base_url))
    monkeypatch.setattr(connection, "backend", test_backend)


class RecordRoots(BaseCallbackHandler):
    """Stands in for Langfuse's handler, keeping the metadata of each root run."""

    def __init__(self, roots: list[dict[str, Any]]) -> None:
        self.roots = roots

    def on_chain_start(self, serialized, inputs, *, parent_run_id=None, **kwargs):
        if parent_run_id is None:
            self.roots.append(dict(kwargs.get("metadata") or {}))


@pytest.fixture(autouse=True)
def traces(monkeypatch):
    """Keep Langfuse out of the tests, and record the root runs it would trace."""
    roots: list[dict[str, Any]] = []
    for module in (harness, improver):
        monkeypatch.setattr(module, "CallbackHandler", lambda: RecordRoots(roots))
    return roots


@pytest.fixture(autouse=True)
def no_waits(monkeypatch):
    """Take the waits out of the dispatcher's RetryPolicy and the check's, keeping
    their tries, so the tests never sleep through the backoff. Returns the
    dispatcher's real policy."""
    real = dispatcher.RETRY
    monkeypatch.setattr(
        dispatcher, "RETRY", real._replace(initial_interval=0, jitter=False)
    )
    check = harness.SCREEN_RETRY._replace(initial_interval=0, jitter=False)
    monkeypatch.setattr(harness, "SCREEN_RETRY", check)
    return real


@pytest.fixture
def serve():
    """Run the agent's service, without its lifespan, with each version's claim
    agents on a stub model, given the version's instructions, whose graphs share a
    saver."""

    def with_model(model, saver=None):
        saver = saver or InMemorySaver()

        def claim_agents(version):
            return partial(graph_on, model, saver, version["instructions"])

        service.app.dependency_overrides[service.claim_agents] = lambda: claim_agents
        return TestClient(service.app)

    yield with_model
    service.app.dependency_overrides.clear()


@dataclass
class HeldRun:
    """A run the service is working, held open until the test releases it."""

    working: threading.Event = field(default_factory=threading.Event)
    release: threading.Event = field(default_factory=threading.Event)


@pytest.fixture
def hold_runs(monkeypatch):
    """Hold each run the service starts from then on open until the test releases
    it."""

    def from_now():
        held = HeldRun()
        work_run = service.work_run

        def hold(run, work):
            held.working.set()
            held.release.wait(5)
            return work_run(run, work)

        monkeypatch.setattr(service, "work_run", hold)
        return held

    return from_now


@pytest.fixture
def held_run(hold_runs):
    """Hold each run the service starts open until the test releases it."""
    return hold_runs()


@pytest.fixture
def serve_rounds():
    """Run the agent's service, without its lifespan, with a stub improver and stub
    claim agents for each version, which save their progress in memory."""
    saver = InMemorySaver()

    def with_models(improver_model, claim_model):
        def claim_agents(version):
            return partial(graph_on, claim_model, saver, version["instructions"])

        workers = service.RoundWorkers(
            claim_agents, lambda round: improver_model, saver
        )
        service.app.dependency_overrides[service.round_workers] = lambda: workers
        service.app.dependency_overrides[service.claim_agents] = lambda: claim_agents
        return TestClient(service.app)

    yield with_models
    service.app.dependency_overrides.clear()
