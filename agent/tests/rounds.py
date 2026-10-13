"""Rounds of the improver the tests work through the agent's service: a stub
improver that follows a script of tool calls, and stub claim agents that decide
better once their instructions hold the improver's rule."""

from agent.tests.stubs import StubModel, calculate, call, stub
from backend.database import INSTRUCTIONS
from backend.tests.round_requests import handler_answers

# What the improver adds to the claim agent's instructions in the tests, and what
# makes the stub claim agents decide as the handlers did.
RULE = "\nA general rule: decide each claim as a careful handler would.\n"
VERSION_1 = (INSTRUCTIONS / "claim.md").read_text(encoding="utf-8")
LUNA = {"model": "openai/gpt-6-luna", "reasoning_effort": "low"}


class RuleFollowingModel(StubModel):
    """A stub claim agent that reads its claim, then refers it, or once its
    instructions hold the rule, decides it as the handler did, working out an
    approval's payout first."""

    answers: dict[str, tuple[str, float]] = {}

    def next_reply(self, messages):
        if len(messages) == 2:
            return call("get_claim")
        copy_id = messages[1].content.removeprefix("Claim ")
        decision, payout = ("refer", 0)
        if RULE.strip() in messages[0].content:
            decision, payout = self.answers[copy_id.rsplit("-E", 1)[0]]
        if decision == "approve" and messages[-1].name != "calculate_payout":
            return calculate(copy_id, payout)
        return call(
            "record_decision",
            decision=decision,
            payout=payout,
            section="Section 3",
            reason="The reason.",
        )


def claim_agents_model():
    answers = handler_answers("evaluation") | handler_answers("held_out")
    return RuleFollowingModel(messages=iter(()), answers=answers)


def propose(instructions=VERSION_1 + RULE, **model):
    return call(
        "propose_change",
        instructions=instructions,
        reason="It approved claims the handlers declined.",
        **(LUNA | model),
    )


def improver(*replies):
    """A stub improver with a script of replies, across its stretches."""
    return stub(*replies)


def whole_round():
    """The improver's replies in a round with one rejection: it reads the results,
    proposes a change, proposes another after the rejection, runs the evaluation,
    proposes a recipe and ends."""
    return improver(
        call("read_results"),
        propose(VERSION_1 + "\nA rule for CLM-1003.\n"),
        propose(),
        call("run_evaluation"),
        call("propose_recipe", recipe="1. Read the results.\n", reason="Shorter"),
        "The round is done.",
    )
