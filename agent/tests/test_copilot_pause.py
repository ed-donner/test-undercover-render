"""The pause before a sign-off: checked in code first, the confirmation card filled in
by the app from its records, and the handler's answer, taken by a freshly built
Copilot on the same saved state, which signs off and pays once, or cancels with a
reply written in code. The handler's sign-in goes with every request and is saved
nowhere."""

import json
import logging

from langchain_core.messages import AIMessage, ToolMessage

from agent import connection
from agent.copilot import app_api, turns
from agent.copilot.graph import CLAIM_CHANGED, ONE_A_TURN, ONE_STEP
from agent.tests.copilot_driver import Copilot
from agent.tests.records import payments_of
from agent.tests.stubs import call, stub
from backend.tests.claim_requests import held, send_back, sign_off
from backend.tests.copilot_requests import started
from backend.tests.rows import everything_recorded
from backend.tests.run_requests import create_evaluation
from backend.tests.sign_in import MARCUS

PAID = "Signed off and paid: $3,750.00."


class Recorded:
    """The test backend, keeping each request the Copilot sends and its headers."""

    def __init__(self, backend):
        self.backend = backend
        self.requests: list[tuple[str, str]] = []
        self.headers: list[dict[str, str]] = []

    def request(self, method, path, headers, **request):
        self.requests.append((method, path))
        self.headers.append(headers)
        return self.backend.request(method, path, headers=headers, **request)


def paused_on(client, copilot: Copilot, claim_id="CLM-1003", payout=3750.0):
    """A conversation whose turn waits for Dana to confirm a sign-off the model
    asked for, naming the wrong amount in its words, and the conversation's id."""
    held(client, claim_id, payout)
    copilot.model = stub(call("sign_off_claim", "I'll pay $1.00.", claim_id=claim_id))
    return copilot.ask(f"Sign off {claim_id}")["conversation_id"]


def test_the_pause(client, copilot: Copilot):
    conversation_id = paused_on(client, copilot)
    [turn] = copilot.read(conversation_id)["turns"]
    claim = client.get("/api/claims/CLM-1003").json()
    assert turn["status"] == "waiting_for_confirmation"
    assert turn["confirmation"] == {
        "claim_id": "CLM-1003",
        "customer_name": claim["customer_name"],
        "payout": 3750.0,
        "reason": claim["decision"]["reason"],
    }
    assert turn["steps"] == []
    assert payments_of("CLM-1003") == []
    interrupts = copilot.graph_state(conversation_id).interrupts
    assert [i.value for i in interrupts] == [{"claim_id": "CLM-1003"}]


def test_a_fresh_copilot_signs_off_once_on_the_handlers_answer(
    client, copilot: Copilot, monkeypatch
):
    """One script runs across the pause and the answer: whatever ran before the
    pause, the model calls, the cards and the reads of the claim, happens once."""
    recorded = Recorded(connection.backend)
    monkeypatch.setattr(connection, "backend", recorded)
    held(client, "CLM-1003", 3750.0)
    copilot.model = stub(
        call("get_claim", claim_id="CLM-1003"),
        call("sign_off_claim", "I'll pay $1.00.", claim_id="CLM-1003"),
        PAID,
    )
    conversation_id = copilot.ask("Sign off CLM-1003")["conversation_id"]
    [turn] = copilot.answer(conversation_id, "sign_off")["turns"]
    [payment] = payments_of("CLM-1003")
    assert payment["amount"] == 3750.0
    decision = client.get("/api/claims/CLM-1003").json()["decision"]
    assert decision["signed_off_by"] == "Dana Whitfield"
    assert [(c["tool"], c["kind"], c["status"]) for c in turn["steps"]] == [
        ("get_claim", "claims", "done"),
        ("sign_off_claim", "action", "done"),
    ]
    assert (turn["status"], turn["answer"], turn["model_calls"]) == ("done", PAID, 3)
    assert len(copilot.model.prompts) == 3
    paid = copilot.model.prompts[2][-1]
    assert isinstance(paid, ToolMessage)
    assert json.loads(paid.text)["payment"]["amount"] == 3750.0
    claim_reads = [r for r in recorded.requests if r == ("GET", "/claims/CLM-1003")]
    assert len(claim_reads) == 2


def test_a_cancel_ends_the_turn_in_code(client, copilot: Copilot):
    conversation_id = paused_on(client, copilot)
    copilot.model = stub()
    [turn] = copilot.answer(conversation_id, "cancel")["turns"]
    assert payments_of("CLM-1003") == []
    assert (turn["status"], turn["answer"]) == (
        "done",
        "I haven't signed off CLM-1003. What would you like to do instead?",
    )
    assert (turn["confirmation_answer"], turn["steps"]) == ("cancel", [])
    assert copilot.model.prompts == []


def test_a_sign_off_for_a_claim_that_changed_is_canceled_in_code(
    client, copilot: Copilot
):
    conversation_id = paused_on(client, copilot)
    sign_off(client, "CLM-1003")
    copilot.model = stub()
    [turn] = copilot.answer(conversation_id, "sign_off")["turns"]
    assert (turn["status"], turn["answer"]) == ("done", CLAIM_CHANGED)
    assert copilot.model.prompts == []
    assert len(payments_of("CLM-1003")) == 1
    copilot.model = stub("Hello again.")
    later = copilot.ask("What next?", conversation_id)["turns"][-1]
    assert later["status"] == "done"


def test_one_sign_off_a_turn(client, copilot: Copilot):
    conversation_id = paused_on(client, copilot)
    held(client, "CLM-1008", 2240.0)
    copilot.model = stub(
        call("sign_off_claim", claim_id="CLM-1008"), "I'll sign CLM-1008 off next."
    )
    [turn] = copilot.answer(conversation_id, "sign_off")["turns"]
    assert [(c["input"], c["status"], c["reason"]) for c in turn["steps"]] == [
        ("CLM-1003", "done", None),
        ("CLM-1008", "refused", ONE_A_TURN),
    ]
    assert (turn["status"], turn["answer"]) == ("done", "I'll sign CLM-1008 off next.")
    assert copilot.graph_state(conversation_id).interrupts == ()
    assert payments_of("CLM-1008") == []
    assert len(payments_of("CLM-1003")) == 1


def test_a_handler_who_cant_sign_off_is_told_so_without_a_pause(
    client, copilot: Copilot, monkeypatch
):
    held(client, "CLM-1003", 3750.0)
    signed_off = []
    monkeypatch.setattr(app_api, "sign_off_claim", lambda *asked: signed_off.append(1))
    copilot.model = stub(call("sign_off_claim", claim_id="CLM-1003"), "You can't.")
    [turn] = copilot.ask("Sign off CLM-1003", email=MARCUS)["turns"]
    why = "Marcus Oyelaran can't sign off payouts over the approval limit of $1,000.00"
    [card] = turn["steps"]
    assert (card["tool"], card["status"], card["reason"]) == (
        "sign_off_claim",
        "refused",
        why,
    )
    assert (turn["status"], turn["confirmation"]) == ("done", None)
    assert copilot.model.prompts[1][-1].text == f"Refused: {why}"
    assert signed_off == []


def test_a_claim_not_waiting_for_sign_off_is_refused_before_the_pause(
    copilot: Copilot,
):
    copilot.model = stub(call("sign_off_claim", claim_id="CLM-1001"), "It isn't held.")
    [turn] = copilot.ask("Sign off CLM-1001")["turns"]
    [card] = turn["steps"]
    assert (card["status"], card["reason"]) == (
        "refused",
        "Claim CLM-1001 isn't waiting for sign-off",
    )
    assert turn["status"] == "done"


def test_a_sign_off_run_again_after_it_paid_counts_as_done(client, copilot: Copilot):
    conversation_id = paused_on(client, copilot)
    turn_id = copilot.read(conversation_id)["turns"][0]["turn_id"]
    copilot.answer_in_the_app(conversation_id, turn_id, "sign_off")
    sign_off(client, "CLM-1003")
    copilot.model = stub(PAID)
    copilot.carry_on()
    [turn] = copilot.read(conversation_id)["turns"]
    assert [(c["tool"], c["status"]) for c in turn["steps"]] == [
        ("sign_off_claim", "done")
    ]
    assert len(payments_of("CLM-1003")) == 1
    assert turn["answer"] == PAID


def test_the_sign_in_goes_with_every_request_and_is_saved_nowhere(
    client, copilot: Copilot, monkeypatch, agent_key, caplog
):
    caplog.set_level(logging.DEBUG)
    recorded = Recorded(connection.backend)
    monkeypatch.setattr(connection, "backend", recorded)
    conversation_id = paused_on(client, copilot)
    copilot.model = stub(PAID)
    copilot.answer(conversation_id, "sign_off")
    sign_ins = {payload["sign_in"] for payload in copilot.payloads}
    sent = {headers["Authorization"] for headers in recorded.headers}
    assert sent <= {f"Bearer {sign_in}" for sign_in in sign_ins}
    assert all(set(headers) == {"Authorization"} for headers in recorded.headers)
    assert agent_key
    saver = copilot.saver
    saved = repr(saver.storage) + repr(saver.writes) + repr(saver.blobs)
    recorded_by_the_app = json.dumps(everything_recorded(), default=str)
    logged = "\n".join(record.getMessage() for record in caplog.records)
    for sign_in in sign_ins:
        assert sign_in not in saved
        assert sign_in not in recorded_by_the_app
        assert sign_in not in logged


def test_a_sign_off_beside_another_tool_is_one_step_at_a_time(client, copilot: Copilot):
    held(client, "CLM-1003", 3750.0)
    lookup = call("get_claim", claim_id="CLM-1003").tool_calls[0]
    sign = call("sign_off_claim", claim_id="CLM-1003").tool_calls[0]
    copilot.model = stub(AIMessage(content="", tool_calls=[lookup, sign]))
    conversation_id = copilot.ask("Look and sign off CLM-1003")["conversation_id"]
    [turn] = copilot.read(conversation_id)["turns"]
    assert (turn["status"], turn["steps"]) == ("waiting_for_confirmation", [])
    messages = copilot.graph_state(conversation_id).values["messages"]
    [refused] = [m for m in messages if isinstance(m, ToolMessage)]
    assert (refused.tool_call_id, refused.text) == (lookup["id"], ONE_STEP)


def test_a_claim_not_found_or_a_copy_is_refused_before_the_pause(
    client, copilot: Copilot
):
    copy = create_evaluation(client).json()["claims"][0]["claim_id"]
    held(client, copy, 1500.0)
    copilot.model = stub(
        call("sign_off_claim", claim_id="CLM-9999"),
        call("sign_off_claim", claim_id=copy),
        "Neither can be signed off.",
    )
    [turn] = copilot.ask("Sign them off")["turns"]
    assert [(c["status"], c["reason"]) for c in turn["steps"]] == [
        ("refused", "Claim CLM-9999 not found"),
        ("refused", f"Claim {copy} is a copy in an evaluation, which nobody signs off"),
    ]


def test_a_sign_off_the_app_refuses_after_the_answer_goes_back_to_the_model(
    client, copilot: Copilot
):
    conversation_id = paused_on(client, copilot)
    turn_id = copilot.read(conversation_id)["turns"][0]["turn_id"]
    copilot.answer_in_the_app(conversation_id, turn_id, "sign_off")
    send_back(client, "CLM-1003")
    copilot.model = stub("It was sent back before I could sign it off.")
    copilot.carry_on()
    [turn] = copilot.read(conversation_id)["turns"]
    [card] = turn["steps"]
    assert (card["status"], card["reason"]) == (
        "refused",
        "Claim CLM-1003 is not waiting for sign-off",
    )
    assert payments_of("CLM-1003") == []
    told = copilot.model.prompts[0][-1]
    assert told.text == "Refused: Claim CLM-1003 is not waiting for sign-off"


def test_a_malformed_sign_off_goes_back_to_the_model(client, copilot: Copilot):
    held(client, "CLM-1003", 3750.0)
    copilot.model = stub(call("sign_off_claim", claim="CLM-1003"), "I'll ask again.")
    [turn] = copilot.ask("Sign off CLM-1003")["turns"]
    [card] = turn["steps"]
    assert (card["tool"], card["status"], card["reason"]) == (
        "sign_off_claim",
        "refused",
        "claim_id: Field required",
    )
    assert (turn["status"], turn["confirmation"]) == ("done", None)
    told = copilot.model.prompts[1][-1]
    assert told.text == "Refused: claim_id: Field required"


def test_an_answer_with_no_sign_off_waiting_fails_the_turn(copilot: Copilot):
    conversation_id = started(copilot.dashboard)["conversation_id"]
    turns.answer_confirmation(copilot.turn(), copilot.saver)
    [turn] = copilot.read(conversation_id)["turns"]
    assert (turn["status"], turn["failure"]) == (
        "failed",
        "NotThisTurn: No sign-off is waiting for an answer in this conversation",
    )
    assert copilot.model.prompts == []
