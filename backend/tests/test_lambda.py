"""The backend on AWS Lambda: its handler answers a Function URL's events without
the startup hook, and each request opens a connection of its own."""

import json
from dataclasses import dataclass

import psycopg
import pytest
from fastapi.testclient import TestClient
from mangum.types import LambdaCognitoIdentity, LambdaMobileClientContext
from sqlalchemy.pool import NullPool, QueuePool

from backend.database import engine, is_seeded
from backend.dependencies import API_KEY_HEADER
from backend.main import app, handler
from backend.tests.dashboard_build import INDEX

TRANSACTION_POOLER = "postgresql://postgres.ref:secret@pooler.example.com:6543/db"
FUNCTION = "undercover-app"


@dataclass
class Context:
    """The context Lambda hands the function with each event."""

    function_name: str = FUNCTION
    function_version: str = "$LATEST"
    invoked_function_arn: str = f"arn:aws:lambda:us-east-1:0:function:{FUNCTION}"
    memory_limit_in_mb: int = 1024
    aws_request_id: str = "request-1"
    log_group_name: str = f"/aws/lambda/{FUNCTION}"
    log_stream_name: str = "stream-1"
    identity: LambdaCognitoIdentity | None = None
    client_context: LambdaMobileClientContext | None = None

    def get_remaining_time_in_millis(self) -> int:
        return 30_000


def function_url_event(path, headers=None):
    """A request as a Lambda Function URL hands it to the function."""
    return {
        "version": "2.0",
        "routeKey": "$default",
        "rawPath": path,
        "rawQueryString": "",
        "headers": {"host": "app.lambda-url.us-east-1.on.aws"} | (headers or {}),
        "requestContext": {
            "accountId": "anonymous",
            "apiId": "app",
            "domainName": "app.lambda-url.us-east-1.on.aws",
            "domainPrefix": "app",
            "http": {
                "method": "GET",
                "path": path,
                "protocol": "HTTP/1.1",
                "sourceIp": "203.0.113.7",
                "userAgent": "test",
            },
            "requestId": "request-1",
            "routeKey": "$default",
            "stage": "$default",
            "time": "06/Oct/2026:12:00:00 +0000",
            "timeEpoch": 1791374400000,
        },
        "isBase64Encoded": False,
    }


def through_the_handler(path, headers=None):
    """Call the Lambda handler with a Function URL's event, and return its answer."""
    return handler(function_url_event(path, headers), Context())


def test_the_handler_answers_without_the_startup_hook(agent_key):
    health = through_the_handler("/api/health")
    assert (health["statusCode"], json.loads(health["body"])) == (200, {"status": "ok"})
    claims = through_the_handler("/api/claims", {API_KEY_HEADER.lower(): agent_key})
    assert claims["statusCode"] == 200
    assert len(json.loads(claims["body"])) == 26
    assert through_the_handler("/api/claims")["statusCode"] == 401


def test_the_handler_never_seeds_the_database(tmp_path, monkeypatch):
    monkeypatch.setenv("UNDERCOVER_DB", str(tmp_path / "empty.db"))
    assert through_the_handler("/api/health")["statusCode"] == 200
    assert not is_seeded(engine())


@pytest.mark.usefixtures("build")
@pytest.mark.parametrize("path", ["/", "/claims/CLM-1901"])
def test_the_handler_serves_the_dashboard(path):
    page = through_the_handler(path)
    assert (page["statusCode"], page["body"]) == (200, INDEX)


@pytest.fixture
def connections(monkeypatch):
    """Record each connection psycopg is asked to open, and open none."""
    opened = []

    def record(*args, **settings):
        opened.append(settings)
        raise psycopg.OperationalError("The tests open no connection to Postgres")

    monkeypatch.setattr(psycopg, "connect", record)
    return opened


def test_on_lambda_each_request_opens_its_own_connection(
    agent_key, connections, monkeypatch
):
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", FUNCTION)
    monkeypatch.setenv("DATABASE_URL", TRANSACTION_POOLER)
    assert isinstance(engine().pool, NullPool)
    caller = TestClient(
        app, headers={API_KEY_HEADER: agent_key}, raise_server_exceptions=False
    )
    for _ in range(2):
        assert caller.get("/api/claims").status_code == 500
    assert [settings["prepare_threshold"] for settings in connections] == [None, None]
    assert {settings["port"] for settings in connections} == {6543}


def test_off_lambda_the_engine_keeps_its_pool(monkeypatch):
    monkeypatch.delenv("AWS_LAMBDA_FUNCTION_NAME", raising=False)
    monkeypatch.setenv("DATABASE_URL", TRANSACTION_POOLER)
    pool = engine().pool
    assert isinstance(pool, QueuePool)
    assert pool.size() == 4
