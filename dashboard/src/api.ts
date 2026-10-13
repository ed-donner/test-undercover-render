import { accessToken } from "./auth";
import { ApiError, reasonFor } from "./refusals";

export const statuses = [
  "waiting",
  "in_progress",
  "waiting_for_sign_off",
  "sent_back",
  "decided",
  "left_for_handler",
] as const;
export type Status = (typeof statuses)[number];
export type DecisionKind = "approve" | "decline" | "refer";
export type StepKind =
  | "screening"
  | "tool_call"
  | "tool_result"
  | "message"
  | "lookup"
  | "memory_search"
  | "memory_save"
  | "refusal"
  | "error"
  // A handler's note on a decision sent back, which only the app records.
  | "sent_back";

// A context file a lookup came from, with that file's source.
export interface Source {
  file: string;
  system: string;
  owner: string;
  reviewed: string;
}

export interface ClaimSummary {
  claim_id: string;
  customer_name: string;
  claim_type: string;
  summary: string;
  amount_claimed: number;
  submitted_on: string;
  status: Status;
  decision: DecisionKind | null;
  payout: number | null;
  // A resume is working on the claim, so a dispatch leaves it alone.
  resuming: boolean;
}

export interface Item {
  description: string;
  category: string;
  amount: number;
}

export interface ClaimDocument {
  name: string;
  type: string;
  content: string;
}

export interface CalculationStep {
  step: string;
  amount: number;
}

// How an approval's payout was worked out, as the payout rules gave it.
export interface Calculation {
  lines: CalculationStep[];
  payout: number;
}

// A decision as claims manual section 14 records it.
export interface DecisionRecord {
  decision: DecisionKind;
  payout: number;
  // None for a decline or a referral.
  calculation: Calculation | null;
  section: string;
  reason: string;
  decided_by: string;
  decided_at: string;
  // The claims manual's version in force when the decision was made.
  manual_version: string;
  // Why the Gateway refused to pay the approval, which then waits for sign-off.
  gateway_refusal: string | null;
}

export interface Decision extends DecisionRecord {
  signed_off_by: string | null;
  signed_off_at: string | null;
}

export interface Payment {
  amount: number;
  paid_at: string;
  signed_off_by: string | null;
  signed_off_at: string | null;
}

// The longest note a handler can send a decision back with.
export const NOTE_LENGTH = 1000;

// A decision a senior handler sent back to the agent, with their note.
export interface SentBackDecision extends DecisionRecord {
  note: string;
  sent_back_by: string;
  sent_back_at: string;
}

export interface Claim {
  claim_id: string;
  policy_id: string;
  customer_id: string;
  customer_name: string;
  claim_type: string;
  submitted_on: string;
  incident_date: string;
  incident_location: string;
  summary: string;
  story: string;
  items: Item[];
  amount_claimed: number;
  documents: ClaimDocument[];
  status: Status;
  thread_id: string | null;
  attempts: number;
  // Set on an evaluation's copy of a claim.
  evaluation_id: string | null;
  copy_of: string | null;
  decision: Decision | null;
  payment: Payment | null;
  // Oldest first.
  sent_back_decisions: SentBackDecision[];
}

export interface Policy {
  policy_id: string;
  customer_id: string;
  plan: string;
  add_ons: string[];
  purchased_on: string;
  sold_through: string;
  trip: {
    destination: string;
    departs_on: string;
    returns_on: string;
    trip_cost: number;
  };
  travelers: string[];
  status: string;
}

export interface PreviousClaim {
  claim_id: string;
  filed_on: string;
  incident_date: string;
  claim_type: string;
  summary: string;
  outcome: string;
  amount_paid: number;
}

export interface Handler {
  handler_id: string;
  name: string;
  role: string;
  email: string;
  can_approve_over_limit: boolean;
}

export interface Step {
  step_id: number;
  thread_id: string;
  kind: StepKind;
  content: string;
  // The context files a lookup came from, and none for any other step.
  sources: Source[];
  created_at: string;
}

export type RunStatus = "running" | "finished" | "stopped";
export type RunKind = "dispatch" | "evaluation";
export const evaluationSets = ["evaluation", "held_out"] as const;
export type EvaluationSet = (typeof evaluationSets)[number];

export interface HeldPayout {
  claim_id: string;
  payout: number;
}

export interface DispatchSummary {
  approved: number;
  declined: number;
  referred: number;
  waiting_for_sign_off: HeldPayout[];
  left_for_handler: string[];
  // In progress or back in the queue, for the next dispatch.
  unfinished: string[];
}

// A claim's line in the queue, with its cost and time in a run.
export interface RunClaim extends ClaimSummary {
  started_at: string | null;
  seconds: number;
  model_cost: number;
}

export interface RunDetails {
  run_id: string;
  number: number;
  kind: RunKind;
  agents: number;
  version: number;
  round_id: string | null;
  // The round that ran it, if any.
  round_number: number | null;
  model: string;
  reasoning_effort: string;
  status: RunStatus;
  // Why it stopped, for a run that stopped.
  stopped_because: string | null;
  started_at: string;
  finished_at: string | null;
  seconds: number | null;
  model_cost: number;
}

export interface Run extends RunDetails {
  evaluation_set: EvaluationSet | null;
  tiny: boolean | null;
  summary: DispatchSummary | null;
  claims: RunClaim[];
}

export interface Measures {
  decision_accuracy: number;
  accuracy: number;
  cost_of_mistakes: number;
  straight_through: number;
  // The judge's average grade from 0 to 3, or null when it graded no claim.
  grade: number | null;
  model_cost_per_claim: number;
  seconds_per_claim: number;
  run_seconds: number | null;
}

export type Letter = "F" | "C" | "B" | "A";

// The judge's grade of an explanation: its score from 0 to 3, the likeliest
// level, and the chances it gave the same grounds and section as the handler.
export interface ClaimGrade {
  score: number;
  letter: Letter;
  same_grounds: number;
  same_section: number;
  cost: number;
}

// An evaluation's copy of a claim beside the handler's decision on it.
export interface ScoredClaim extends RunClaim {
  copy_of: string;
  reason: string | null;
  grade: ClaimGrade | null;
  handler_decision: DecisionKind;
  handler_payout: number;
  right: boolean;
  mistake_cost: number;
}

export interface Evaluation extends RunDetails {
  evaluation_set: EvaluationSet;
  tiny: boolean;
  size: number;
  judge_cost: number;
  measures: Measures;
}

export interface ScoredEvaluation extends Evaluation {
  claims: ScoredClaim[];
}

export interface Accepted {
  status: "accepted";
}

export type VersionStatus = "current" | "kept" | "rolled_back" | "under_test";
export type Verdict = "kept" | "rolled_back";
export type DiffLineKind = "context" | "added" | "removed";

export interface DiffLine {
  kind: DiffLineKind;
  text: string;
}

// The lines that differ between two texts, in hunks with their context.
export interface Diff {
  added: number;
  removed: number;
  hunks: DiffLine[][];
}

// A version's scores on each set, from the evaluations rounds ran on it.
export interface VersionScores {
  evaluation: Measures | null;
  held_out: Measures | null;
}

export interface VersionSummary {
  number: number;
  status: VersionStatus;
  model: string;
  reasoning_effort: string;
  // The version this one changes, and its model, or null for version 1.
  based_on: number | null;
  model_before: string | null;
  reasoning_effort_before: string | null;
  lines_added: number;
  lines_removed: number;
  reason: string;
  proposed_by: string;
  round_id: string | null;
  approved_by: string | null;
  approved_at: string | null;
  created_at: string;
  verdict: Verdict | null;
  verdict_reason: string | null;
  scores: VersionScores;
}

export interface VersionDetails extends VersionSummary {
  instructions: string;
  diff: Diff | null;
}

export interface Configuration {
  current: number;
  versions: VersionSummary[];
}

// A setting for each measure the rule compares: accuracy and the grade as
// differences, cost and time per claim as fractions of the old value.
export interface MeasureSettings {
  accuracy: number;
  grade: number;
  cost_per_claim: number;
  seconds_per_claim: number;
}

export interface SettingsValues {
  approval_limit: number;
  objectives: { accuracy: number; grade: number };
  noise: MeasureSettings;
  tolerance: MeasureSettings;
  spending_limit: number;
  agents: number;
}

export interface Settings extends SettingsValues {
  number: number;
  changed_by: string | null;
  changed_at: string;
}

export interface ModelAllowed {
  model: string;
  reasoning_efforts: string[];
  // US dollars per million tokens.
  input_price: number;
  output_price: number;
}

export interface SettingsPage {
  current: Settings;
  changes: Settings[];
  models_allowed: ModelAllowed[];
}

export type RoundStatus = "open" | "finished" | "stopped";
export type RoundStage =
  | "first_evaluations"
  | "improving"
  | "change_waiting"
  | "evaluating"
  | "verdict"
  | "recipe_waiting";
export type ProposalKind = "change" | "recipe";
export type Review = "approved" | "rejected";

// Who approved or rejected one of the improver's proposals, and when.
export interface RoundReview {
  kind: ProposalKind;
  review: Review;
  reviewed_by: string;
  reviewed_at: string;
  rejection_reason: string | null;
}

// The proposal waiting for a handler, with what it would change. A recipe has
// no model.
export interface WaitingProposal {
  proposal_id: string;
  kind: ProposalKind;
  reason: string;
  proposed_at: string;
  diff: Diff;
  model_before: string | null;
  reasoning_effort_before: string | null;
  model_after: string | null;
  reasoning_effort_after: string | null;
}

export interface RoundSummary {
  round_id: string;
  number: number;
  status: RoundStatus;
  // Where an open round has got to, and how far, such as "2 of 3".
  stage: RoundStage | null;
  progress: string | null;
  started_by: string;
  started_at: string;
  finished_at: string | null;
  stopped_by: string | null;
  stopped_because: string | null;
  recipe: number;
  settings: number;
  spending_limit: number;
  cost: number;
  // The version the round tried, if any, and its verdict.
  version: number | null;
  model: string | null;
  reasoning_effort: string | null;
  reason: string | null;
  verdict: Verdict | null;
  verdict_reason: string | null;
  held_out_before: Measures | null;
  held_out_after: Measures | null;
  reviews: RoundReview[];
}

export interface RoundView extends RoundSummary {
  waiting: WaitingProposal | null;
  evaluations: Evaluation[];
}

// A version's held-out accuracy and grade, for the chart.
export interface VersionPoint {
  number: number;
  verdict: Verdict | null;
  accuracy: number | null;
  grade: number | null;
}

export interface RecipeSummary {
  number: number;
  current: boolean;
  reason: string;
  proposed_by: string;
  round_id: string | null;
  approved_by: string | null;
  approved_at: string | null;
  created_at: string;
  lines_added: number;
  lines_removed: number;
}

export interface RecipeDetails extends RecipeSummary {
  recipe: string;
  diff: Diff | null;
}

export interface Improvement {
  // The open round, or the newest.
  round: RoundView | null;
  rounds: RoundSummary[];
  first_version: VersionPoint;
  versions_tried: VersionPoint[];
  recipes: RecipeSummary[];
}

// Sends a request with the signed-in handler's access token, if any.
async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = await accessToken();
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(path, { ...init, headers });
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as {
      detail?: unknown;
    };
    throw new ApiError(response.status, reasonFor(body.detail));
  }
  return (await response.json()) as T;
}

function send<T>(method: "POST" | "PUT", path: string, body?: object) {
  if (body === undefined) return request<T>(path, { method });
  return request<T>(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

const post = <T>(path: string, body?: object) => send<T>("POST", path, body);

const CLAIMS = "/api/claims";
const claimPath = (claimId: string) =>
  `${CLAIMS}/${encodeURIComponent(claimId)}`;
const DISPATCHES = "/api/dispatches";
const CONFIGURATION = "/api/configuration";
const SETTINGS = "/api/settings";
const EVALUATIONS = "/api/evaluations";
const IMPROVEMENT = "/api/improvement";
const ROUNDS = `${IMPROVEMENT}/rounds`;
const roundPath = (roundId: string) =>
  `${ROUNDS}/${encodeURIComponent(roundId)}`;
const proposalPath = (roundId: string, proposalId: string) =>
  `${roundPath(roundId)}/proposals/${encodeURIComponent(proposalId)}`;

export const api = {
  listClaims: () => request<ClaimSummary[]>(CLAIMS),
  getClaim: (claimId: string) => request<Claim>(claimPath(claimId)),
  listSteps: (claimId: string) =>
    request<Step[]>(`${claimPath(claimId)}/steps`),
  getPolicy: (policyId: string) =>
    request<Policy>(`/api/policies/${encodeURIComponent(policyId)}`),
  getClaimHistory: (customerId: string) =>
    request<PreviousClaim[]>(
      `/api/customers/${encodeURIComponent(customerId)}/claims`,
    ),
  getConfiguration: () => request<Configuration>(CONFIGURATION),
  getVersionDetails: (number: string) =>
    request<VersionDetails>(
      `${CONFIGURATION}/versions/${encodeURIComponent(number)}`,
    ),
  getSignedInHandler: () => request<Handler>("/api/me"),
  getSettings: () => request<SettingsPage>(SETTINGS),
  changeSettings: (values: SettingsValues) =>
    send<SettingsPage>("PUT", SETTINGS, values),
  getLatestDispatch: () => request<Run | null>(`${DISPATCHES}/latest`),
  startDispatch: (agents: number) => post<Accepted>(DISPATCHES, { agents }),
  listEvaluations: () => request<Evaluation[]>(EVALUATIONS),
  getEvaluation: (runId: string) =>
    request<ScoredEvaluation>(`${EVALUATIONS}/${encodeURIComponent(runId)}`),
  startEvaluation: (
    evaluationSet: EvaluationSet,
    tiny: boolean,
    agents: number,
  ) =>
    post<Accepted>(EVALUATIONS, {
      evaluation_set: evaluationSet,
      tiny,
      agents,
    }),
  signOff: (claimId: string) => post<Claim>(`${claimPath(claimId)}/sign-off`),
  sendBack: (claimId: string, note: string) =>
    post<Claim>(`${claimPath(claimId)}/send-back`, { note }),
  getImprovement: () => request<Improvement>(IMPROVEMENT),
  getRecipe: (number: string) =>
    request<RecipeDetails>(
      `${IMPROVEMENT}/recipes/${encodeURIComponent(number)}`,
    ),
  startRound: () => post<Accepted>(ROUNDS),
  stopRound: (roundId: string) =>
    post<RoundSummary>(`${roundPath(roundId)}/stop`),
  approveProposal: (roundId: string, proposalId: string) =>
    post<Accepted>(`${proposalPath(roundId, proposalId)}/approval`),
  rejectProposal: (roundId: string, proposalId: string, reason: string) =>
    post<Accepted>(`${proposalPath(roundId, proposalId)}/rejection`, {
      reason,
    }),
};
