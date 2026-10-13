"""A senior handler sends a held decision back to the agent with a note: the decision
is kept with the note and cleared from the claim, the claim waits for the agent,
and a dispatch or a resume takes it back into work once."""

import json
import logging
import threading
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from backend.database import calculations, payments
from backend.tests.agent_answers import slow, unreachable
from backend.tests.claim_requests import (
    NOTE,
    decide,
    fail,
    held,
    record_heartbeat,
    send_back,
    sign_off,
    start,
    take,
)
from backend.tests.dashboard_reads import steps_of
from backend.tests.rows import committed_claim, count, resume_heard
from backend.tests.run_requests import (
    create_evaluation,
    dispatch_of,
    finish,
    queue,
)
from backend.tests.sign_in import MARCUS


def summary_of(client, claim_id):
    [line] = [c for c in queue(client) if c["claim_id"] == claim_id]
    return line


def test_a_send_back_keeps_the_decision_with_the_note_and_clears_it(
    client, agent_answers
):
    before = held(client, "CLM-1008", 2240.0)
    calls, seen = [], []

    def accept(request):
        calls.append(json.loads(request.content))
        seen.append(committed_claim("CLM-1008")["status"])
        return httpx.Response(200, json={"accepted": True})

    agent_answers(accept)
    response = send_back(client, "CLM-1008")
    assert response.status_code == 200
    claim = response.json()
    assert (claim["status"], claim["decision"], claim["payment"]) == (
        "sent_back",
        None,
        None,
    )
    [kept] = claim["sent_back_decisions"]
    decision = before["decision"]
    assert kept == {
        "decision": "approve",
        "payout": 2240.0,
        "calculation": decision["calculation"],
        "section": decision["section"],
        "reason": decision["reason"],
        "decided_by": decision["decided_by"],
        "decided_at": decision["decided_at"],
        "manual_version": decision["manual_version"],
        "gateway_refusal": None,
        "note": NOTE,
        "sent_back_by": "Dana Whitfield",
        "sent_back_at": kept["sent_back_at"],
    }
    assert decision["calculation"]["payout"] == 2240.0
    assert datetime.fromisoformat(kept["sent_back_at"]) <= datetime.now(UTC)
    assert count(calculations) == 0
    step = steps_of(client, "CLM-1008")[-1]
    assert (step["kind"], step["content"], step["thread_id"]) == (
        "sent_back",
        f"Sent back by Dana Whitfield: {NOTE}",
        claim["thread_id"],
    )
    assert calls == [{"operation": "resume_claim", "claim_id": "CLM-1008"}]
    assert seen == ["sent_back"]
    assert client.get("/api/claims/CLM-1008").json() == claim


def test_a_note_can_be_1000_characters(client):
    held(client, "CLM-1008", 2240.0)
    note = "x" * 1000
    response = send_back(client, "CLM-1008", note)
    assert response.status_code == 200
    assert response.json()["sent_back_decisions"][0]["note"] == note


@pytest.mark.parametrize("note", ["", "   ", "x" * 1001])
def test_a_note_is_needed_of_up_to_1000_characters(client, agent_calls, note):
    held(client, "CLM-1008", 2240.0)
    assert send_back(client, "CLM-1008", note).status_code == 422
    assert summary_of(client, "CLM-1008")["status"] == "waiting_for_sign_off"
    assert agent_calls == []


def test_the_send_backs_refusals(client, dashboard, agent_calls):
    held(client, "CLM-1008", 2240.0)
    marcus = send_back(client, "CLM-1008", email=MARCUS)
    assert (marcus.status_code, marcus.json()["detail"]) == (
        403,
        "Only a handler who can sign off payouts over $1,000.00 can send this back. "
        "Marcus Oyelaran can't.",
    )
    assert (
        dashboard.post(
            "/api/claims/CLM-1008/send-back", json={"note": NOTE}
        ).status_code
        == 401
    )

    unknown = send_back(client, "CLM-9999")
    assert (unknown.status_code, unknown.json()["detail"]) == (
        404,
        "Claim CLM-9999 not found",
    )
    start(client, "CLM-1001")
    decide(client, "CLM-1001", "approve", 420.0)
    waiting = send_back(client, "CLM-1001")
    assert (waiting.status_code, waiting.json()["detail"]) == (
        409,
        "Claim CLM-1001 is not waiting for sign-off",
    )
    create_evaluation(client)
    held(client, "CLM-1112-E1", 1200.0)
    copy = send_back(client, "CLM-1112-E1")
    assert (copy.status_code, copy.json()["detail"]) == (
        409,
        "Claim CLM-1112-E1 is a copy in an evaluation and can't be sent back",
    )
    assert summary_of(client, "CLM-1008")["status"] == "waiting_for_sign_off"
    assert [c for c in agent_calls if c["operation"] == "resume_claim"] == []


@pytest.mark.parametrize("answer", [unreachable, slow])
def test_a_send_back_stands_whatever_happens_to_the_call(
    client, agent_answers, caplog, answer
):
    held(client, "CLM-1008", 2240.0)
    agent_answers(answer)
    response = send_back(client, "CLM-1008")
    assert response.status_code == 200
    assert response.json()["status"] == "sent_back"
    [warning] = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warning.getMessage().startswith("CLM-1008 wasn't resumed: ")


def test_a_sign_off_and_a_send_back_at_the_same_moment(client):
    held(client, "CLM-1008", 2240.0)
    together = threading.Barrier(2)
    answers = []

    def answer(request):
        together.wait()
        answers.append(request(client, "CLM-1008"))

    answering = [
        threading.Thread(target=answer, args=(r,)) for r in (sign_off, send_back)
    ]
    for thread in answering:
        thread.start()
    for thread in answering:
        thread.join(10)
    assert sorted(a.status_code for a in answers) == [200, 409]
    claim = client.get("/api/claims/CLM-1008").json()
    if claim["status"] == "decided":
        assert (count(payments), claim["sent_back_decisions"]) == (1, [])
    else:
        assert claim["status"] == "sent_back"
        assert (count(payments), len(claim["sent_back_decisions"])) == (0, 1)


def test_a_sent_back_claim_is_taken_once(client, dashboard):
    before = held(client, "CLM-1008", 2240.0)
    send_back(client, "CLM-1008")
    assert (
        dashboard.post("/api/claims/CLM-1008/take", json={"run_id": None}).status_code
        == 401
    )

    taken = take(client, "CLM-1008")
    assert taken.status_code == 200
    claim = taken.json()
    assert claim["status"] == "in_progress"
    assert (claim["thread_id"], claim["attempts"]) == (
        before["thread_id"],
        before["attempts"],
    )
    again = take(client, "CLM-1008")
    assert (again.status_code, again.json()["detail"]) == (
        409,
        "Claim CLM-1008 isn't sent back",
    )
    assert take(client, "CLM-1001").status_code == 409
    assert take(client, "CLM-9999").status_code == 404


def test_a_claim_taken_by_a_resume_is_resuming_while_the_agent_speaks_of_it(client):
    held(client, "CLM-1008", 2240.0)
    send_back(client, "CLM-1008")
    take(client, "CLM-1008")
    assert summary_of(client, "CLM-1008")["resuming"] is True
    resume_heard("CLM-1008", timedelta(minutes=6))
    assert summary_of(client, "CLM-1008")["resuming"] is False
    assert record_heartbeat(client, "CLM-1008").status_code == 200
    assert summary_of(client, "CLM-1008")["resuming"] is True
    assert record_heartbeat(client, "CLM-9999").status_code == 404


def test_a_claim_started_again_after_a_failed_resume_isnt_resuming(client):
    held(client, "CLM-1008", 2240.0)
    send_back(client, "CLM-1008")
    take(client, "CLM-1008")
    assert fail(client, "CLM-1008").json()["status"] == "waiting"
    assert summary_of(client, "CLM-1008")["resuming"] is False
    start(client, "CLM-1008")
    assert summary_of(client, "CLM-1008")["resuming"] is False


def test_a_claim_taken_by_a_dispatch_is_never_resuming(client):
    held(client, "CLM-1008", 2240.0)
    send_back(client, "CLM-1008")
    run_id = dispatch_of(client, "CLM-1008")
    assert take(client, "CLM-1008", run_id).status_code == 200
    assert summary_of(client, "CLM-1008")["resuming"] is False
    assert take(client, "CLM-1008", "run-9999").status_code == 404


def test_the_queue_lists_a_sent_back_claim_and_a_dispatch_leaves_it_unfinished(client):
    held(client, "CLM-1008", 2240.0)
    run_id = dispatch_of(client, "CLM-1008")
    send_back(client, "CLM-1008")
    assert summary_of(client, "CLM-1008")["status"] == "sent_back"
    summary = finish(client, run_id).json()["summary"]
    assert (summary["approved"], summary["unfinished"]) == (0, ["CLM-1008"])
