"""UnderCover's payout rules for an approved claim.

The rules come from section 10 of the policy wording, the plans and sections 6, 7
and 10 of the claims manual. The plans come from the payout rules and the approval
limit from the settings in force.
"""

from dataclasses import dataclass
from math import ceil, inf

from backend.models import (
    Benefit,
    CalculationStep,
    Line,
    Payout,
    PayoutRequest,
    Plan,
    Plans,
    Policy,
)
from backend.money import dollars

CASH_LIMIT = 100.0
HOTEL_NIGHT_LIMIT = 350.0
MEALS_PER_TRAVELER_PER_DAY = 35.0
ELECTRONICS_PLUS = "electronics_plus"

BENEFIT_MAXIMUM = {
    "trip_cancellation": "trip_cancellation_max",
    "trip_interruption": "trip_cancellation_max",
    "trip_delay": "trip_delay_max",
    "baggage_delay": "baggage_delay_max",
    "baggage": "baggage_max",
    "passport": "passport_max",
    "emergency_medical": "emergency_medical_max",
}


@dataclass
class Limits:
    """The limits on the lines of a claim under one policy."""

    per_item: float
    electronics_per_item: float
    travelers: int


def needs_sign_off(payout: float, approval_limit: float) -> bool:
    """Say whether a payout is over the limit, and so needs a handler's sign-off."""
    return payout > approval_limit


def step(description: str, amount: float) -> CalculationStep:
    """Make one line of the calculation, rounded to the cent."""
    return CalculationStep(step=description, amount=round(amount, 2))


def limits_for(policy: Policy, plan: Plan, plans: Plans) -> Limits:
    """Return the limits on a policy's lines; Electronics Plus raises electronics."""
    electronics = plan.per_item_limit
    if ELECTRONICS_PLUS in policy.add_ons:
        add_on = next(a for a in plans.add_ons if a.add_on == ELECTRONICS_PLUS)
        electronics = add_on.electronics_per_item_limit or electronics
    return Limits(plan.per_item_limit, electronics, len(policy.travelers))


def limit_for(line: Line, limits: Limits) -> float:
    """Return the most UnderCover pays for one line, or infinity for no limit."""
    match line.kind:
        case "item":
            return limits.per_item * line.quantity
        case "electronics":
            return limits.electronics_per_item * line.quantity
        case "hotel":
            rooms = ceil(limits.travelers / 2)
            return HOTEL_NIGHT_LIMIT * rooms * line.nights
        case "meals_without_receipts":
            days = ceil(line.hours / 24)
            return MEALS_PER_TRAVELER_PER_DAY * limits.travelers * days
        case _:
            return inf


def eligible_amount(line: Line, limits: Limits) -> CalculationStep:
    """Return the amount claimed for one line, or its limit if that is lower."""
    limit = limit_for(line, limits)
    if line.amount > limit:
        return step(f"{line.description}, limited to {dollars(limit)}", limit)
    return step(line.description, line.amount)


def benefit_maximum(policy: Policy, plan: Plan, benefit: Benefit) -> float:
    """Return the most the plan pays for a benefit, capped at the trip cost for
    Trip Cancellation and Interruption."""
    maximum: float = getattr(plan, BENEFIT_MAXIMUM[benefit])
    if benefit in ("trip_cancellation", "trip_interruption"):
        return min(maximum, policy.trip.trip_cost)
    return maximum


def work_out_payout(
    policy: Policy, plans: Plans, request: PayoutRequest, approval_limit: float
) -> Payout:
    """Work out the payout on an approved claim, step by step, and whether it needs
    a handler's sign-off."""
    plan = next(plan for plan in plans.plans if plan.plan == policy.plan)
    limits = limits_for(policy, plan, plans)
    lines = request.lines
    calculation = [
        eligible_amount(line, limits) for line in lines if line.kind != "cash"
    ]
    cash = sum(line.amount for line in lines if line.kind == "cash")
    if cash:
        calculation.append(
            step(f"Cash, up to ${CASH_LIMIT:,.0f} in all", min(cash, CASH_LIMIT))
        )
    total = sum(entry.amount for entry in calculation)

    if request.paid_by_others:
        calculation.append(
            step("Less what others have paid or refunded", -request.paid_by_others)
        )
        total -= request.paid_by_others

    if request.benefit in plans.deductible_applies_to and total > 0:
        deductible = min(plan.deductible, total)
        if deductible:
            calculation.append(step("Less the deductible", -deductible))
            total -= deductible

    maximum = benefit_maximum(policy, plan, request.benefit)
    if total > maximum:
        calculation.append(
            step(
                f"Less the amount over the maximum of ${maximum:,.0f}", maximum - total
            )
        )
        total = maximum

    if total < 0:
        calculation.append(step("Nothing is left to pay", -total))
        total = 0.0

    payout = round(total, 2)
    return Payout(
        calculation=calculation,
        payout=payout,
        needs_sign_off=needs_sign_off(payout, approval_limit),
    )
