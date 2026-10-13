"""UnderCover's payout rules for an approved claim.

The rules come from section 10 of the policy wording, the plan limits in data/plans.json
and sections 6, 7 and 10 of the claims manual.
"""

import json
from math import ceil, inf
from pathlib import Path
from typing import Literal, TypedDict

from pydantic import BaseModel, Field

DATA = Path(__file__).parent.parent / "data"
PLAN_DATA = json.loads((DATA / "plans.json").read_text(encoding="utf-8"))
PLANS = {plan["plan"]: plan for plan in PLAN_DATA["plans"]}
ADD_ONS = {add_on["add_on"]: add_on for add_on in PLAN_DATA["add_ons"]}
DEDUCTIBLE_BENEFITS = PLAN_DATA["deductible_applies_to"]

ELECTRONICS_PLUS_LIMIT = ADD_ONS["electronics_plus"]["electronics_per_item_limit"]
CASH_LIMIT = 100.0
HOTEL_NIGHT_LIMIT = 350.0
MEALS_PER_TRAVELER_PER_DAY = 35.0
APPROVAL_LIMIT = 1000.0

Benefit = Literal[
    "trip_cancellation", "trip_interruption", "trip_delay", "baggage_delay", "baggage", "passport", "emergency_medical"
]

BENEFIT_MAXIMUM = {
    "trip_cancellation": "trip_cancellation_max",
    "trip_interruption": "trip_cancellation_max",
    "trip_delay": "trip_delay_max",
    "baggage_delay": "baggage_delay_max",
    "baggage": "baggage_max",
    "passport": "passport_max",
    "emergency_medical": "emergency_medical_max",
}


class Line(BaseModel):
    """One covered item or expense on a claim."""

    description: str = Field(description="What the item or expense is")
    amount: float = Field(description="The total claimed for the line in US dollars, before any limits. For several items, the total for all of them")
    quantity: int = Field(default=1, ge=1, description="How many separate items the line holds, such as 3 for three shirts. A pair or a set is one item")
    kind: Literal["item", "electronics", "cash", "expense", "hotel", "meals_without_receipts"] = Field(
        description=(
            "item: a belonging, or a pair or set that counts as one item. "
            "electronics: only a phone, tablet, laptop, camera or its lens, e-reader or smartwatch; any other device is an item. "
            "cash: cash that was lost or stolen. "
            "expense: any other cost with a receipt, such as a medical bill, a meal, a taxi, a fee or a prepaid trip cost. "
            "hotel: a hotel during a trip delay. "
            "meals_without_receipts: meals during a trip delay with no receipts."
        )
    )
    nights: int = Field(default=0, description="For a hotel, the number of nights")
    hours: float = Field(default=0, description="For meals without receipts, the length of the delay in hours")


class Step(TypedDict):
    """One line of the calculation."""

    step: str
    amount: float


class Payout(TypedDict):
    """The payout on a claim and the calculation behind it."""

    calculation: list[Step]
    payout: float
    needs_sign_off: bool


def step(description: str, amount: float) -> Step:
    """Make one line of the calculation, rounded to the cent."""
    return {"step": description, "amount": round(amount, 2)}


def limit_for(line: Line, policy: dict) -> float:
    """Return the most UnderCover pays for one line of a claim.

    Args:
        line: The item or expense
        policy: The customer's policy record

    Returns:
        The limit in US dollars, or infinity when the line has no limit of its own
    """
    plan = PLANS[policy["plan"]]
    travelers = len(policy["travelers"])
    match line.kind:
        case "item":
            return plan["per_item_limit"] * line.quantity
        case "electronics":
            per_item = ELECTRONICS_PLUS_LIMIT if "electronics_plus" in policy["add_ons"] else plan["per_item_limit"]
            return per_item * line.quantity
        case "hotel":
            rooms = ceil(travelers / 2)
            return HOTEL_NIGHT_LIMIT * rooms * line.nights
        case "meals_without_receipts":
            days = ceil(line.hours / 24)
            return MEALS_PER_TRAVELER_PER_DAY * travelers * days
        case _:
            return inf


def eligible_amount(line: Line, policy: dict) -> Step:
    """Return the eligible amount of one line of a claim.

    Args:
        line: The item or expense
        policy: The customer's policy record

    Returns:
        The step for the line: the amount claimed, or its limit if that is lower
    """
    limit = limit_for(line, policy)
    if line.amount > limit:
        return step(f"{line.description}, limited to ${limit:,.2f}", limit)
    return step(line.description, line.amount)


def benefit_maximum(policy: dict, benefit: Benefit) -> float:
    """Return the most the plan pays for a benefit.

    Args:
        policy: The customer's policy record
        benefit: The benefit the claim is paid under

    Returns:
        The plan's maximum, which for Trip Cancellation and Interruption is also capped at the trip cost
    """
    maximum = PLANS[policy["plan"]][BENEFIT_MAXIMUM[benefit]]
    if benefit in ("trip_cancellation", "trip_interruption"):
        return min(maximum, policy["trip"]["trip_cost"])
    return maximum


def work_out_payout(policy: dict, benefit: Benefit, lines: list[Line], paid_by_others: float = 0.0) -> Payout:
    """Work out the payout on an approved claim, following section 10 of the policy wording.

    Args:
        policy: The customer's policy record
        benefit: The benefit the claim is paid under
        lines: The covered items and expenses, with any excluded ones left out
        paid_by_others: Anything a carrier, hotel or other party has paid or refunded for the same loss

    Returns:
        The calculation step by step, the payout, and whether the payout needs a handler's sign-off
    """
    calculation = [eligible_amount(line, policy) for line in lines if line.kind != "cash"]
    cash = sum(line.amount for line in lines if line.kind == "cash")
    if cash:
        calculation.append(step(f"Cash, up to ${CASH_LIMIT:,.0f} in all", min(cash, CASH_LIMIT)))
    total = sum(entry["amount"] for entry in calculation)

    if paid_by_others:
        calculation.append(step("Less what others have paid or refunded", -paid_by_others))
        total -= paid_by_others

    if benefit in DEDUCTIBLE_BENEFITS and total > 0:
        deductible = min(PLANS[policy["plan"]]["deductible"], total)
        if deductible:
            calculation.append(step("Less the deductible", -deductible))
            total -= deductible

    maximum = benefit_maximum(policy, benefit)
    if total > maximum:
        calculation.append(step(f"Less the amount over the maximum of ${maximum:,.0f}", maximum - total))
        total = maximum

    if total < 0:
        calculation.append(step("Nothing is left to pay", -total))
        total = 0.0

    payout = round(total, 2)
    return {"calculation": calculation, "payout": payout, "needs_sign_off": payout > APPROVAL_LIMIT}
