"""The Copilot's memory of each handler: searched as a turn starts, with a card of
what it found, which goes into the instructions, and the handler's message and the
answer saved as the turn ends, and nothing else."""

import logging

from langchain_core.messages import AIMessage, HumanMessage

from agent import agentcore_memory
from agent.copilot.memory import MEMORY_ID, memory_store
from agent.tests.copilot_driver import Copilot
from agent.tests.memory_stand_in import MemoryStandIn
from agent.tests.stubs import call, stub
from backend.tests.claim_requests import held
from backend.tests.sign_in import MARCUS

PREFERENCE = "Dana likes amounts first, in short bullet points"
QUESTION = "What needs me today?"
ANSWER = "- $3,750.00 on CLM-1003, held for your sign-off"


def remembering() -> MemoryStandIn:
    """A memory with one of Dana's preferences in it."""
    return MemoryStandIn(memories=[("/handlers/HND-01/preferences/", PREFERENCE)])


def test_a_turn_starts_with_what_the_copilot_remembers(copilot: Copilot):
    copilot.store = remembering()
    copilot.model = stub(ANSWER)
    conversation = copilot.ask(QUESTION)
    [turn] = conversation["turns"]
    [card] = turn["steps"]
    assert (card["tool"], card["kind"], card["input"], card["status"]) == (
        "search_memory",
        "memory",
        QUESTION,
        "done",
    )
    assert card["answer"] == f"- {PREFERENCE}"
    [system, *_] = copilot.model.prompts[0]
    assert f"- {PREFERENCE}" in system.text
    assert copilot.store.searched == ["/handlers/HND-01"]


def test_a_turn_saves_the_message_and_the_answer_and_nothing_else(
    client, copilot: Copilot
):
    held(client, "CLM-1003", 3750.0)
    copilot.store = remembering()
    copilot.model = stub(call("get_claim", claim_id="CLM-1003"), ANSWER)
    conversation_id = copilot.ask(QUESTION)["conversation_id"]
    message, answer = copilot.store.events
    assert (message.actor, message.session) == ("HND-01", conversation_id)
    assert (answer.actor, answer.session) == ("HND-01", conversation_id)
    assert isinstance(message.message, HumanMessage)
    assert isinstance(answer.message, AIMessage)
    assert (message.message.text, answer.message.text) == (QUESTION, ANSWER)
    sign_in = copilot.last_payload()["sign_in"]
    assert sign_in not in repr(copilot.store.events)


def test_each_handler_is_searched_alone(copilot: Copilot):
    copilot.store = remembering()
    copilot.model = stub("Hello, Marcus.")
    [turn] = copilot.ask("Hello", email=MARCUS)["turns"]
    assert copilot.store.searched == ["/handlers/HND-02"]
    assert turn["steps"][0]["answer"] == "Nothing remembered that bears on this"
    assert PREFERENCE not in copilot.model.prompts[0][0].text
    assert [event.actor for event in copilot.store.events] == ["HND-02", "HND-02"]


def test_a_paused_turn_saves_once_after_its_answer(client, copilot: Copilot):
    held(client, "CLM-1003", 3750.0)
    copilot.store = remembering()
    copilot.model = stub(call("sign_off_claim", claim_id="CLM-1003"))
    conversation_id = copilot.ask("Sign off CLM-1003")["conversation_id"]
    assert copilot.store.events == []
    copilot.answer(conversation_id, "cancel")
    message, answer = copilot.store.events
    assert (message.message.text, answer.message.text) == (
        "Sign off CLM-1003",
        "I haven't signed off CLM-1003. What would you like to do instead?",
    )


def test_a_signed_off_turn_saves_once_after_the_models_answer(client, copilot: Copilot):
    held(client, "CLM-1003", 3750.0)
    copilot.store = remembering()
    copilot.model = stub(call("sign_off_claim", claim_id="CLM-1003"))
    conversation_id = copilot.ask("Sign off CLM-1003")["conversation_id"]
    copilot.model = stub("Signed off and paid.")
    copilot.answer(conversation_id, "sign_off")
    message, answer = copilot.store.events
    assert (message.message.text, answer.message.text) == (
        "Sign off CLM-1003",
        "Signed off and paid.",
    )


def test_with_memory_off_nothing_is_searched_or_saved(copilot: Copilot):
    copilot.model = stub("Hello.")
    [turn] = copilot.ask("Hello")["turns"]
    assert turn["steps"] == []
    assert "Nothing yet." in copilot.model.prompts[0][0].text


def test_a_memory_that_cant_be_reached(copilot: Copilot, caplog):
    copilot.store = MemoryStandIn(reachable=False)
    copilot.model = stub("Hello.")
    [turn] = copilot.ask("Hello")["turns"]
    [card] = turn["steps"]
    assert (card["tool"], card["status"]) == ("search_memory", "refused")
    assert card["reason"].startswith("The memory can't be reached.")
    assert (turn["status"], turn["answer"]) == ("done", "Hello.")
    [warning] = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warning.getMessage().startswith(
        "The Copilot's memory wasn't saved: EndpointConnectionError"
    )


def test_the_memory_is_read_from_its_setting(monkeypatch):
    made = []

    def recorder(**settings):
        made.append(settings)
        return MemoryStandIn()

    monkeypatch.setattr(agentcore_memory, "AgentCoreMemoryStore", recorder)
    monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-2")
    assert memory_store() is None
    monkeypatch.setenv(MEMORY_ID, "undercover_copilot_memory-abc")
    assert isinstance(memory_store(), MemoryStandIn)
    assert made == [
        {"memory_id": "undercover_copilot_memory-abc", "region_name": "eu-west-2"}
    ]
