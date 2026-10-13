import pytest

from backend.models import ClaimGrade, DecisionKind, Letter, ScoredClaim, Status
from backend.scoring import Answer, answer_of, is_right, measures, mistake_cost

APPROVE, DECLINE, REFER = DecisionKind.APPROVE, DecisionKind.DECLINE, DecisionKind.REFER


@pytest.mark.parametrize(
    ("answer", "expected", "cost"),
    [
        (Answer(APPROVE, 420), Answer(APPROVE, 420), 0),
        (Answer(DECLINE, 0), Answer(DECLINE, 0), 0),
        (Answer(REFER, 0), Answer(REFER, 0), 0),
        (Answer(DECLINE, 0), Answer(APPROVE, 420), 1500),
        (Answer(DECLINE, 0), Answer(REFER, 0), 1500),
        (Answer(APPROVE, 1240), Answer(DECLINE, 0), 1240),
        (Answer(APPROVE, 300), Answer(REFER, 0), 300),
        (Answer(REFER, 0), Answer(APPROVE, 825), 50),
        (Answer(REFER, 0), Answer(DECLINE, 0), 50),
        (Answer(APPROVE, 1240), Answer(APPROVE, 240), 1000),
        (Answer(APPROVE, 200), Answer(APPROVE, 250), 50),
    ],
)
def test_the_cost_of_a_mistake(answer, expected, cost):
    assert mistake_cost(answer, expected) == cost


def test_a_payout_within_a_dollar_is_right():
    expected = Answer(APPROVE, 250)
    assert is_right(Answer(APPROVE, 250.99), expected)
    assert is_right(Answer(APPROVE, 249.01), expected)
    assert not is_right(Answer(APPROVE, 251.01), expected)
    assert not is_right(Answer(DECLINE, 0), Answer(REFER, 0))


def test_a_claim_the_agent_didnt_decide_counts_as_a_referral():
    assert answer_of(None, None) == Answer(REFER, 0)
    assert answer_of(APPROVE, 420) == Answer(APPROVE, 420)


def scored(agent, handler, seconds, grade=None):
    """A copy decided as the agent did, beside the handler's decision."""
    (decision, payout), (handler_decision, handler_payout) = agent, handler
    answer, expected = (
        answer_of(decision, payout),
        Answer(handler_decision, handler_payout),
    )
    return ScoredClaim(
        claim_id="CLM-1104-E1",
        customer_name="Ada Lovelace",
        claim_type="baggage",
        summary="A suitcase",
        amount_claimed=300,
        submitted_on="2026-08-14",
        status=Status.DECIDED if decision else Status.WAITING,
        decision=decision,
        payout=payout,
        resuming=False,
        started_at=None,
        seconds=seconds,
        model_cost=0.01,
        copy_of="CLM-1104",
        reason=None,
        section=None,
        handler_decision=handler_decision,
        handler_payout=handler_payout,
        right=is_right(answer, expected),
        mistake_cost=mistake_cost(answer, expected),
        grade=grade,
    )


def test_the_measures_of_an_evaluation():
    claims = [
        scored((APPROVE, 420), (APPROVE, 420), 30),
        scored((APPROVE, 500), (APPROVE, 420), 50),
        scored((DECLINE, 0), (REFER, 0), 40),
        scored((None, None), (APPROVE, 100), 0),
    ]
    result = measures(claims, model_cost=0.08, run_seconds=95)
    assert result.decision_accuracy == 0.5
    assert result.accuracy == 0.25
    assert result.cost_of_mistakes == 80 + 1500 + 50
    assert result.straight_through == 0.75
    assert result.model_cost_per_claim == pytest.approx(0.02)
    assert result.seconds_per_claim == 30
    assert result.run_seconds == 95
    assert result.grade is None


def grade_of(score):
    return ClaimGrade(
        score=score, letter=Letter.B, same_grounds=1, same_section=1, cost=0
    )


def test_the_grade_averages_the_claims_the_judge_graded():
    claims = [
        scored((APPROVE, 420), (APPROVE, 420), 30, grade_of(3.0)),
        scored((APPROVE, 420), (APPROVE, 420), 30, grade_of(1.5)),
        scored((APPROVE, 420), (APPROVE, 420), 30),
    ]
    assert measures(claims, model_cost=0, run_seconds=None).grade == 2.25
