import re
from contextlib import nullcontext

import httpx
import pytest
from fastapi.testclient import TestClient

from agent import connection, service


def test_the_key_is_read_as_each_request_is_sent(monkeypatch, agent_key):
    sent: list[str | None] = []

    def answer(request: httpx.Request) -> httpx.Response:
        sent.append(request.headers.get(connection.API_KEY_HEADER))
        return httpx.Response(200, json={"status": "ok"})

    stand_in = httpx.Client(
        base_url=str(connection.backend.base_url),
        transport=httpx.MockTransport(answer),
    )
    monkeypatch.setattr(connection, "backend", stand_in)
    connection.call("GET", "/health")
    monkeypatch.setenv("UNDERCOVER_API_KEY", "a-key-set-after-the-import")
    connection.call("GET", "/health")
    assert sent == [agent_key, "a-key-set-after-the-import"]


def test_a_request_without_the_key_says_its_missing(monkeypatch):
    monkeypatch.delenv("UNDERCOVER_API_KEY")
    with pytest.raises(RuntimeError, match=re.escape(connection.MISSING_KEY)):
        connection.call("GET", "/health")


def test_the_service_refuses_to_start_without_the_key(monkeypatch):
    opened = []
    monkeypatch.delenv("UNDERCOVER_API_KEY")
    monkeypatch.setattr(
        service, "checkpoint_pool", lambda: opened.append(1) or nullcontext(object())
    )
    with (
        pytest.raises(RuntimeError, match=re.escape(connection.MISSING_KEY)),
        TestClient(service.app),
    ):
        pass
    assert opened == []
