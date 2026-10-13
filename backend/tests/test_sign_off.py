"""A handler's sign-off of a held payout: it pays the claim once, commits, then asks
the agent to resume the claim, and stands whatever happens to that call."""

import json
import logging
import threading

import httpx
import pytest

from backend import main
from backend.database import payments
from backend.tests.agent_answers import broken, refusing, slow, unreachable
from backend.tests.claim_requests import held, sign_off
from backend.tests.rows import committed_claim, count


def test_a_sign_off_pays_the_claim_then_asks_the_agent_to_resume_it(
    client, agent_answers
):
    held(client, "CLM-1002", 1350.0)
    calls, seen = [], []

    def accept(request):
        calls.append(json.loads(request.content))
        claim = committed_claim("CLM-1002")
        seen.append((claim["status"], claim["amount"], claim["signed_off_by"]))
        return httpx.Response(200, json={"accepted": True})

    agent_answers(accept)
    response = sign_off(client, "CLM-1002")
    assert response.status_code == 200
    claim = response.json()
    assert claim["status"] == "decided"
    assert claim["payment"]["amount"] == 1350.0
    assert claim["decision"]["signed_off_by"] == "Dana Whitfield"
    assert claim["decision"]["signed_off_at"] is not None
    assert calls == [{"operation": "resume_claim", "claim_id": "CLM-1002"}]
    assert seen == [("decided", 1350.0, "Dana Whitfield")]


def undecodable(request):
    return httpx.Response(
        200, content=b"x", headers={"Content-Encoding": "unknown-encoding-x"}
    )


@pytest.mark.parametrize("answer", [unreachable, slow, refusing, broken, undecodable])
def test_a_sign_off_stands_whatever_happens_to_the_call(
    client, agent_answers, caplog, answer
):
    held(client, "CLM-1002", 1350.0)
    agent_answers(answer)
    response = sign_off(client, "CLM-1002")
    assert response.status_code == 200
    assert response.json()["payment"]["amount"] == 1350.0
    assert committed_claim("CLM-1002")["status"] == "decided"
    [warning] = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warning.getMessage().startswith("CLM-1002 wasn't resumed: ")


def test_a_sign_off_pays_the_decision_its_move_found(client, monkeypatch):
    held(client, "CLM-1002", 1350.0)
    # The claim as read before a send back and a new decision held it again.
    as_read = dict(committed_claim("CLM-1002")) | {"payout": 1999.0}
    find_claim, reads = main.find_claim, []

    def first_read_is_old(db, claim_id):
        reads.append(claim_id)
        return as_read if len(reads) == 1 else find_claim(db, claim_id)

    monkeypatch.setattr(main, "find_claim", first_read_is_old)
    assert sign_off(client, "CLM-1002").json()["payment"]["amount"] == 1350.0


def test_two_sign_offs_at_the_same_moment_pay_the_claim_once(client, agent_calls):
    held(client, "CLM-1002", 1350.0)
    together = threading.Barrier(2)
    answers = []

    def sign():
        together.wait()
        answers.append(sign_off(client, "CLM-1002"))

    signing = [threading.Thread(target=sign) for _ in range(2)]
    for thread in signing:
        thread.start()
    for thread in signing:
        thread.join(10)
    assert sorted(a.status_code for a in answers) == [200, 409]
    [refused] = [a for a in answers if a.status_code == 409]
    assert refused.json()["detail"] == "Claim CLM-1002 is not waiting for sign-off"
    assert count(payments) == 1
    assert agent_calls == [{"operation": "resume_claim", "claim_id": "CLM-1002"}]
