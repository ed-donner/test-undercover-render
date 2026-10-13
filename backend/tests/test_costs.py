from datetime import UTC, datetime, timedelta

import pytest

from backend import main
from backend.tests.claim_requests import record_call, record_time, start
from backend.tests.run_requests import create_dispatch

RECORDED_AT = "2026-10-02T12:00:30+00:00"


@pytest.fixture
def run_id(client):
    return create_dispatch(client).json()["run_id"]


@pytest.mark.parametrize("in_run", [True, False])
def test_record_a_model_call(client, monkeypatch, run_id, in_run):
    monkeypatch.setattr(main, "now", lambda: RECORDED_AT)
    start(client, "CLM-1004")
    named = run_id if in_run else None
    response = record_call(client, "CLM-1004", named)
    assert response.status_code == 200
    assert response.json() == {
        "claim_id": "CLM-1004",
        "thread_id": "t-1",
        "run_id": named,
        "input_tokens": 1200,
        "output_tokens": 300,
        "cost": 0.0042,
        "created_at": RECORDED_AT,
    }


def second(moment):
    """A moment as the records have it, to the second."""
    return moment.replace(microsecond=0)


@pytest.mark.parametrize("in_run", [True, False])
def test_record_a_spell_of_work(client, run_id, in_run):
    start(client, "CLM-1004")
    named = run_id if in_run else None
    before = datetime.now(UTC)
    response = record_time(client, "CLM-1004", named)
    after = datetime.now(UTC)
    assert response.status_code == 200
    spell = response.json()
    assert (spell["claim_id"], spell["thread_id"], spell["run_id"]) == (
        "CLM-1004",
        "t-1",
        named,
    )
    assert spell["seconds"] == 12.5
    started = datetime.fromisoformat(spell["started_at"])
    took = timedelta(seconds=12.5)
    assert second(before - took) <= started <= second(after - took)


@pytest.mark.parametrize("record", [record_call, record_time])
def test_recording_needs_a_started_claim_and_a_known_run(client, record):
    not_started = record(client, "CLM-1004", None)
    assert not_started.status_code == 409
    assert not_started.json()["detail"] == "Claim CLM-1004 has not been started"
    assert record(client, "CLM-9999", None).status_code == 404
    start(client, "CLM-1004")
    unknown = record(client, "CLM-1004", "run-9")
    assert unknown.status_code == 404
    assert unknown.json()["detail"] == "Run run-9 not found"


@pytest.mark.parametrize(
    "usage", [{"input_tokens": -1}, {"output_tokens": -1}, {"cost": -0.01}]
)
def test_a_model_call_cant_be_negative(client, usage):
    start(client, "CLM-1004")
    assert record_call(client, "CLM-1004", None, **usage).status_code == 422


def test_a_spell_of_work_cant_be_negative(client):
    start(client, "CLM-1004")
    assert record_time(client, "CLM-1004", None, seconds=-1).status_code == 422
