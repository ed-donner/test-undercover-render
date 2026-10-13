"""The business's rule that keeps or rolls back a new version, with measures worked
out by hand: accuracy and the grade as differences, cost and time as fractions."""

import pytest

from backend.models import Measures, Settings
from backend.tests.settings_requests import STARTING
from backend.verdict import keep_or_roll_back

SETTINGS = Settings(**STARTING, number=1, changed_by=None, changed_at="2026-10-04")


def scores(accuracy, grade, cost, seconds):
    return Measures(
        decision_accuracy=accuracy,
        accuracy=accuracy,
        cost_of_mistakes=0,
        straight_through=1,
        grade=grade,
        model_cost_per_claim=cost,
        seconds_per_claim=seconds,
        run_seconds=60,
    )


OLD = scores(0.60, 1.50, 0.0010, 20)


@pytest.mark.parametrize(
    ("new", "verdict", "reason"),
    [
        (scores(0.72, 1.50, 0.0019, 24), "kept", "accuracy improved"),
        (scores(0.72, 1.50, 0.0021, 24), "rolled_back", "cost_per_claim got worse"),
        (scores(0.60, 1.50, 0.0008, 20), "kept", "cost_per_claim improved"),
        (
            scores(0.68, 1.60, 0.0010, 20),
            "rolled_back",
            "no score improved by more than the noise",
        ),
        (
            scores(0.72, 0.90, 0.0010, 20),
            "rolled_back",
            "it missed the objectives on grade",
        ),
        (scores(0.72, None, 0.0010, 20), "rolled_back", "it has no grade"),
    ],
)
def test_the_rule(new, verdict, reason):
    assert keep_or_roll_back(new, OLD, SETTINGS) == (verdict, reason)


def test_the_grade_counts_only_when_both_versions_have_one():
    old = scores(0.60, None, 0.0010, 20)
    assert keep_or_roll_back(scores(0.72, 0.5, 0.0010, 20), old, SETTINGS) == (
        "rolled_back",
        "it missed the objectives on grade",
    )
    assert keep_or_roll_back(scores(0.72, 1.2, 0.0010, 20), old, SETTINGS) == (
        "kept",
        "accuracy improved",
    )


def test_with_no_held_out_scores_to_compare_nothing_improved():
    assert keep_or_roll_back(scores(0.72, 1.5, 0.001, 20), None, SETTINGS) == (
        "rolled_back",
        "no score improved by more than the noise",
    )
