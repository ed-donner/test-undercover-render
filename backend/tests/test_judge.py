"""The judge, Jev, grading the agent's explanation against the handler's reason."""

import json
import logging

import httpx
import pytest

from backend import judge
from backend.tests.judging import answer

HANDLER = judge.Explanation(
    "approve", "The delay was over six hours.", "Policy wording, section 3"
)
AGENT = judge.Explanation("approve", "A long delay is covered.", "Section 3")


def test_the_request(judge_answers):
    requests = []

    def keep(request):
        requests.append(request)
        return httpx.Response(200, json=answer())

    judge_answers(keep)
    grade = judge.grade(HANDLER, AGENT)
    [request] = requests
    assert str(request.url) == "https://judge.test/api/alpha/decisions"
    body = json.loads(request.content)
    assert body["model"] == "typesafe/jev-1.13"
    assert body["state"] == {
        "handler": {
            "decision": "approve",
            "reason": "The delay was over six hours.",
            "reference": "Policy wording, section 3",
        },
        "agent": {
            "decision": "approve",
            "reason": "A long delay is covered.",
            "section": "Section 3",
        },
    }
    assert list(body["questions"]) == ["grade", "same_grounds", "same_section"]
    assert "`agent.reason`" in body["questions"]["grade"]["instructions"]
    assert request.extensions["timeout"]["read"] == 10
    assert grade is not None
    assert (grade.score, grade.letter, grade.cost) == (2.2, "B", 0.00002)
    assert (grade.same_grounds, grade.same_section) == (0.8, 0.3)


def test_the_letter_is_the_likeliest_level_not_the_score_rounded(judge_answers):
    judge_answers(
        lambda request: httpx.Response(
            200,
            json=answer(
                score=1.5,
                probabilities={"0": 0.4, "1": 0.05, "2": 0.2, "3": 0.35},
            ),
        )
    )
    grade = judge.grade(HANDLER, AGENT)
    assert grade is not None
    assert (grade.score, grade.letter) == (1.5, "F")


@pytest.mark.parametrize(
    "fails",
    [
        lambda request: (_ for _ in ()).throw(httpx.ReadTimeout("Timed out")),
        lambda request: httpx.Response(500, json={"error": "Down"}),
        lambda request: httpx.Response(200, json=answer() | {"answers": {}}),
    ],
    ids=["a timeout", "an error", "no grade"],
)
def test_a_claim_the_judge_cant_grade_isnt_graded(judge_answers, caplog, fails):
    calls = []

    def once(request):
        calls.append(request)
        return fails(request)

    judge_answers(once)
    with caplog.at_level(logging.ERROR):
        assert judge.grade(HANDLER, AGENT) is None
    assert len(calls) == 1
    assert "The judge couldn't grade the explanation" in caplog.text
