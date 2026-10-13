"""The judge's answers in the tests, in place of OpenRouter's Decisions endpoint."""

from typing import Any

JUDGE_URL = "https://judge.test"


def answer(
    score: float = 2.2,
    probabilities: dict[str, float] | None = None,
    same_grounds: float = 0.8,
    same_section: float = 0.3,
    cost: float = 0.00002,
) -> dict[str, Any]:
    """An answer as Jev gives it, a B by default."""
    return {
        "model": "typesafe/jev-1.13",
        "answers": {
            "grade": {
                "type": "score",
                "score": score,
                "probabilities": probabilities
                or {"0": 0.05, "1": 0.1, "2": 0.5, "3": 0.35},
            },
            "same_grounds": {"type": "noul", "noul": same_grounds},
            "same_section": {"type": "noul", "noul": same_section},
        },
        "usage": {"input_tokens": 400, "output_tokens": 3, "cost": cost},
    }
