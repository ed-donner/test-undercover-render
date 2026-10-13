"""The judge: Jev, through OpenRouter's Decisions endpoint, grades the claim agent's
explanation of a decision against the handler's reason and reference, as in
labs/week2day5.ipynb. The endpoint is in alpha, so this is the one module that calls
it, and the one that knows its address."""

import logging
import os
from functools import cache
from typing import NamedTuple

from openrouter import OpenRouter
from openrouter.components import (
    DecisionsNoulAnswer,
    DecisionsScoreAnswer,
    QuestionsTypedDict,
)
from openrouter.utils import BackoffStrategy, RetryConfig

from backend.models import ClaimGrade, Letter

JEV = "typesafe/jev-1.13"
# The client ignores an address set on it, so each call passes this one.
JUDGE_URL = os.getenv("JUDGE_URL", "https://openrouter.ai")
TIMEOUT_MS = 10_000
# No retries: a claim the judge can't grade at once is left ungraded.
NO_RETRIES = RetryConfig("none", BackoffStrategy(0, 0, 0, 0), False)

# Jev numbers the levels by their place in the list, so F is 0 and A is 3.
RUBRIC = {
    Letter.F: "different grounds from the handler's reason, or it contradicts the "
    "handler's reason",
    Letter.C: "partly the same as the handler's reason: one of the handler's grounds "
    "or the section is missing, or it adds a ground the handler did not give",
    Letter.B: "the same grounds and the same section of the policy wording as the "
    "handler's reason",
    Letter.A: "the same grounds and section as the handler's reason, and clearly "
    "better expressed: clearer for the customer, with the section and the figures, "
    "shorter, and no jargon",
}
LEVELS = list(RUBRIC)

QUESTIONS: dict[str, QuestionsTypedDict] = {
    "grade": {
        "type": "score",
        "instructions": "An expert claims handler decided a travel insurance claim "
        "and gave `handler.reason`, resting on `handler.reference`. Grade how well "
        "`agent.reason`, citing `agent.section`, explains the same decision.",
        "criteria": [f"{letter}: {text}" for letter, text in RUBRIC.items()],
    },
    "same_grounds": {
        "type": "noul",
        "instructions": "`agent.reason` gives the same main grounds for the "
        "decision as `handler.reason`",
    },
    "same_section": {
        "type": "noul",
        "instructions": "`agent.section` refers to the same section of the policy "
        "wording as `handler.reference`",
    },
}

log = logging.getLogger(__name__)


class Explanation(NamedTuple):
    """A decision on a claim with its reason and the section relied on: the agent's
    section, or the handler's reference."""

    decision: str
    reason: str
    section: str


class Ungradable(Exception):
    """The judge answered without the grade and the two checks."""


@cache
def client() -> OpenRouter:
    """The OpenRouter client, which reads its key from OPENROUTER_API_KEY."""
    return OpenRouter()


def ask(handler: Explanation, agent: Explanation) -> ClaimGrade:
    """Ask Jev once to grade the agent's explanation against the handler's."""
    state = {
        "handler": {
            "decision": handler.decision,
            "reason": handler.reason,
            "reference": handler.section,
        },
        "agent": {
            "decision": agent.decision,
            "reason": agent.reason,
            "section": agent.section,
        },
    }
    response = client().alpha.decisions.create(
        model=JEV,
        state=state,
        questions=QUESTIONS,
        server_url=JUDGE_URL,
        timeout_ms=TIMEOUT_MS,
        retries=NO_RETRIES,
    )
    score = response.answers.get("grade")
    grounds = response.answers.get("same_grounds")
    section = response.answers.get("same_section")
    if not (
        isinstance(score, DecisionsScoreAnswer)
        and score.probabilities
        and isinstance(grounds, DecisionsNoulAnswer)
        and isinstance(section, DecisionsNoulAnswer)
    ):
        raise Ungradable(f"The judge answered {response.answers}")
    probabilities = score.probabilities
    likeliest = max(probabilities, key=lambda level: probabilities[level])
    return ClaimGrade(
        score=score.score,
        letter=LEVELS[int(likeliest)],
        same_grounds=grounds.noul,
        same_section=section.noul,
        cost=response.usage.cost or 0,
    )


def grade(handler: Explanation, agent: Explanation) -> ClaimGrade | None:
    """Grade the agent's explanation, or return nothing when the judge can't, such
    as on a timeout, which is logged."""
    try:
        return ask(handler, agent)
    except Exception:  # an ungraded claim never stops an evaluation finishing
        log.exception("The judge couldn't grade the explanation")
        return None
