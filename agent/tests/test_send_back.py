"""A decision sent back: the paused claim graph resumes with the handler's note, taken
by a resume or by a dispatch, forgets the decision and decides again."""

import threading
from datetime import timedelta

import pytest
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver

from agent import api, harness
from agent.tests.dispatching import dispatch, new_dispatch
from agent.tests.held import StopAtThePause, hold, resume_claim, state_of
from agent.tests.invoking import ACCEPTED
from agent.tests.queue_setup import leave_waiting
from agent.tests.records import claim_of, model_calls_of, payments_of
from agent.tests.stubs import agent_on, approve, calculate, call, record, stub
from agent.tools import claim_as_read
from backend.tests.agent_answers import accepting, unreachable
from backend.tests.claim_requests import NOTE, send_back
from backend.tests.dashboard_reads import steps_of
from backend.tests.rows import resume_heard

NEW_DECISION = "CLM-1003  approve  $890.00"


def decides_again(payout=890.0):
    """A stub model that works out a new payout on CLM-1003 and approves it."""
    return stub(calculate("CLM-1003", payout), record("approve", payout))


def sent_back(client, saver, note=NOTE):
    """Hold CLM-1003's approval of $3,750.00 for sign-off, and send it back."""
    hold(saver=saver)
    assert send_back(client, "CLM-1003", note).status_code == 200


def note_in(model):
    """The message that ends the model's first input after the resume."""
    message = model.prompts[0][-1]
    assert isinstance(message, HumanMessage)
    return message.text


def test_a_claim_sent_back_is_taken_by_a_resume_and_decided_again(client, serve):
    saver = InMemorySaver()
    sent_back(client, saver)
    model = decides_again()
    assert resume_claim(serve(model, saver), "CLM-1003").json() == ACCEPTED

    note = note_in(model)
    assert note.startswith("Dana Whitfield, a senior handler, sent your decision")
    assert NOTE in note
    claim = claim_of(client, "CLM-1003")
    assert claim["status"] == "decided"
    decision = claim["decision"]
    assert (decision["payout"], decision["calculation"]["payout"]) == (890.0, 890.0)
    assert [p["amount"] for p in payments_of("CLM-1003")] == [890.0]
    [kept] = claim["sent_back_decisions"]
    assert (kept["payout"], kept["note"]) == (3750.0, NOTE)
    resumed = model_calls_of("CLM-1003")[-2:]
    assert [call["run_id"] for call in resumed] == [None, None]

    agent = agent_on(stub(), saver)
    history = agent.graph.get_state_history(harness.thread_of(claim))
    [after_the_pause] = [
        s
        for s in history
        if s.next == (harness.AGENT,) and s.values["messages"][-1].text == note
    ]
    values = after_the_pause.values
    assert (values["decision"], values["status"], values["model_calls"]) == (
        {},
        "",
        0,
    )
    assert state_of(agent, client, "CLM-1003").values["model_calls"] == 2


def test_a_new_decision_over_the_limit_pauses_again_and_can_be_sent_back(client, serve):
    saver = InMemorySaver()
    sent_back(client, saver)
    over = decides_again(2500.0)
    assert resume_claim(serve(over, saver), "CLM-1003").json() == ACCEPTED
    claim = claim_of(client, "CLM-1003")
    assert (claim["status"], claim["decision"]["payout"]) == (
        "waiting_for_sign_off",
        2500.0,
    )
    assert harness.paused(claim, agent_on(stub(), saver))

    second = "Only the hospital's own bill is covered."
    assert send_back(client, "CLM-1003", second).status_code == 200
    model = decides_again()
    assert resume_claim(serve(model, saver), "CLM-1003").json() == ACCEPTED
    assert second in note_in(model)
    results = [m for m in model.prompts[0] if isinstance(m, ToolMessage)]
    assert results
    assert not [m for m in results if NOTE in m.text]
    claim = claim_of(client, "CLM-1003")
    assert (claim["status"], claim["decision"]["payout"]) == ("decided", 890.0)
    assert [(d["payout"], d["note"]) for d in claim["sent_back_decisions"]] == [
        (3750.0, NOTE),
        (2500.0, second),
    ]


def test_a_send_back_gives_back_the_full_allowance_of_model_calls(client):
    saver = InMemorySaver()
    reads = [call("get_claim") for _ in range(26)]
    agent = agent_on(stub(*reads, *approve("CLM-1003", 3750.0)), saver)
    harness.work_claim("CLM-1003", None, agent)
    assert state_of(agent, client, "CLM-1003").values["model_calls"] == 29
    send_back(client, "CLM-1003")
    api.take_claim("CLM-1003", None)

    model = stub(*[call("get_claim") for _ in range(31)])
    report = harness.resume("CLM-1003", agent_on(model, saver))
    assert len(model.prompts) == 30
    assert report == (
        "CLM-1003  failed: TooManyModelCalls: The claim agent made 30 model calls "
        "without finishing, back in the queue"
    )


def test_the_note_message_is_the_agents_own_whatever_its_instructions(client):
    saver = InMemorySaver()
    sent_back(client, saver)
    api.take_claim("CLM-1003", None)
    model = decides_again()
    version = {"number": 1, "instructions": "Decide the claim."}
    harness.resume("CLM-1003", agent_on(model, saver, version))
    assert model.prompts[0][0].text == "Decide the claim."
    note = note_in(model)
    for words in (
        "a senior handler's review",
        "the policy wording and the claims manual",
        "refer the claim to a handler and say why",
    ):
        assert words in note


def test_the_claim_as_the_agent_reads_it_holds_no_note(client):
    saver = InMemorySaver()
    sent_back(client, saver)
    claim = claim_of(client, "CLM-1003")
    assert claim["sent_back_decisions"]
    assert NOTE not in claim_as_read(claim)
    assert "sent_back_decisions" not in claim_as_read(claim)

    api.take_claim("CLM-1003", None)
    model = stub(
        call("get_claim"), calculate("CLM-1003", 890.0), record("approve", 890.0)
    )
    harness.resume("CLM-1003", agent_on(model, saver))
    read = model.prompts[1][-1]
    assert isinstance(read, ToolMessage)
    assert read.text.startswith('{"claim_id": "CLM-1003"')
    assert NOTE not in read.text


def test_a_resume_and_a_dispatch_asking_at_once_take_the_claim_once(
    client, serve, monkeypatch
):
    leave_waiting("CLM-1003")
    saver = InMemorySaver()
    sent_back(client, saver)
    together = threading.Barrier(2, timeout=5)
    take = api.take_claim

    def at_once(claim_id, run_id):
        together.wait()
        return take(claim_id, run_id)

    monkeypatch.setattr(api, "take_claim", at_once)
    agent = serve(decides_again(), saver)
    answers, reports = [], []
    resuming = threading.Thread(
        target=lambda: answers.append(resume_claim(agent, "CLM-1003"))
    )
    resuming.start()
    reports += dispatch(decides_again(), saver)
    resuming.join(10)

    [answer] = answers
    if answer.json() == ACCEPTED:
        assert reports == ["CLM-1003  taken by a resume"]
    else:
        assert answer.json() == {"refused": "Claim CLM-1003 isn't sent back"}
        assert reports == [NEW_DECISION]
    claim = claim_of(client, "CLM-1003")
    assert (claim["status"], claim["decision"]["payout"]) == ("decided", 890.0)
    decisions = [
        s
        for s in steps_of(client, "CLM-1003")
        if s["kind"] == "tool_call" and s["content"].startswith("record_decision")
    ]
    assert len(decisions) == 2


def test_a_dispatch_reports_a_claim_a_resume_took_after_it_was_listed(
    client, monkeypatch
):
    leave_waiting("CLM-1003")
    saver = InMemorySaver()
    sent_back(client, saver)
    list_claims = api.list_claims

    def then_a_resume_takes_it():
        queue = list_claims()
        api.take_claim("CLM-1003", None)
        return queue

    monkeypatch.setattr(api, "list_claims", then_a_resume_takes_it)
    model = stub()
    assert dispatch(model, saver) == ["CLM-1003  taken by a resume"]
    assert model.prompts == []
    assert claim_of(client, "CLM-1003")["status"] == "in_progress"


def test_a_resume_is_refused_a_claim_a_dispatch_took(client, serve):
    saver = InMemorySaver()
    sent_back(client, saver)
    api.take_claim("CLM-1003", new_dispatch()["run_id"])
    refused = resume_claim(serve(stub(), saver), "CLM-1003")
    assert refused.json() == {"refused": "Claim CLM-1003 isn't sent back"}


def test_a_dispatch_leaves_a_claim_alone_while_a_resume_works_on_it(client):
    leave_waiting("CLM-1003")
    saver = InMemorySaver()
    sent_back(client, saver)
    api.take_claim("CLM-1003", None)
    assert dispatch(stub(), saver) == []
    assert claim_of(client, "CLM-1003")["status"] == "in_progress"

    resume_heard("CLM-1003", timedelta(minutes=6))
    assert dispatch(decides_again(), saver) == [NEW_DECISION]


def test_a_send_back_the_agent_never_got_is_worked_by_the_next_dispatch(
    client, agent_answers
):
    agent_answers(unreachable)
    leave_waiting("CLM-1003")
    saver = InMemorySaver()
    sent_back(client, saver)
    assert claim_of(client, "CLM-1003")["status"] == "sent_back"
    agent_answers(accepting)

    model = decides_again()
    assert dispatch(model, saver) == [NEW_DECISION]
    assert NOTE in note_in(model)
    assert claim_of(client, "CLM-1003")["attempts"] == 1


def test_a_claim_stopped_before_its_pause_then_sent_back_is_resumed_with_the_note(
    client,
):
    leave_waiting("CLM-1003")
    saver = StopAtThePause()
    with pytest.raises(KeyboardInterrupt):
        hold(saver=saver)
    assert state_of(agent_on(stub(), saver), client, "CLM-1003").interrupts == ()
    send_back(client, "CLM-1003")

    model = decides_again()
    assert dispatch(model, saver) == [NEW_DECISION]
    assert NOTE in note_in(model)
    claim = claim_of(client, "CLM-1003")
    assert [d["payout"] for d in claim["sent_back_decisions"]] == [3750.0]
