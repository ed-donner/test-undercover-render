import type {
  Evaluation,
  Improvement,
  Measures,
  RecipeDetails,
  RoundView,
  WaitingProposal,
} from "./api";
import { renderAt, type Routes, stubApi } from "./testing";

// A round of the improver as the backend gives it to the Improvement page, for
// the page's tests.
export const ROUND_ID = "round-1";
export const PROPOSAL_ID = "proposal-2";
export const START = "POST /api/improvement/rounds";
export const APPROVAL = `POST /api/improvement/rounds/${ROUND_ID}/proposals/${PROPOSAL_ID}/approval`;
export const REJECTION = `POST /api/improvement/rounds/${ROUND_ID}/proposals/${PROPOSAL_ID}/rejection`;

export function measures(accuracy: number, grade: number | null): Measures {
  return {
    decision_accuracy: accuracy,
    accuracy,
    cost_of_mistakes: 0,
    straight_through: 1,
    grade,
    model_cost_per_claim: 0.002,
    seconds_per_claim: 20,
    run_seconds: 60,
  };
}

export const evaluation: Evaluation = {
  run_id: "run-3",
  number: 3,
  kind: "evaluation",
  agents: 25,
  version: 1,
  round_id: ROUND_ID,
  round_number: 1,
  model: "openai/gpt-6-luna",
  reasoning_effort: "low",
  status: "finished",
  stopped_because: null,
  started_at: "2026-10-04T09:00:00+00:00",
  finished_at: "2026-10-04T09:02:00+00:00",
  seconds: 120,
  model_cost: 0.05,
  evaluation_set: "held_out",
  tiny: false,
  size: 25,
  judge_cost: 0.002,
  measures: measures(0.6, 1.5),
};

export const change: WaitingProposal = {
  proposal_id: PROPOSAL_ID,
  kind: "change",
  reason: "Two stolen phones were approved without a police report",
  proposed_at: "2026-10-04T09:10:00+00:00",
  diff: {
    added: 1,
    removed: 0,
    hunks: [
      [
        { kind: "context", text: "# Working a claim" },
        { kind: "added", text: "A stolen phone needs a police report." },
      ],
    ],
  },
  model_before: "openai/gpt-6-luna",
  reasoning_effort_before: "low",
  model_after: "google/gemini-3.5-flash-lite",
  reasoning_effort_after: "minimal",
};

export const open: RoundView = {
  round_id: ROUND_ID,
  number: 1,
  status: "open",
  stage: "change_waiting",
  progress: null,
  started_by: "Dana Whitfield",
  started_at: "2026-10-04T09:00:00+00:00",
  finished_at: null,
  stopped_by: null,
  stopped_because: null,
  recipe: 1,
  settings: 1,
  spending_limit: 0.5,
  cost: 0.1234,
  version: null,
  model: null,
  reasoning_effort: null,
  reason: null,
  verdict: null,
  verdict_reason: null,
  held_out_before: null,
  held_out_after: null,
  reviews: [],
  waiting: change,
  evaluations: [evaluation],
};

export const empty: Improvement = {
  round: null,
  rounds: [],
  first_version: { number: 1, verdict: null, accuracy: null, grade: null },
  versions_tried: [],
  recipes: [
    {
      number: 1,
      current: true,
      reason: "The lab's recipe",
      proposed_by: "The claims team",
      round_id: null,
      approved_by: null,
      approved_at: null,
      created_at: "2026-10-04T08:00:00+00:00",
      lines_added: 0,
      lines_removed: 0,
    },
  ],
};

export function improvement(
  round: RoundView | null,
  more: Partial<Improvement> = {},
) {
  return {
    ...empty,
    round,
    rounds: round ? [round] : [],
    ...more,
  };
}

// Shows the Improvement page with the backend answering from the routes given,
// which a test may change to play out what the next refresh brings.
export function showPage(page: Improvement, routes: Routes = {}) {
  routes["GET /api/improvement"] ??= page;
  const fetchMock = stubApi(routes);
  renderAt("/improvement");
  return fetchMock;
}

// Recipe 1 as its page shows it.
export const firstRecipe: RecipeDetails = {
  ...empty.recipes[0],
  recipe: "1. Read the results.\n",
  diff: null,
};

// A round that finished with its version kept.
export const finishedRound = {
  ...open,
  status: "finished",
  stage: null,
  waiting: null,
  version: 2,
  reason: "Two stolen phones were approved",
  verdict: "kept",
  verdict_reason: "accuracy improved",
  held_out_before: measures(0.6, 1.5),
  held_out_after: measures(0.72, 1.9),
} as const;
