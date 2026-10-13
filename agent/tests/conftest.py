import importlib
import os
import sys
import threading
from contextlib import ExitStack
from dataclasses import dataclass, field
from functools import partial
from types import ModuleType
from typing import Any

import pytest
from fastapi.testclient import TestClient
from langchain_core.callbacks import BaseCallbackHandler
from langgraph.checkpoint.memory import InMemorySaver

from agent import (
    connection,
    dispatcher,
    entrypoint,
    harness,
    identity,
    improver,
    work,
)
from agent import copilot as copilot_package
from agent.copilot import entrypoint as copilot_entrypoint
from agent.copilot import memory as copilot_memory
from agent.copilot import turns
from agent.direct import CONTEXT_URL
from agent.tests.copilot_driver import Copilot
from agent.tests.credentials import CREDENTIALS
from agent.tests.gateway_stand_in import GatewayStandIn
from agent.tests.invoking import HEALTH, Agent
from agent.tests.local_server import serving
from agent.tests.stubs import agent_on, stub
from backend.main import app
from context.server import build_server


@pytest.fixture(scope="session")
def context_layer():
    """The real context layer, served on a local port for the whole session."""
    with serving(build_server().streamable_http_app()) as address:
        yield f"{address}/mcp"


@pytest.fixture(autouse=True)
def context_at(no_aws, context_layer, monkeypatch):
    """Point the direct route at the context layer the tests serve."""
    monkeypatch.setenv(CONTEXT_URL, context_layer)
    return context_layer


@pytest.fixture(autouse=True)
def backend(database, monkeypatch):
    """Send the agent's requests to the test backend, at the same address. The
    client stays open for the test, so its requests share one event loop, as they
    would on a server, rather than starting a thread and a loop for each."""
    with TestClient(app, base_url=str(connection.backend.base_url)) as test_backend:
        monkeypatch.setattr(connection, "backend", test_backend)
        yield


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


def pauses_in(kind):
    """Whether a kind of run's claim agents pause for a handler, as the harness
    builds them."""
    return harness.traits_of(kind).pauses


@pytest.fixture
def fresh_agent():
    """Make the agent's AgentCore app, not yet ready, each with a client that stays
    open for the test, so its requests share one event loop."""
    with ExitStack() as clients:
        yield lambda: Agent(clients.enter_context(TestClient(entrypoint.app)))


@pytest.fixture
def workers_from(monkeypatch):
    """Stand in for what the agent builds as it gets ready: no checkpoint pool, and
    the workers given, with each version's claim agents on a stub model, given the
    version's instructions. The agent gets ready again in each test."""

    def given(claim_model, saver, improver_model):
        def claim_agents(version, kind):
            return partial(
                agent_on, claim_model, saver, version, pauses=pauses_in(kind)
            )

        workers = work.Workers(claim_agents, lambda round: improver_model, saver)
        monkeypatch.setattr(entrypoint, "open_checkpoint_pool", object)
        monkeypatch.setattr(entrypoint, "workers_on", lambda pool: workers)
        monkeypatch.setattr(entrypoint, "ready", entrypoint.new_ready())
        return workers

    return given


@pytest.fixture
def serve(workers_from, fresh_agent):
    """The agent's AgentCore app, ready, with its claim agents on a stub model,
    whose graphs share a saver."""

    def with_model(model, saver=None):
        workers_from(model, saver or InMemorySaver(), stub())
        agent = fresh_agent()
        agent.invoke(HEALTH)
        return agent

    return with_model


@pytest.fixture
def serve_rounds(workers_from, fresh_agent):
    """The agent's AgentCore app, ready, with a stub improver and stub claim agents
    for each version, which save their progress in memory."""
    saver = InMemorySaver()

    def with_models(improver_model, claim_model):
        workers_from(claim_model, saver, improver_model)
        agent = fresh_agent()
        agent.invoke(HEALTH)
        return agent

    return with_models


@dataclass
class HeldRun:
    """A run the agent is working, held open until the test releases it."""

    working: threading.Event = field(default_factory=threading.Event)
    release: threading.Event = field(default_factory=threading.Event)


@pytest.fixture
def hold_runs(monkeypatch):
    """Hold each run the agent starts from then on open until the test releases
    it."""

    def from_now():
        held = HeldRun()
        work_run = work.work_run

        def hold(run, work):
            held.working.set()
            held.release.wait(5)
            return work_run(run, work)

        monkeypatch.setattr(work, "work_run", hold)
        return held

    return from_now


@pytest.fixture
def held_run(hold_runs):
    """Hold each run the agent starts open until the test releases it."""
    yield (held := hold_runs())
    held.release.set()


@pytest.fixture(scope="session")
def gateway_server():
    """The stand-in Gateway, served on a local port for the whole session."""
    stand_in = GatewayStandIn()
    with serving(stand_in.asgi()) as address:
        stand_in.url = f"{address}/mcp"
        yield stand_in


@pytest.fixture
def gateway(gateway_server):
    """The stand-in Gateway, with nothing called or refused yet in this test."""
    gateway_server.reset()
    return gateway_server


@pytest.fixture
def copilot(dashboard, copilot_calls, monkeypatch):
    """The Copilot as the tests drive it, through the app, on the model each test
    gives it, saving its state in memory."""
    driver = Copilot(dashboard, copilot_calls)
    monkeypatch.setattr(turns, "copilot_model", driver.model_for)
    monkeypatch.setattr(copilot_memory, "memory_store", lambda: driver.store)
    return driver


@pytest.fixture
def on_runtime(monkeypatch, agent_key):
    """Run as on AgentCore Runtime: the deployment names the three credentials, and
    a stand-in for Identity gives each provider's value, keeping each it was asked
    for."""
    asked = []
    for setting, provider in CREDENTIALS.items():
        monkeypatch.setenv(f"AGENTCORE_CREDENTIAL_{setting}_NAME", provider)
        # Identity's value lands in the setting, which is as it was after the test.
        monkeypatch.setenv(setting, os.getenv(setting, ""))

    # The database's value is empty, which keeps the tests' backend, in the same
    # process, on SQLite.
    values = {
        "undercover-openrouter": "openrouter-key",
        "undercover-api-key": agent_key,
        "undercover-database": "",
    }

    def requires_api_key(provider_name):
        def wrap(function):
            def fetched():
                asked.append(provider_name)
                return function(api_key=values[provider_name])

            return fetched

        return wrap

    monkeypatch.setattr(identity, "requires_api_key", requires_api_key)
    return asked


@dataclass
class CopilotApp(Agent):
    """The Copilot's AgentCore app, and the module it was imported from."""

    module: ModuleType = field(kw_only=True)


@pytest.fixture
def copilot_app(copilot, monkeypatch):
    """The Copilot's AgentCore app as a new process starts it, imported afresh,
    nothing ready and no turn working, each time the test asks for one: its turns
    on the model the test gives the Copilot, saving their state in the Copilot's
    saver."""
    monkeypatch.setattr(copilot_package, "entrypoint", copilot_entrypoint)
    with ExitStack() as clients:

        def fresh() -> CopilotApp:
            name = copilot_entrypoint.__name__
            monkeypatch.delitem(sys.modules, name, raising=False)
            module = importlib.import_module(name)
            monkeypatch.setattr(module, "open_checkpoint_pool", object)
            monkeypatch.setattr(module, "saver_on", lambda pool: copilot.saver)
            client = clients.enter_context(TestClient(module.app))
            return CopilotApp(client, with_key=False, module=module)

        yield fresh
