"""The shapes of the backend's requests and responses."""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    Field,
    StringConstraints,
)


class Status(StrEnum):
    """Where a claim stands."""

    WAITING = "waiting"
    IN_PROGRESS = "in_progress"
    WAITING_FOR_SIGN_OFF = "waiting_for_sign_off"
    SENT_BACK = "sent_back"
    DECIDED = "decided"
    LEFT_FOR_HANDLER = "left_for_handler"


class DecisionKind(StrEnum):
    APPROVE = "approve"
    DECLINE = "decline"
    REFER = "refer"


class RunKind(StrEnum):
    DISPATCH = "dispatch"
    EVALUATION = "evaluation"


class RunStatus(StrEnum):
    RUNNING = "running"
    FINISHED = "finished"
    STOPPED = "stopped"


class EvaluationSet(StrEnum):
    """The labeled sets of claims an evaluation can work."""

    EVALUATION = "evaluation"
    HELD_OUT = "held_out"


class Verdict(StrEnum):
    """Whether the business's rule kept a version of the claim agent."""

    KEPT = "kept"
    ROLLED_BACK = "rolled_back"


class VersionStatus(StrEnum):
    """Where a version of the claim agent stands."""

    CURRENT = "current"
    KEPT = "kept"
    ROLLED_BACK = "rolled_back"
    UNDER_TEST = "under_test"


class Letter(StrEnum):
    """The judge's levels, from different grounds to better expressed."""

    F = "F"
    C = "C"
    B = "B"
    A = "A"


class RoundStatus(StrEnum):
    OPEN = "open"
    FINISHED = "finished"
    STOPPED = "stopped"


class RoundStage(StrEnum):
    """Where an open round has got to, which the backend works out from its
    records."""

    FIRST_EVALUATIONS = "first_evaluations"
    IMPROVING = "improving"
    CHANGE_WAITING = "change_waiting"
    EVALUATING = "evaluating"
    VERDICT = "verdict"
    RECIPE_WAITING = "recipe_waiting"


class ProposalKind(StrEnum):
    CHANGE = "change"
    RECIPE = "recipe"


class Review(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"


class DiffLineKind(StrEnum):
    CONTEXT = "context"
    ADDED = "added"
    REMOVED = "removed"


def to_the_cent(amount: float) -> float:
    """Round an amount in US dollars to the cent."""
    return round(amount, 2)


# A model at its own default, with no reasoning effort sent. OpenAI's "none" is a
# real level of its own.
NO_REASONING_EFFORT = "default"


# The kinds of step recorded through record_step.
RecordedStepKind = Literal[
    "screening",
    "tool_call",
    "tool_result",
    "message",
    "lookup",
    "memory_search",
    "memory_save",
    "refusal",
    "error",
]
# A handler's note on a decision sent back, which only the app records.
StepKind = RecordedStepKind | Literal["sent_back"]
MOST_AGENTS = 25
NOTE_LENGTH = 1000
Agents = Annotated[
    int, Field(ge=1, le=MOST_AGENTS, description="How many claim agents work at once")
]
Benefit = Literal[
    "trip_cancellation",
    "trip_interruption",
    "trip_delay",
    "baggage_delay",
    "baggage",
    "passport",
    "emergency_medical",
]
LineKind = Literal[
    "item", "electronics", "cash", "expense", "hotel", "meals_without_receipts"
]


class Item(BaseModel):
    description: str
    category: str
    amount: float


class Document(BaseModel):
    name: str
    type: str
    content: str


class CalculationStep(BaseModel):
    step: str
    amount: float


class Calculation(BaseModel):
    lines: list[CalculationStep]
    payout: float


class DecisionRecord(BaseModel):
    """A decision as claims manual section 14 records it."""

    decision: DecisionKind
    payout: float
    calculation: Calculation | None
    section: str
    reason: str
    decided_by: str
    decided_at: str
    manual_version: str
    gateway_refusal: str | None


class Decision(DecisionRecord):
    signed_off_by: str | None
    signed_off_at: str | None


class Payment(BaseModel):
    amount: float
    paid_at: str
    signed_off_by: str | None
    signed_off_at: str | None


class SentBackDecision(DecisionRecord):
    """A decision a senior handler sent back to the agent, with their note."""

    note: str
    sent_back_by: str
    sent_back_at: str


class ClaimSummary(BaseModel):
    claim_id: str
    customer_name: str
    claim_type: str
    summary: str
    amount_claimed: float
    submitted_on: str
    status: Status
    decision: DecisionKind | None
    payout: float | None
    resuming: bool = Field(description="A resume is working on the claim")


class Claim(BaseModel):
    claim_id: str
    policy_id: str
    customer_id: str
    customer_name: str
    claim_type: str
    submitted_on: str
    incident_date: str
    incident_location: str
    summary: str
    story: str
    items: list[Item]
    amount_claimed: float
    documents: list[Document]
    status: Status
    thread_id: str | None
    attempts: int
    evaluation_id: str | None
    copy_of: str | None
    decision: Decision | None
    payment: Payment | None
    sent_back_decisions: list[SentBackDecision] = Field(
        description="The decisions handlers sent back, oldest first"
    )


class Trip(BaseModel):
    destination: str
    departs_on: str
    returns_on: str
    trip_cost: float


class Policy(BaseModel):
    policy_id: str
    customer_id: str
    plan: str
    add_ons: list[str]
    purchased_on: str
    sold_through: str
    trip: Trip
    travelers: list[str]
    status: str


class PreviousClaim(BaseModel):
    claim_id: str
    filed_on: str
    incident_date: str
    claim_type: str
    summary: str
    outcome: str
    amount_paid: float


class Handler(BaseModel):
    handler_id: str
    name: str
    role: str
    email: str
    can_approve_over_limit: bool


class Source(BaseModel):
    """A context file a lookup's answer came from, and that file's source."""

    file: str
    system: str
    owner: str
    reviewed: str


class Step(BaseModel):
    step_id: int
    thread_id: str
    kind: StepKind
    content: str
    sources: list[Source]
    created_at: str


class MeasureSettings(BaseModel):
    """A setting for each measure the rule compares: accuracy and the grade as
    differences, cost and time per claim as fractions of the old value."""

    accuracy: float = Field(ge=0)
    grade: float = Field(ge=0)
    cost_per_claim: float = Field(ge=0)
    seconds_per_claim: float = Field(ge=0)


class Objectives(BaseModel):
    """The floors a new version must meet on the held-out set."""

    accuracy: float = Field(ge=0, le=1)
    grade: float = Field(ge=0, le=3)


class SettingsValues(BaseModel):
    approval_limit: float = Field(gt=0, description="In US dollars")
    objectives: Objectives
    noise: MeasureSettings
    tolerance: MeasureSettings
    spending_limit: float = Field(gt=0, description="For each round, in US dollars")
    agents: Agents


class Settings(SettingsValues):
    number: int
    changed_by: str | None
    changed_at: str


class ModelAllowed(BaseModel):
    model: str
    reasoning_efforts: list[str]
    input_price: float = Field(description="US dollars per million input tokens")
    output_price: float = Field(description="US dollars per million output tokens")


class SettingsPage(BaseModel):
    current: Settings
    changes: list[Settings]
    models_allowed: list[ModelAllowed]


class StartRequest(BaseModel):
    thread_id: str = Field(min_length=1)


class StepRequest(BaseModel):
    kind: RecordedStepKind
    content: str = Field(min_length=1)
    sources: list[Source] = Field(
        description="The context files a lookup came from, and none for other steps"
    )


class NewStep(BaseModel):
    """A step the app adds to a claim, recorded by the agent or the app itself."""

    kind: StepKind
    content: str
    sources: list[Source]


class SendBackRequest(BaseModel):
    note: Annotated[
        str,
        StringConstraints(strip_whitespace=True, min_length=1, max_length=NOTE_LENGTH),
    ] = Field(description="What the agent should look at again")


class TakeRequest(BaseModel):
    run_id: str | None = Field(
        description="The dispatch taking the claim, or null for a resume"
    )


class DecisionRequest(BaseModel):
    """A decision to record, which claims manual section 14 checks."""

    decision: DecisionKind
    payout: Annotated[float, AfterValidator(to_the_cent)] = Field(
        description="In US dollars, 0 for a decline or referral"
    )
    section: str = Field(
        description="The sections of the wording and the manual relied on"
    )
    reason: str = Field(description="Two or three sentences explaining the decision")
    decided_by: str = Field(
        description="Who or what made the decision, such as the UnderCover Agent "
        "with the version of its configuration"
    )


class PaymentRequest(BaseModel):
    amount: float = Field(gt=0, description="The approved payout in US dollars")


class HoldRequest(BaseModel):
    reason: str = Field(min_length=1, description="Why the Gateway refused to pay")


class Plan(BaseModel):
    plan: str
    name: str
    trip_cancellation_max: float
    trip_delay_waiting_hours: int
    trip_delay_max: float
    baggage_delay_waiting_hours: int
    baggage_delay_max: float
    baggage_max: float
    per_item_limit: float
    passport_max: float
    emergency_medical_max: float
    deductible: float


class AddOn(BaseModel):
    add_on: str
    name: str
    effect: str
    electronics_per_item_limit: float | None = None


class Plans(BaseModel):
    plans: list[Plan]
    deductible_applies_to: list[Benefit]
    add_ons: list[AddOn]


class Line(BaseModel):
    description: str = Field(min_length=1)
    amount: float = Field(ge=0, description="The total claimed, before limits")
    quantity: int = Field(ge=1, description="How many separate items")
    kind: LineKind
    nights: int = Field(ge=0, description="For a hotel, and 0 otherwise")
    hours: float = Field(
        ge=0, description="For meals without receipts, and 0 otherwise"
    )


class PayoutRequest(BaseModel):
    benefit: Benefit
    lines: list[Line] = Field(
        description="The covered lines, with any excluded left out"
    )
    paid_by_others: float = Field(ge=0, description="Paid or refunded by others")


class Payout(BaseModel):
    calculation: list[CalculationStep]
    payout: float
    needs_sign_off: bool


class FailureRequest(BaseModel):
    reason: str = Field(min_length=1, description="What went wrong")


class ModelCallRequest(BaseModel):
    run_id: str | None = Field(description="The run the call was made in, or null")
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cost: float = Field(ge=0, description="In US dollars, as OpenRouter reports it")


class ModelCall(BaseModel):
    claim_id: str
    thread_id: str
    run_id: str | None
    input_tokens: int
    output_tokens: int
    cost: float
    created_at: str


class WorkTimeRequest(BaseModel):
    run_id: str | None = Field(description="The run the work was done in, or null")
    seconds: float = Field(ge=0, description="How long the agent worked on the claim")


class WorkTime(BaseModel):
    claim_id: str
    thread_id: str
    run_id: str | None
    started_at: str
    seconds: float


class StartDispatchRequest(BaseModel):
    agents: Agents


class RunClaimsRequest(BaseModel):
    claim_ids: list[str] = Field(description="The claims a dispatch works, in order")


class HeldPayout(BaseModel):
    claim_id: str
    payout: float


class DispatchSummary(BaseModel):
    approved: int
    declined: int
    referred: int
    waiting_for_sign_off: list[HeldPayout]
    left_for_handler: list[str]
    unfinished: list[str]


class RunClaim(ClaimSummary):
    started_at: str | None
    seconds: float
    model_cost: float


class RunDetails(BaseModel):
    run_id: str
    number: int
    kind: RunKind
    agents: int
    version: int
    round_id: str | None
    round_number: int | None = Field(description="The round that ran it, if any")
    model: str
    reasoning_effort: str
    status: RunStatus
    stopped_because: str | None
    started_at: str
    finished_at: str | None
    seconds: float | None
    model_cost: float


class Run(RunDetails):
    evaluation_set: EvaluationSet | None
    tiny: bool | None
    summary: DispatchSummary | None
    claims: list[RunClaim]


class StartEvaluationRequest(StartDispatchRequest):
    evaluation_set: EvaluationSet
    tiny: bool = Field(description="Only the set's five tiny claims")


class Measures(BaseModel):
    decision_accuracy: float
    accuracy: float
    cost_of_mistakes: float
    straight_through: float
    grade: float | None = Field(description="From 0 to 3, or null with none graded")
    model_cost_per_claim: float
    seconds_per_claim: float
    run_seconds: float | None


class ClaimGrade(BaseModel):
    """The judge's grade of an explanation: its score from 0 to 3, the likeliest
    level, and the chances of the same grounds and the same section as the
    handler's."""

    score: float
    letter: Letter
    same_grounds: float
    same_section: float
    cost: float


class ScoredClaim(RunClaim):
    copy_of: str
    reason: str | None
    section: str | None
    grade: ClaimGrade | None
    handler_decision: DecisionKind
    handler_payout: float
    right: bool
    mistake_cost: float


class Evaluation(RunDetails):
    evaluation_set: EvaluationSet
    tiny: bool
    size: int
    judge_cost: float
    measures: Measures


class ScoredEvaluation(Evaluation):
    claims: list[ScoredClaim]


class Accepted(BaseModel):
    status: Literal["accepted"] = "accepted"


class ScreeningModel(BaseModel):
    """The model the check for hidden instructions runs on, outside the versions."""

    model: str
    reasoning_effort: str


class ClaimAgentVersion(BaseModel):
    """A version as the claim agent reads it, with no scores."""

    number: int
    instructions: str
    model: str
    reasoning_effort: str


class DiffLine(BaseModel):
    kind: DiffLineKind
    text: str


class Diff(BaseModel):
    added: int
    removed: int
    hunks: list[list[DiffLine]]


class VersionScores(BaseModel):
    """A version's scores on each set, from the evaluations rounds ran on it."""

    evaluation: Measures | None
    held_out: Measures | None


class VersionSummary(BaseModel):
    number: int
    status: VersionStatus
    model: str
    reasoning_effort: str
    based_on: int | None
    model_before: str | None
    reasoning_effort_before: str | None
    lines_added: int
    lines_removed: int
    reason: str
    proposed_by: str
    round_id: str | None
    approved_by: str | None
    approved_at: str | None
    created_at: str
    verdict: Verdict | None
    verdict_reason: str | None
    scores: VersionScores


class VersionDetails(VersionSummary):
    instructions: str
    diff: Diff | None


class Configuration(BaseModel):
    current: int
    versions: list[VersionSummary]


class NewNumber(BaseModel):
    """The number of a version or a recipe the improver's round made."""

    number: int


class RoundForTheAgent(BaseModel):
    """A round as the agent needs it to work."""

    round_id: str
    number: int
    status: RoundStatus
    thread_id: str
    improver_model: str
    improver_reasoning_effort: str
    instructions: str = Field(description="The improver's, around the recipe")
    models_allowed: list[ModelAllowed]
    first_evaluations: list[EvaluationSet] = Field(
        description="The first evaluations the round needed as it started, in order"
    )
    version_evaluations: list[EvaluationSet] = Field(
        description="The evaluations a version under test gets, in order"
    )


class ChangeProposalRequest(BaseModel):
    instructions: str = Field(min_length=1)
    model: str = Field(min_length=1)
    reasoning_effort: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class RecipeProposalRequest(BaseModel):
    recipe: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class Proposal(BaseModel):
    proposal_id: str
    round_id: str
    kind: ProposalKind
    reason: str
    instructions: str | None
    model: str | None
    reasoning_effort: str | None
    recipe: str | None
    proposed_at: str
    review: Review | None
    reviewed_by: str | None
    reviewed_at: str | None
    rejection_reason: str | None


class RejectionRequest(BaseModel):
    reason: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] = (
        Field(description="Why, for the improver to read")
    )


class ImproverCallRequest(BaseModel):
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cost: float = Field(ge=0, description="In US dollars, as OpenRouter reports it")


class VerdictScores(BaseModel):
    held_out_before: Measures | None
    held_out_after: Measures | None
    evaluation_after: Measures | None


class VerdictResult(BaseModel):
    version: int
    verdict: Verdict
    reason: str
    current_version: int
    summary: str = Field(description="The verdict in a sentence, for the improver")
    scores: VerdictScores


# What the improver reads.


class AgentAnswer(BaseModel):
    decision: DecisionKind | None
    payout: float | None
    reason: str | None
    section: str | None


class HandlerAnswer(BaseModel):
    decision: DecisionKind
    payout: float
    reason: str
    reference: str


class JudgeAnswer(BaseModel):
    grade: float
    letter: Letter
    same_grounds: Literal["yes", "no"]
    same_section: Literal["yes", "no"]


class ClaimBesideHandler(BaseModel):
    """A claim of the evaluation set, with the agent's answer beside the
    handler's and the judge's grade."""

    claim_id: str
    summary: str
    agent: AgentAnswer
    handler: HandlerAnswer
    judge: JudgeAnswer | None


class EvaluationSetResults(BaseModel):
    wrong: list[ClaimBesideHandler]
    explained_least_well: list[ClaimBesideHandler]


class EarlierRound(BaseModel):
    round: int
    recipe_version: int
    version: int | None
    model: str | None
    reasoning_effort: str | None
    reason: str | None
    held_out_before: Measures | None
    held_out_after: Measures | None
    verdict: Verdict | None
    why: str | None


class Spending(BaseModel):
    limit: float
    spent: float
    left: float


class ImproverView(BaseModel):
    current_version: ClaimAgentVersion = Field(
        description="Without the contents of the documents, which never change"
    )
    scores: VersionScores
    evaluation_set: EvaluationSetResults
    earlier_rounds: list[EarlierRound]
    objectives_on_the_held_out_set: Objectives
    noise: MeasureSettings
    tolerance: MeasureSettings
    rule: str
    spending: Spending
    models_allowed: list[ModelAllowed]


# What the Improvement page shows.


class RoundReviewView(BaseModel):
    """Who approved or rejected one of the improver's proposals, and when."""

    kind: ProposalKind
    review: Review
    reviewed_by: str
    reviewed_at: str
    rejection_reason: str | None


class WaitingProposal(BaseModel):
    proposal_id: str
    kind: ProposalKind
    reason: str
    proposed_at: str
    diff: Diff
    model_before: str | None
    reasoning_effort_before: str | None
    model_after: str | None
    reasoning_effort_after: str | None


class RoundSummary(BaseModel):
    round_id: str
    number: int
    status: RoundStatus
    stage: RoundStage | None
    progress: str | None = Field(description="Such as 2 of 3, or null")
    started_by: str
    started_at: str
    finished_at: str | None
    stopped_by: str | None
    stopped_because: str | None
    recipe: int
    settings: int
    spending_limit: float
    cost: float
    version: int | None
    model: str | None
    reasoning_effort: str | None
    reason: str | None
    verdict: Verdict | None
    verdict_reason: str | None
    held_out_before: Measures | None
    held_out_after: Measures | None
    reviews: list[RoundReviewView]


class RoundView(RoundSummary):
    waiting: WaitingProposal | None
    evaluations: list[Evaluation]


class VersionPoint(BaseModel):
    """A version's held-out accuracy and grade, for the chart."""

    number: int
    verdict: Verdict | None
    accuracy: float | None
    grade: float | None


class RecipeSummary(BaseModel):
    number: int
    current: bool
    reason: str
    proposed_by: str
    round_id: str | None
    approved_by: str | None
    approved_at: str | None
    created_at: str
    lines_added: int
    lines_removed: int


class RecipeDetails(RecipeSummary):
    recipe: str
    diff: Diff | None


class Improvement(BaseModel):
    round: RoundView | None = Field(description="The open round, or the newest")
    rounds: list[RoundSummary]
    first_version: VersionPoint
    versions_tried: list[VersionPoint]
    recipes: list[RecipeSummary]
