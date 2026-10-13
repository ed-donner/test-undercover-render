import { type APIRequestContext, expect } from "@playwright/test";
import type {
  DecisionKind,
  EvaluationSet,
  Improvement,
  Run,
  Source,
  StepKind,
} from "../dashboard/src/api";
import { HANDLERS, signedInAs } from "./handlers";
import { AGENT_KEY_HEADERS, AGENT_STAND_IN } from "./servers";

// Stands in for the agent's service and its claim agents, with one function for
// each backend operation the tests use, sent through the dashboard's proxy with
// the agent's key.
type Request = APIRequestContext;

const claimPath = (claimId: string) =>
  `/api/claims/${encodeURIComponent(claimId)}`;
const runPath = (runId: string) => `/api/runs/${runId}`;

// Sends a request as the agent's side does, with its key, and returns the
// backend's answer, which may be a refusal.
const asTheAgent = (
  request: Request,
  method: "POST" | "PUT",
  path: string,
  data: object = {},
) => request.fetch(path, { method, data, headers: AGENT_KEY_HEADERS });

async function send(
  request: Request,
  method: "POST" | "PUT",
  path: string,
  data: object = {},
) {
  const response = await asTheAgent(request, method, path, data);
  await expect(response).toBeOK();
  return response;
}

export const startClaim = (request: Request, claimId: string, thread: string) =>
  send(request, "POST", `${claimPath(claimId)}/start`, { thread_id: thread });

// Records a step, with the context files a lookup came from, and none for any
// other step.
export const recordStep = (
  request: Request,
  claimId: string,
  kind: StepKind,
  content: string,
  sources: Source[] = [],
) =>
  send(request, "POST", `${claimPath(claimId)}/steps`, {
    kind,
    content,
    sources,
  });

// Who makes the decisions the tests record, as the claim agent says it.
const MAKER = "UnderCover Agent, version 1";

interface DecisionRequest {
  decision: DecisionKind;
  payout: number;
  section: string;
  reason: string;
  decided_by: string;
}

const recordDecision = (
  request: Request,
  claimId: string,
  decision: DecisionRequest,
) => send(request, "POST", `${claimPath(claimId)}/decision`, decision);

const calculatePayout = (
  request: Request,
  claimId: string,
  payout: { benefit: string; lines: object[]; paid_by_others: number },
) => send(request, "POST", `${claimPath(claimId)}/payout`, payout);

// Works out the payout on one emergency medical bill, which the backend keeps
// for the claim's attempt, and returns what it pays.
async function payoutOnABill(request: Request, claimId: string, bill: number) {
  const response = await calculatePayout(request, claimId, {
    benefit: "emergency_medical",
    lines: [
      {
        description: "The covered costs",
        amount: bill,
        quantity: 1,
        kind: "expense",
        nights: 0,
        hours: 0,
      },
    ],
    paid_by_others: 0,
  });
  const { payout } = (await response.json()) as { payout: number };
  return payout;
}

// Records a decision as the claim agent does, with its maker. An approval's
// payout is worked out first: a bill for the payout alone shows the plan's
// deductible, and a bill for the payout and the deductible leaves exactly the
// payout on file.
export async function decide(
  request: Request,
  claimId: string,
  decision: Omit<DecisionRequest, "decided_by">,
) {
  if (decision.decision === "approve") {
    const deductible =
      decision.payout -
      (await payoutOnABill(request, claimId, decision.payout));
    await payoutOnABill(request, claimId, decision.payout + deductible);
  }
  return recordDecision(request, claimId, { ...decision, decided_by: MAKER });
}

// Asks to pay a claim and returns the backend's answer, which may be a refusal.
export const askToPay = (request: Request, claimId: string, amount: number) =>
  asTheAgent(request, "POST", `${claimPath(claimId)}/payment`, { amount });

export async function payClaim(
  request: Request,
  claimId: string,
  amount: number,
) {
  await expect(await askToPay(request, claimId, amount)).toBeOK();
}

export const failClaim = (request: Request, claimId: string, reason: string) =>
  send(request, "POST", `${claimPath(claimId)}/failure`, { reason });

export const recordModelCall = (
  request: Request,
  claimId: string,
  runId: string,
  cost: number,
) =>
  send(request, "POST", `${claimPath(claimId)}/model-calls`, {
    run_id: runId,
    input_tokens: 1200,
    output_tokens: 300,
    cost,
  });

export const recordWorkTime = (
  request: Request,
  claimId: string,
  runId: string,
  seconds: number,
) =>
  send(request, "POST", `${claimPath(claimId)}/work-times`, {
    run_id: runId,
    seconds,
  });

export async function createDispatch(
  request: Request,
  agents: number,
): Promise<Run> {
  const response = await send(request, "POST", "/api/runs/dispatches", {
    agents,
  });
  return (await response.json()) as Run;
}

export async function createEvaluation(
  request: Request,
  evaluationSet: EvaluationSet,
  tiny: boolean,
  agents: number,
): Promise<Run> {
  const response = await send(request, "POST", "/api/runs/evaluations", {
    evaluation_set: evaluationSet,
    tiny,
    agents,
  });
  return (await response.json()) as Run;
}

export const recordRunClaims = (
  request: Request,
  runId: string,
  claimIds: string[],
) => send(request, "PUT", `${runPath(runId)}/claims`, { claim_ids: claimIds });

export const finishRun = (request: Request, runId: string) =>
  send(request, "POST", `${runPath(runId)}/finish`);

// A round of the improver, played out as the agent's service would record it,
// for Dana Whitfield.
const ROUNDS = "/api/rounds";
const roundPath = (roundId: string) => `${ROUNDS}/${roundId}`;
const DANA = HANDLERS.dana.handler_id;

export async function createRound(request: Request): Promise<string> {
  const response = await send(request, "POST", ROUNDS, { handler_id: DANA });
  return ((await response.json()) as { round_id: string }).round_id;
}

export async function recordChangeProposal(
  request: Request,
  roundId: string,
  instructions: string,
): Promise<string> {
  const response = await send(
    request,
    "POST",
    `${roundPath(roundId)}/proposals/change`,
    {
      instructions,
      model: "openai/gpt-6-luna",
      reasoning_effort: "low",
      reason: "Two stolen phones were approved without a police report",
    },
  );
  return ((await response.json()) as { proposal_id: string }).proposal_id;
}

export async function recordRecipeProposal(
  request: Request,
  roundId: string,
): Promise<string> {
  const response = await send(
    request,
    "POST",
    `${roundPath(roundId)}/proposals/recipe`,
    { recipe: "1. Read the results.\n", reason: "A shorter recipe" },
  );
  return ((await response.json()) as { proposal_id: string }).proposal_id;
}

export const recordReview = (
  request: Request,
  roundId: string,
  proposalId: string,
  review: "approved" | "rejected",
  reason = "",
) =>
  send(
    request,
    "POST",
    `${roundPath(roundId)}/proposals/${proposalId}/review`,
    { review, handler_id: DANA, reason },
  );

export const createVersion = (request: Request, roundId: string) =>
  send(request, "POST", `${roundPath(roundId)}/version`);

export const finishRound = (request: Request, roundId: string) =>
  send(request, "POST", `${roundPath(roundId)}/finish`);

// Finishes the open round, if any, rejecting a proposal it's waiting on first,
// so the next test can start one. It reads the round as Dana, as the dashboard
// does.
export async function finishOpenRound(request: Request) {
  const response = await request.get("/api/improvement", {
    headers: await signedInAs(request, HANDLERS.dana),
  });
  await expect(response).toBeOK();
  const { round } = (await response.json()) as Improvement;
  if (round?.status !== "open") return;
  if (round.waiting)
    await recordReview(
      request,
      round.round_id,
      round.waiting.proposal_id,
      "rejected",
      "The test is over",
    );
  await finishRound(request, round.round_id);
}

export interface Started {
  path: string;
  body: unknown;
}

export async function started(request: Request): Promise<Started[]> {
  const response = await request.get(`${AGENT_STAND_IN}/api/started`);
  await expect(response).toBeOK();
  return (await response.json()) as Started[];
}

export async function reviews(request: Request): Promise<Started[]> {
  const response = await request.get(`${AGENT_STAND_IN}/api/reviews`);
  await expect(response).toBeOK();
  return (await response.json()) as Started[];
}
