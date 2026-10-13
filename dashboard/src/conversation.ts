import type { Source } from "./sources";

// The Copilot's conversations, each turn and its cards.
export type TurnStatus =
  | "working"
  | "waiting_for_confirmation"
  | "done"
  | "failed"
  // A turn still working long after it started, which the app reads as stopped.
  | "stopped";
export type CardKind =
  "claims" | "customers" | "context" | "work" | "memory" | "action";
export type CardStatus = "working" | "done" | "refused" | "failed";
export type ConfirmationAnswer = "sign_off" | "cancel";

// A sign-off waiting for the handler's confirmation, from the app's records.
export interface Confirmation {
  claim_id: string;
  customer_name: string;
  payout: number;
  reason: string;
}

// A card: one tool the Copilot called, what was asked and what came back.
export interface CopilotStep {
  step_id: number;
  tool: string;
  kind: CardKind;
  // The tool's main input, such as CLM-1012.
  input: string;
  asked: string;
  status: CardStatus;
  answer: string | null;
  reason: string | null;
  sources: Source[];
  started_at: string;
  finished_at: string | null;
  // So far, while it works.
  seconds: number;
}

export interface CopilotTurn {
  turn_id: string;
  number: number;
  message: string;
  status: TurnStatus;
  started_at: string;
  paused_at: string | null;
  answered_at: string | null;
  finished_at: string | null;
  // Once it has finished, leaving out the wait for the handler.
  seconds: number | null;
  answer: string | null;
  model_calls: number | null;
  cost: number | null;
  failure: string | null;
  confirmation: Confirmation | null;
  confirmation_answer: ConfirmationAnswer | null;
  canceled_because: string | null;
  steps: CopilotStep[];
}

export interface ConversationSummary {
  conversation_id: string;
  // The first message.
  title: string;
  created_at: string;
}

export interface Conversation extends ConversationSummary {
  turns: CopilotTurn[];
}

// The conversation's latest turn, if it has one.
export function latestTurn(
  conversation?: Conversation | null,
): CopilotTurn | undefined {
  return conversation?.turns.at(-1);
}

// Whether the Copilot is working on the conversation's latest turn, which is
// what the sidebar keeps asking about.
export function stillWorking(conversation?: Conversation | null): boolean {
  return latestTurn(conversation)?.status === "working";
}
