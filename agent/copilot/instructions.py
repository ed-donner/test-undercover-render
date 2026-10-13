"""The Copilot's instructions: its goal, who it works for and what they may do, what
it can see and do, the success criteria we agreed, and how to answer, with what it
remembers of the handler."""

from pathlib import Path
from typing import Any

from agent.copilot.criteria import STRAIGHT_THROUGH

INSTRUCTIONS = (Path(__file__).parent / "instructions.md").read_text(encoding="utf-8")
CAN_SIGN_OFF = "They can sign off payouts over the approval limit."
CANT_SIGN_OFF = "They can't sign off payouts over the approval limit."
NOTHING_REMEMBERED = "Nothing yet."


def instructions_for(handler: dict[str, Any], remembered: list[str]) -> str:
    """The instructions for the handler the app says is signed in, with what the
    Copilot remembers of them."""
    can = CAN_SIGN_OFF if handler["can_approve_over_limit"] else CANT_SIGN_OFF
    memories = "\n".join(f"- {text}" for text in remembered) or NOTHING_REMEMBERED
    return INSTRUCTIONS.format(
        name=handler["name"],
        role=handler["role"],
        sign_off=can,
        straight_through=STRAIGHT_THROUGH,
        remembered=memories,
    )
