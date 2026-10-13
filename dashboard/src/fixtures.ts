import type {
  Configuration,
  Evaluation,
  Run,
  RunClaim,
  ScoredClaim,
  ScoredEvaluation,
  VersionDetails,
  VersionSummary,
} from "./api";
import { summary } from "./testing";

// What the backend gives the pages, for the tests of more than one page: a
// dispatch at work, evaluations, and the claim agent's versions.
export const waitingInRun: RunClaim = {
  ...summary,
  claim_id: "CLM-1013",
  customer_name: "Grace Liu",
  started_at: null,
  seconds: 0,
  model_cost: 0,
};

export const runningDispatch: Run = {
  run_id: "run-4",
  number: 4,
  kind: "dispatch",
  agents: 3,
  version: 1,
  round_id: null,
  round_number: null,
  model: "openai/gpt-6-luna",
  reasoning_effort: "low",
  evaluation_set: null,
  tiny: null,
  status: "running",
  started_at: "2026-10-03T17:02:13+00:00",
  finished_at: null,
  seconds: null,
  summary: null,
  model_cost: 0.0125,
  claims: [
    {
      ...waitingInRun,
      claim_id: "CLM-1001",
      customer_name: "Maya Patel",
      status: "decided",
      decision: "approve",
      payout: 420,
      started_at: "2026-10-03T17:02:14+00:00",
      seconds: 41,
      model_cost: 0.0125,
    },
    {
      ...waitingInRun,
      claim_id: "CLM-1014",
      status: "in_progress",
      seconds: 12,
    },
    waitingInRun,
  ],
};

export const finishedEvaluation: Evaluation = {
  run_id: "run-7",
  number: 7,
  kind: "evaluation",
  agents: 25,
  version: 1,
  round_id: null,
  round_number: null,
  model: "openai/gpt-6-luna",
  reasoning_effort: "low",
  evaluation_set: "evaluation",
  tiny: false,
  status: "finished",
  started_at: "2026-10-03T17:02:13+00:00",
  finished_at: "2026-10-03T17:04:54+00:00",
  seconds: 161,
  model_cost: 0.3125,
  judge_cost: 0.0005,
  size: 25,
  measures: {
    decision_accuracy: 0.8,
    accuracy: 0.64,
    cost_of_mistakes: 1600,
    straight_through: 0.88,
    grade: 2.2,
    model_cost_per_claim: 0.0125,
    seconds_per_claim: 40,
    run_seconds: 161,
  },
};

export const scoredCopy: ScoredClaim = {
  ...summary,
  claim_id: "CLM-1104-E9",
  started_at: "2026-10-03T17:02:14+00:00",
  seconds: 40,
  model_cost: 0.0125,
  status: "decided",
  decision: "approve",
  payout: 250,
  copy_of: "CLM-1104",
  reason: "The delay was covered.",
  handler_decision: "approve",
  handler_payout: 250,
  right: true,
  mistake_cost: 0,
  grade: {
    score: 2.2,
    letter: "B",
    same_grounds: 0.8,
    same_section: 0.3,
    cost: 0.0001,
  },
};

export const scoredEvaluation: ScoredEvaluation = {
  ...finishedEvaluation,
  run_id: "run-9",
  number: 9,
  evaluation_set: "held_out",
  tiny: true,
  size: 5,
  claims: [
    scoredCopy,
    {
      ...scoredCopy,
      claim_id: "CLM-1112-E9",
      copy_of: "CLM-1112",
      status: "waiting_for_sign_off",
      payout: 1200,
      handler_payout: 680,
      right: false,
      mistake_cost: 520,
    },
    {
      ...scoredCopy,
      claim_id: "CLM-1114-E9",
      copy_of: "CLM-1114",
      status: "in_progress",
      decision: null,
      payout: null,
      reason: null,
      handler_decision: "decline",
      handler_payout: 0,
      right: false,
      mistake_cost: 50,
      grade: null,
    },
  ],
};

export const firstVersion: VersionSummary = {
  number: 1,
  status: "kept",
  model: "openai/gpt-6-luna",
  reasoning_effort: "low",
  model_before: null,
  reasoning_effort_before: null,
  based_on: null,
  lines_added: 0,
  lines_removed: 0,
  reason: "The claim agent as the claims team built it",
  proposed_by: "The claims team",
  round_id: null,
  approved_by: null,
  approved_at: null,
  created_at: "2026-10-04T09:00:00+00:00",
  verdict: "kept",
  verdict_reason: "the first version",
  scores: { evaluation: null, held_out: null },
};

export const secondVersion: VersionSummary = {
  ...firstVersion,
  number: 2,
  status: "current",
  model: "google/gemini-3.5-flash-lite",
  reasoning_effort: "minimal",
  model_before: "openai/gpt-6-luna",
  reasoning_effort_before: "low",
  based_on: 1,
  lines_added: 12,
  lines_removed: 3,
  reason: "Add a rule for stolen phones",
  proposed_by: "Round 1",
  approved_by: "Dana Whitfield",
  approved_at: "2026-10-05T14:05:00+00:00",
};

export const configuration: Configuration = {
  current: 2,
  versions: [secondVersion, firstVersion],
};

export const versionDetails: VersionDetails = {
  ...secondVersion,
  instructions: "# Working a claim\n\n## Contents of the claims manual",
  diff: {
    added: 1,
    removed: 1,
    hunks: [
      [
        { kind: "context", text: "Read the claim." },
        { kind: "removed", text: "Refer a stolen phone." },
        { kind: "added", text: "Decline a phone left unattended." },
      ],
      [{ kind: "context", text: "Record the decision." }],
    ],
  },
};
