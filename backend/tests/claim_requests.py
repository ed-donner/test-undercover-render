"""Requests the backend's tests send to work a claim."""

from backend.tests.sign_in import DANA, signed_in


def start(client, claim_id):
    return client.post(f"/api/claims/{claim_id}/start", json={"thread_id": "t-1"})


def decide(client, claim_id, decision, payout):
    return client.post(
        f"/api/claims/{claim_id}/decision",
        json={
            "decision": decision,
            "payout": payout,
            "section": "Section 3, Trip Delay",
            "reason": "The delay was covered.",
        },
    )


def pay(client, claim_id, amount):
    return client.post(f"/api/claims/{claim_id}/payment", json={"amount": amount})


def sign_off(client, claim_id, email=DANA):
    return client.post(f"/api/claims/{claim_id}/sign-off", headers=signed_in(email))


def fail(client, claim_id, reason="The model timed out"):
    return client.post(f"/api/claims/{claim_id}/failure", json={"reason": reason})


def record_call(client, claim_id, run_id, **usage):
    body = {"input_tokens": 1200, "output_tokens": 300, "cost": 0.0042} | usage
    return client.post(
        f"/api/claims/{claim_id}/model-calls", json={"run_id": run_id, **body}
    )


def record_time(client, claim_id, run_id, seconds=12.5):
    return client.post(
        f"/api/claims/{claim_id}/work-times",
        json={"run_id": run_id, "seconds": seconds},
    )
