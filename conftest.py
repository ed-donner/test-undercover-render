"""Fixtures for the backend's and the agent's tests."""

import json
import os
import shutil

import httpx
import jwt
import pytest
from fastapi.testclient import TestClient
from openrouter import OpenRouter

from agent import identity
from agent.direct import CONTEXT_URL
from agent.gateway import GATEWAY_URL
from agent.memory import MEMORY_ID
from backend import agent_service, auth, judge
from backend.dashboard import DashboardFiles
from backend.dashboard import mount as dashboard_mount
from backend.database import engine, seed
from backend.dependencies import API_KEY_HEADER
from backend.main import app
from backend.tests.dashboard_build import stand_in_build
from backend.tests.judging import JUDGE_URL, answer
from backend.tests.sign_in import PUBLIC_KEYS, SUPABASE_URL

# The agent's API key in the tests, which the backend and the agent share.
TEST_KEY = "test-agent-key-0123456789abcdefghijklmnop"


def use_sqlite(monkeypatch, path):
    """Point the backend at a SQLite file, never Postgres, on the default model."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("MODEL_NAME", raising=False)
    monkeypatch.setenv("UNDERCOVER_DB", str(path))


@pytest.fixture(scope="session")
def seeded(tmp_path_factory):
    """A SQLite database seeded once for the whole session."""
    path = tmp_path_factory.mktemp("seeded") / "undercover.db"
    with pytest.MonkeyPatch.context() as monkeypatch:
        use_sqlite(monkeypatch, path)
        seed(engine())
    return path


@pytest.fixture(autouse=True)
def database(seeded, tmp_path, monkeypatch):
    """Give every test its own copy of the session's seeded SQLite database, which
    is quicker than seeding each time."""
    path = tmp_path / "undercover.db"
    use_sqlite(monkeypatch, path)
    shutil.copyfile(seeded, path)
    return path


@pytest.fixture(autouse=True)
def no_aws(tmp_path, monkeypatch):
    """Keep every test away from AWS, a Gateway and the servers running on the
    laptop: no Gateway, context layer, memory or agent's runtime from the
    environment, never as if on AgentCore Runtime, and stand-in AWS credentials and
    a region in place of the AWS CLI's."""
    ours = (
        GATEWAY_URL,
        CONTEXT_URL,
        MEMORY_ID,
        agent_service.AGENT,
        agent_service.RUNTIME,
    )
    on_runtime = [name for name in os.environ if name.startswith(identity.PREFIX)]
    for name in (*ours, *on_runtime, "AWS_PROFILE", "AWS_SESSION_TOKEN", "AWS_REGION"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test-access-key")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test-secret-key")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "aws-config"))
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "aws-credentials"))


@pytest.fixture(autouse=True)
def agent_key(monkeypatch):
    """Give the backend and the agent the same API key in every test."""
    monkeypatch.setenv("UNDERCOVER_API_KEY", TEST_KEY)
    return TEST_KEY


@pytest.fixture(autouse=True)
def supabase_keys(monkeypatch):
    """Check sign-ins against the tests' own public key, in place of fetching
    Supabase's."""
    monkeypatch.setenv("VITE_SUPABASE_URL", SUPABASE_URL)
    monkeypatch.setattr(jwt.PyJWKClient, "fetch_data", lambda _: PUBLIC_KEYS)
    auth.public_keys.cache_clear()


@pytest.fixture
def judge_answers(monkeypatch):
    """Answer the judge's calls with a handler of the test's own, in place of
    OpenRouter's Decisions endpoint, at the tests' own address."""
    monkeypatch.setattr(judge, "JUDGE_URL", JUDGE_URL)

    def answer_with(handler):
        transport = httpx.MockTransport(handler)
        # With both clients its own, the SDK closes neither when the stand-in is
        # collected; closing an async client it made runs asyncio.run, which
        # takes the main thread's event loop away from the Lambda handler.
        stand_in = OpenRouter(
            api_key="test-key",
            client=httpx.Client(transport=transport),
            async_client=httpx.AsyncClient(transport=transport),
        )
        monkeypatch.setattr(judge, "client", lambda: stand_in)

    return answer_with


@pytest.fixture(autouse=True)
def judged(judge_answers):
    """Stand in for the judge, grading every explanation a B, and keep the body of
    each request to it."""
    requests: list[dict] = []

    def grade(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=answer())

    judge_answers(grade)
    return requests


@pytest.fixture
def agent_answers(monkeypatch):
    """Answer the backend's calls to the agent on the laptop with a handler of the
    test's own, in place of the agent."""

    def answer_with(handler):
        transport = httpx.MockTransport(handler)
        monkeypatch.setattr(agent_service, "agent", httpx.Client(transport=transport))

    return answer_with


@pytest.fixture(autouse=True)
def agent_calls(agent_answers):
    """Stand in for the agent on the laptop, taking the work each payload asks for
    and keeping the payload."""
    calls: list[object] = []

    def accept(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"accepted": True})

    agent_answers(accept)
    return calls


@pytest.fixture
def client(database):
    """The backend, called as the agent's side calls it, with the agent's key. Each
    client stays open for the test, so its requests share one event loop rather
    than starting a thread and a loop for each."""
    with TestClient(app, headers={API_KEY_HEADER: TEST_KEY}) as caller:
        yield caller


@pytest.fixture
def dashboard(database):
    """The backend, called as a handler's browser calls it, with no key, open for
    the test like the agent's side."""
    with TestClient(app) as caller:
        yield caller


@pytest.fixture
def build(tmp_path, monkeypatch):
    """Serve a stand-in for the dashboard's build in place of dashboard/dist."""
    folder = stand_in_build(tmp_path / "dist")
    monkeypatch.setattr(dashboard_mount, "app", DashboardFiles(directory=folder))
    return folder


@pytest.fixture
def no_build(tmp_path, monkeypatch):
    """Serve no build, as when dashboard/dist hasn't been built."""
    unbuilt = DashboardFiles(directory=tmp_path / "dist", check_dir=False)
    monkeypatch.setattr(dashboard_mount, "app", unbuilt)
