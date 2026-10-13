"""Requests the backend's tests send to play out a round of the improver, as the
agent's service and the dashboard do."""

from sqlalchemy import select, update

from backend.database import engine, handler_decisions, runs
from backend.tests.claim_requests import decide
from backend.tests.dashboard_reads import read
from backend.tests.run_requests import get_evaluation
from backend.tests.sign_in import DANA, signed_in

CHANGE = {
    "instructions": "# Working a claim\n\nA rule for stolen phones.\n",
    "model": "openai/gpt-6-luna",
    "reasoning_effort": "low",
    "reason": "Two stolen phones were approved",
}
ALL = 100  # more claims than any set holds
RECIPE = {
    "recipe": "1. Read the results.\n2. Improve the recipe.\n",
    "reason": "Shorter",
}


def create_round(client, handler_id="HND-01"):
    return client.post("/api/rounds", json={"handler_id": handler_id})


def round_path(round_id):
    return f"/api/rounds/{round_id}"


def propose_change(client, round_id, **change):
    return client.post(f"{round_path(round_id)}/proposals/change", json=CHANGE | change)


def propose_recipe(client, round_id):
    return client.post(f"{round_path(round_id)}/proposals/recipe", json=RECIPE)


def review(client, round_id, proposal_id, verdict="approved", handler_id="HND-01"):
    reason = "Keep each rule general" if verdict == "rejected" else ""
    return client.post(
        f"{round_path(round_id)}/proposals/{proposal_id}/review",
        json={"review": verdict, "handler_id": handler_id, "reason": reason},
    )


def approved_change(client, round_id, **change):
    """Propose a change, approve it as Dana and make it a version under test."""
    proposal = propose_change(client, round_id, **change).json()
    review(client, round_id, proposal["proposal_id"])
    return client.post(f"{round_path(round_id)}/version").json()["number"]


def improver_call(client, round_id, cost):
    return client.post(
        f"{round_path(round_id)}/model-calls",
        json={"input_tokens": 1000, "output_tokens": 200, "cost": cost},
    )


def round_evaluation(client, round_id):
    """Ask for a round's next evaluation, on the set the backend chooses."""
    return client.post(f"/api/runs/rounds/{round_id}/evaluations")


def improvement(client):
    return read(client, "/api/improvement").json()


def stop_round(client, round_id, email=DANA):
    return client.post(
        f"/api/improvement/rounds/{round_id}/stop", headers=signed_in(email)
    )


def into_round(round_id, *evaluations):
    """Make evaluations a round's, as if the round had run them."""
    with engine().begin() as db:
        db.execute(
            update(runs)
            .where(runs.c.run_id.in_([e["run_id"] for e in evaluations]))
            .values(round_id=round_id)
        )


def handler_reasons(evaluation_set):
    """The handlers' reasons on a labeled set, by claim."""
    with engine().connect() as db:
        query = select(handler_decisions).where(
            handler_decisions.c.evaluation_set == evaluation_set
        )
        return {row["claim_id"]: row["reason"] for row in db.execute(query).mappings()}


def handler_answers(evaluation_set):
    """The handlers' decisions and payouts on a labeled set, by claim."""
    with engine().connect() as db:
        query = select(handler_decisions).where(
            handler_decisions.c.evaluation_set == evaluation_set
        )
        return {
            row["claim_id"]: (row["decision"], row["payout"])
            for row in db.execute(query).mappings()
        }


def decide_copies(client, run, right):
    """Decide an evaluation's first copies as the handlers did, as many as `right`
    says, and the rest otherwise: declining what they didn't decline, and
    referring what they declined."""
    answers = handler_answers(run["evaluation_set"])
    for n, copy in enumerate(run["claims"]):
        copy_id = copy["claim_id"]
        decision, payout = answers[copy_id.rsplit("-E", 1)[0]]
        if n >= right:
            decision, payout = ("refer" if decision == "decline" else "decline"), 0
        client.post(f"/api/claims/{copy_id}/start", json={"thread_id": copy_id})
        decide(client, copy_id, decision, payout, section="Section 3")


def play_out(client, round_id, right=0, finish=True):
    """Create one of a round's evaluations, decide its copies with `right` of them
    right, and finish it, as the agent's service would. Return the evaluation."""
    run = round_evaluation(client, round_id).json()
    decide_copies(client, run, right)
    if finish:
        client.post(f"/api/runs/{run['run_id']}/finish")
    return get_evaluation(client, run["run_id"])
