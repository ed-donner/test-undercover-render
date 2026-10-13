"""The Copilot's cards: one for each step it takes, recorded with the app as the
step starts and again when it ends, with the tool's own name, its kind, its main
input, what was asked and what came back, trimmed for reading, and the files and
owners a context layer answer came from."""

from typing import Any

from agent.context_tools import Sources
from agent.copilot import app_api
from agent.copilot.app_api import CardResult, CardStart, CardStatus
from agent.copilot.tools import KINDS, CopilotContext
from agent.json_text import as_json

# The most of a card's text the sidebar shows.
CARD_TEXT = 2000


def trimmed(text: str) -> str:
    """A card's text, trimmed to CARD_TEXT characters."""
    return text if len(text) <= CARD_TEXT else text[: CARD_TEXT - 1] + "…"


def main_input(inputs: dict[str, Any]) -> str:
    """A tool's main input as a card shows it: its inputs' values, such as CLM-1012
    or 10."""
    return " ".join(
        value if isinstance(value, str) else as_json(value)
        for value in inputs.values()
        if value is not None
    )


def start(context: CopilotContext, tool: str, inputs: dict[str, Any]) -> int:
    """Record a card for a step as it starts, working, and return its id."""
    card: CardStart = {
        "tool": tool,
        "kind": KINDS[tool],
        "input": trimmed(main_input(inputs)),
        "asked": trimmed(as_json(inputs)),
    }
    return app_api.start_copilot_step(context.sign_in, context.turn_id, card)["step_id"]


def finish(context: CopilotContext, card: int, result: CardResult) -> None:
    app_api.finish_copilot_step(context.sign_in, context.turn_id, card, result)


def done(
    context: CopilotContext, card: int, answer: str, sources: Sources | None = None
) -> None:
    """Record what came back, and the files it came from, if any."""
    result: CardResult = {
        "status": "done",
        "answer": trimmed(answer),
        "reason": None,
        "sources": sources or [],
    }
    finish(context, card, result)


def refused(context: CopilotContext, card: int, reason: str) -> None:
    """Record why the step was refused."""
    finish(context, card, ended("refused", reason))


def failed(context: CopilotContext, card: int, reason: str) -> None:
    """Record why the step failed."""
    finish(context, card, ended("failed", reason))


def ended(status: CardStatus, reason: str) -> CardResult:
    """How a step that was refused or failed ended, and why."""
    return {"status": status, "answer": None, "reason": trimmed(reason), "sources": []}
