// A claim as the backend gives it to the claim page, with its decision and
// the agent's steps, for the page's tests.

import type { Claim, Decision, Source, Step } from "./api";
import {
  claim,
  history,
  panel,
  policy,
  renderAt,
  type Routes,
  stubApi,
} from "./testing";

export const decidedAt = "2026-09-27T17:06:16+00:00";

// A step of the agent's work, from no context file unless it's a lookup.
export const step = (
  step_id: number,
  kind: Step["kind"],
  content: string,
  sources: Source[] = [],
): Step => ({
  step_id,
  thread_id: "t-1",
  kind,
  content,
  sources,
  created_at: decidedAt,
});

export function showClaim(shown: Claim, stepsShown: Step[] = []) {
  const routes: Routes = {
    "GET /api/claims/CLM-1002": shown,
    "GET /api/claims/CLM-1002/steps": stepsShown,
    "GET /api/policies/POL-2002": policy,
    "GET /api/customers/CUS-3002/claims": history,
  };
  const fetchMock = stubApi(routes);
  renderAt("/claims/CLM-1002");
  return { routes, fetchMock };
}

export const decisionPanel = () => panel("Decision");

export const approval: Decision = {
  decision: "approve",
  payout: 420,
  calculation: {
    lines: [
      { step: "Suitcase, limited to $300.00", amount: 300 },
      { step: "Clothes", amount: 170 },
      { step: "Less the deductible", amount: -50 },
    ],
    payout: 420,
  },
  section: "Section 5, Baggage and Personal Effects",
  reason: "The suitcase was lost by the carrier.",
  decided_by: "UnderCover Agent, version 1",
  decided_at: decidedAt,
  manual_version: "2026.2",
  signed_off_by: null,
  signed_off_at: null,
  gateway_refusal: null,
};

export const approved: Claim = {
  ...claim,
  status: "decided",
  thread_id: "t-1",
  decision: approval,
  payment: {
    amount: 420,
    paid_at: decidedAt,
    signed_off_by: null,
    signed_off_at: null,
  },
};

export const held: Claim = {
  ...approved,
  status: "waiting_for_sign_off",
  decision: { ...approval, payout: 1350 },
  payment: null,
};
