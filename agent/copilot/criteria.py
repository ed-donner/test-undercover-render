"""The three success criteria we agreed when the pilot started, checked in code:
an evaluation of the whole held-out set, started with our settings' claim agents
and waited for, its measures, our accuracy objective, and the app's count of
payouts over the limit, then the table of figures and one line on whether all
three are met. Every figure is worked out here, never by the model."""

import math
from typing import Any, NamedTuple

from agent.app_terms import HELD_OUT
from agent.copilot import app_api, waiting

STRAIGHT_THROUGH_TARGET = 0.70
COULDNT_START = "The evaluation couldn't start: {reason}"
STOPPED_PARTWAY = "The evaluation stopped: {reason}"
NONE_PAID = "None paid over the limit yet"
SIGNED_OFF = "{signed_off} of {paid} signed off"
HEADER = "| Criterion | Target | Figure | Met |\n| --- | --- | --- | --- |"
MET = {True: "Yes", False: "No", None: "Not known"}
VERDICTS = {
    3: "All three are met.",
    2: "Two of the three are met.",
    1: "One of the three is met.",
    0: "None of the three is met.",
}
ONLY_THE_THIRD = (
    "Only the third can be judged without the evaluation's figures, and it {is_met}."
)


class Row(NamedTuple):
    """A criterion, its target, its figure and whether it's met, or None when that
    isn't known."""

    criterion: str
    target: str
    figure: str
    met: bool | None


class Figures(NamedTuple):
    """The evaluation's straight-through share and accuracy."""

    straight_through: float
    accuracy: float


def percent(share: float) -> str:
    """A share as a whole percentage, as the Scoreboard shows it: 0.8 as 80%."""
    return f"{math.floor(share * 100 + 0.5)}%"


def as_set(share: float) -> str:
    """A share as Settings shows it, a percentage to a tenth: 0.705 as 70.5%."""
    return f"{math.floor(share * 1000 + 0.5) / 10:g}%"


# The straight-through target as the Copilot says it.
STRAIGHT_THROUGH = percent(STRAIGHT_THROUGH_TARGET)


def start(sign_in: str, agents: int) -> str:
    """Start an evaluation of the whole held-out set with the claim agents given,
    and return its run's id, or raise the app's refusal."""
    return app_api.start_evaluation(sign_in, HELD_OUT, False, agents)["run_id"]


def figures_of(went: dict[str, Any]) -> Figures | str:
    """The evaluation's figures from how it went, or why there are none: it
    stopped partway or is still going."""
    if measures := went.get("measures"):
        return Figures(measures["straight_through"], measures["accuracy"])
    if why := went.get("stopped_because"):
        return STOPPED_PARTWAY.format(reason=why)
    return went["note"]


def shares(
    figures: Figures | str, objective: float
) -> tuple[tuple[str, bool | None], tuple[str, bool | None]]:
    """The straight-through share's and the accuracy's figures and whether each
    meets its target, or why there are none."""
    if isinstance(figures, str):
        return (figures, None), (figures, None)
    return (
        (
            percent(figures.straight_through),
            figures.straight_through >= STRAIGHT_THROUGH_TARGET,
        ),
        (percent(figures.accuracy), figures.accuracy >= objective),
    )


def rows(figures: Figures | str, objective: float, over: dict[str, Any]) -> list[Row]:
    """The three criteria with their targets and figures."""
    straight_through, accuracy = shares(figures, objective)
    paid, signed_off = over["paid_over_the_limit"], over["signed_off"]
    over_the_limit = (
        NONE_PAID if paid == 0 else SIGNED_OFF.format(signed_off=signed_off, paid=paid)
    )
    return [
        Row("Straight through", f"At least {STRAIGHT_THROUGH}", *straight_through),
        Row(
            "Accuracy",
            f"At least {as_set(objective)}, our accuracy objective in Settings",
            *accuracy,
        ),
        Row(
            "Over the limit",
            "Every payout over the approval limit signed off by a handler",
            over_the_limit,
            signed_off == paid,
        ),
    ]


def verdict(table: list[Row]) -> str:
    """One line on whether all three are met."""
    known = [row.met for row in table if row.met is not None]
    if len(known) < len(table):
        return ONLY_THE_THIRD.format(is_met="is met" if table[-1].met else "isn't met")
    return VERDICTS[sum(known)]


def answer(table: list[Row]) -> str:
    """The table of the criteria and the line on whether all three are met."""
    lines = [
        f"| {row.criterion} | {row.target} | {row.figure} | {MET[row.met]} |"
        for row in table
    ]
    return "\n".join([HEADER, *lines]) + f"\n\n{verdict(table)}"


def evaluated(sign_in: str, agents: int) -> Figures | str:
    """Start the evaluation, wait for it and read its figures, or say why there are
    none, as when the app refuses to start it."""
    try:
        run_id = start(sign_in, agents)
    except app_api.Refused as refused:
        return COULDNT_START.format(reason=refused.detail)
    return figures_of(waiting.how_it_went(sign_in, waiting.wait_for(sign_in, run_id)))


def check(sign_in: str) -> str:
    """Check the three criteria as the handler signed in and give the answer."""
    settings = app_api.get_settings(sign_in)["current"]
    figures = evaluated(sign_in, settings["agents"])
    over = app_api.count_payouts_over_limit(sign_in)
    return answer(rows(figures, settings["objectives"]["accuracy"], over))
