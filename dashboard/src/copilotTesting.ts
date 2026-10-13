import { screen, within } from "@testing-library/react";
import { saveConversation } from "./copilot";
import type { Conversation, CopilotStep, CopilotTurn } from "./conversation";
import { renderAt, stubApi } from "./testing";

// Builds the Copilot's conversations, turns and cards for the tests, as the app
// gives them.

export const CONVERSATIONS = "/api/copilot/conversations";
export const CONVERSATION_ID = "conversation-1";
export const CONVERSATION_PATH = `${CONVERSATIONS}/${CONVERSATION_ID}`;

export function step(changes: Partial<CopilotStep> = {}): CopilotStep {
  return {
    step_id: 1,
    tool: "get_claim",
    kind: "claims",
    input: "CLM-1012",
    asked: '{"claim_id": "CLM-1012"}',
    status: "done",
    answer: '{"claim_id": "CLM-1012", "status": "decided"}',
    reason: null,
    sources: [],
    started_at: "2026-10-10T09:00:01.000+00:00",
    finished_at: "2026-10-10T09:00:01.400+00:00",
    seconds: 0.4,
    ...changes,
  };
}

export function turn(changes: Partial<CopilotTurn> = {}): CopilotTurn {
  return {
    turn_id: "turn-1",
    number: 1,
    message: "What needs me today?",
    status: "done",
    started_at: "2026-10-10T09:00:00.000+00:00",
    paused_at: null,
    answered_at: null,
    finished_at: "2026-10-10T09:00:12.000+00:00",
    seconds: 12,
    answer: "Nothing needs you today.",
    model_calls: 4,
    cost: 0.0021,
    failure: null,
    confirmation: null,
    confirmation_answer: null,
    canceled_because: null,
    steps: [],
    ...changes,
  };
}

export function conversation(...turns: CopilotTurn[]): Conversation {
  return {
    conversation_id: CONVERSATION_ID,
    title: turns[0]?.message ?? "What needs me today?",
    created_at: "2026-10-10T09:00:00.000+00:00",
    turns,
  };
}

// A turn waiting for Dana to confirm the sign-off of CLM-1003.
export const confirmation = {
  claim_id: "CLM-1003",
  customer_name: "Lena Fischer",
  payout: 3750,
  reason: "The hospital bill is covered under section 7.",
};

export function waiting(changes: Partial<CopilotTurn> = {}): CopilotTurn {
  return turn({
    message: "Sign off CLM-1003",
    status: "waiting_for_confirmation",
    paused_at: "2026-10-10T09:00:05.000+00:00",
    finished_at: null,
    seconds: null,
    answer: null,
    model_calls: null,
    cost: null,
    confirmation,
    ...changes,
  });
}

// The handler opened a conversation in this browser before.
export function openedBefore(handlerId = "HND-01") {
  saveConversation(handlerId, CONVERSATION_ID);
}

export const sidebar = () =>
  within(screen.getByRole("complementary", { name: "Copilot" }));

export async function openSidebar() {
  return within(await screen.findByRole("complementary", { name: "Copilot" }));
}

// Dana opened the conversation with these turns before, and it shows in the
// sidebar beside the Settings page.
export function showConversation(...turns: CopilotTurn[]) {
  openedBefore();
  const fetchMock = stubApi({
    [`GET ${CONVERSATION_PATH}`]: conversation(...turns),
  });
  renderAt("/settings");
  return fetchMock;
}
