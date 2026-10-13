"""The business's rule that keeps or rolls back a new version of the claim agent, as
the lab's compare and keep_or_roll_back: from the new version's held-out scores, the
current version's and the round's settings."""

from typing import NamedTuple

from backend.models import Measures, Settings, Verdict

# Compared as differences: accuracy from 0 to 1, the grade from 0 to 3.
DIFFERENCES = ("accuracy", "grade")
# Compared as fractions of the old value, so 0.15 means 15% and 1.0 double.
FRACTIONS = ("cost_per_claim", "seconds_per_claim")
# Where each measure is in the scores.
SCORES = {
    "accuracy": "accuracy",
    "grade": "grade",
    "cost_per_claim": "model_cost_per_claim",
    "seconds_per_claim": "seconds_per_claim",
}
RULE = (
    "A new version is kept when it meets the objectives on the held-out set, at "
    "least one measure improves by more than its noise and none gets worse by more "
    "than its tolerance. Accuracy and the grade are compared as differences, and "
    "cost and time per claim as fractions of the old value."
)


# Why a version was rolled back without the rule being applied to its scores.
EVALUATIONS_STOPPED = "its evaluations were stopped"
CANT_AFFORD = "the round couldn't afford to evaluate it"
NOT_EVALUATED = "the improver didn't evaluate it"
STOPPED_BEFORE_VERDICT = "the round was stopped before its verdict"


class Decided(NamedTuple):
    """Whether to keep a version, and why, in the lab's words."""

    verdict: Verdict
    reason: str


def value(scores: Measures, measure: str) -> float | None:
    """One measure of a version's scores, or nothing for a missing grade."""
    return getattr(scores, SCORES[measure])


def compare(
    new: Measures, old: Measures, settings: Settings
) -> tuple[list[str], list[str]]:
    """Return the measures that got better by more than the noise, and those that
    got worse by more than the tolerance. The grade counts only when both versions
    have one."""
    better, worse = [], []
    for measure in (*DIFFERENCES, *FRACTIONS):
        after, before = value(new, measure), value(old, measure)
        if after is None or before is None:
            continue
        noise = getattr(settings.noise, measure)
        tolerance = getattr(settings.tolerance, measure)
        if measure in DIFFERENCES:
            improved, worsened = after > before + noise, after < before - tolerance
        else:
            improved = after < before * (1 - noise)
            worsened = after > before * (1 + tolerance)
        if improved:
            better.append(measure)
        if worsened:
            worse.append(measure)
    return better, worse


def keep_or_roll_back(
    new: Measures | None, old: Measures | None, settings: Settings
) -> Decided:
    """Keep a version that meets the objectives, improves at least one measure by
    more than its noise and worsens none by more than its tolerance."""
    if new is None or new.grade is None:
        return Decided(Verdict.ROLLED_BACK, "it has no grade")
    floors = {
        "accuracy": settings.objectives.accuracy,
        "grade": settings.objectives.grade,
    }
    missed = [m for m, floor in floors.items() if (value(new, m) or 0) < floor]
    if missed:
        return Decided(
            Verdict.ROLLED_BACK, f"it missed the objectives on {', '.join(missed)}"
        )
    better, worse = compare(new, old, settings) if old else ([], [])
    if worse:
        return Decided(Verdict.ROLLED_BACK, f"{', '.join(worse)} got worse")
    if not better:
        return Decided(Verdict.ROLLED_BACK, "no score improved by more than the noise")
    return Decided(Verdict.KEPT, f"{', '.join(better)} improved")
