"""The agent identifies itself with an API key on every request: the routes only the
agent's side calls need it, the reads the dashboard shares take it or a handler's
sign-in, and the key never stands in for a handler."""

import re

import pytest
from fastapi.testclient import TestClient

from backend.database import decisions
from backend.dependencies import (
    API_KEY_HEADER,
    NEEDS_A_SIGN_IN_OR_THE_KEY,
    NEEDS_THE_KEY,
)
from backend.main import app
from backend.tests.claim_requests import decide, start
from backend.tests.dashboard_reads import read
from backend.tests.gates import (
    AGENT_OPERATIONS,
    HANDLER_OPERATIONS,
    OPEN,
    SHARED_READS,
)
from backend.tests.round_requests import create_round, propose_change, review
from backend.tests.rows import count
from backend.tests.run_requests import create_dispatch
from backend.tests.sign_in import signed_in

WRONG_KEY = {API_KEY_HEADER: "not-the-agents-key"}
# What each gate asks for in the OpenAPI document: either scheme will do for a
# shared read.
SECURITY = {
    "anyone": None,
    "the agent's key": [{"APIKeyHeader": []}],
    "the key or a sign-in": [{"APIKeyHeader": []}, {"HTTPBearer": []}],
    "a sign-in": [{"HTTPBearer": []}],
}
GATES = {
    "anyone": OPEN,
    "the agent's key": AGENT_OPERATIONS,
    "the key or a sign-in": set(SHARED_READS),
    "a sign-in": set(HANDLER_OPERATIONS),
}


def operations() -> list[tuple[str, str, str, list | None]]:
    """Every operation in the app, with its method, a path to it and the security
    it asks for."""
    return [
        (
            operation["operationId"],
            method.upper(),
            re.sub(r"{\w+}", "1", path),
            operation.get("security"),
        )
        for path, methods in app.openapi()["paths"].items()
        for method, operation in methods.items()
    ]


AGENT_ROUTES = [
    pytest.param(method, path, id=operation)
    for operation, method, path, _ in operations()
    if operation in AGENT_OPERATIONS
]


def test_the_gates_cover_every_operation_exactly_once():
    named = sorted(operation for names in GATES.values() for operation in names)
    assert named == sorted(operation for operation, *_ in operations())


def test_each_operation_asks_for_its_gates_security():
    for operation, _, _, security in operations():
        [gate] = [gate for gate, names in GATES.items() if operation in names]
        assert security == SECURITY[gate], operation


def test_recording_a_decision_needs_the_agents_key(client, dashboard):
    start(client, "CLM-1001")
    for caller in (dashboard, TestClient(app, headers=WRONG_KEY)):
        refused = decide(caller, "CLM-1001", "decline", 0)
        assert (refused.status_code, refused.json()["detail"]) == (401, NEEDS_THE_KEY)
    assert count(decisions) == 0
    assert decide(client, "CLM-1001", "decline", 0).status_code == 200


@pytest.mark.parametrize(("method", "path"), AGENT_ROUTES)
def test_every_agent_operation_refuses_a_request_without_the_key(
    dashboard, method, path
):
    for headers in ({}, signed_in()):
        refused = dashboard.request(method, path, headers=headers)
        assert (refused.status_code, refused.json()["detail"]) == (401, NEEDS_THE_KEY)


@pytest.mark.parametrize("path", SHARED_READS.values(), ids=SHARED_READS.keys())
def test_a_shared_read_takes_the_key_or_a_sign_in(client, dashboard, path):
    path = path.format(run_id=create_dispatch(client).json()["run_id"])
    assert client.get(path).status_code == 200
    assert read(dashboard, path).status_code == 200
    for headers in ({}, WRONG_KEY):
        refused = dashboard.get(path, headers=headers)
        assert (refused.status_code, refused.json()["detail"]) == (
            401,
            NEEDS_A_SIGN_IN_OR_THE_KEY,
        )


def test_with_no_key_set_handlers_still_work_and_the_agents_routes_refuse(
    dashboard, monkeypatch
):
    monkeypatch.delenv("UNDERCOVER_API_KEY")
    assert dashboard.get("/api/health").status_code == 200
    assert len(read(dashboard, "/api/claims").json()) == 26
    for route in AGENT_ROUTES:
        method, path = route.values
        refused = dashboard.request(method, path, headers={API_KEY_HEADER: ""})
        assert refused.status_code == 401


def test_an_empty_key_set_doesnt_match_an_empty_header(dashboard, monkeypatch):
    monkeypatch.setenv("UNDERCOVER_API_KEY", "")
    refused = dashboard.get("/api/runs/run-1", headers={API_KEY_HEADER: ""})
    assert refused.status_code == 401


def test_a_key_outside_ascii_is_refused_rather_than_raising(dashboard):
    headers = {API_KEY_HEADER: "clé-de-l-agent".encode()}
    assert dashboard.get("/api/runs/run-1", headers=headers).status_code == 401


def test_the_agent_reads_a_review_a_handler_gave(client):
    round_id = create_round(client).json()["round_id"]
    proposal_id = propose_change(client, round_id).json()["proposal_id"]
    reviewed = review(client, round_id, proposal_id)
    assert reviewed.status_code == 200
    assert reviewed.json()["reviewed_by"] == "Dana Whitfield"
