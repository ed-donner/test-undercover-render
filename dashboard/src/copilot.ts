import {
  BookOpen,
  Bot,
  Brain,
  FileText,
  type LucideIcon,
  Users,
  Zap,
} from "lucide-react";
import {
  type CardKind,
  type Conversation,
  type CopilotTurn,
  type TurnStatus,
  latestTurn,
} from "./conversation";
import { modelCost } from "./format";

// What the sidebar shows of each kind of card: its icon and what it's about.
export const CARD_KINDS: Record<CardKind, { icon: LucideIcon; label: string }> =
  {
    claims: { icon: FileText, label: "Claims" },
    customers: { icon: Users, label: "Customers and policies" },
    context: { icon: BookOpen, label: "The context layer" },
    work: { icon: Bot, label: "The agent's work" },
    memory: { icon: Brain, label: "Memory" },
    action: { icon: Zap, label: "Action" },
  };

// The Copilot's step that signs off a claim, whose card shows how a sign-off
// the handler confirmed went.
export const SIGN_OFF = "sign_off_claim";

// What this browser remembers of the sidebar for each handler: whether it is
// open, and the conversation open in it.
const OPEN = "undercover-copilot-open";
const CONVERSATION = "undercover-copilot-conversation";

const keyFor = (name: string, handlerId: string) => `${name}:${handlerId}`;

function read(name: string, handlerId: string): string | null {
  return localStorage.getItem(keyFor(name, handlerId));
}

function write(name: string, handlerId: string, value: string | undefined) {
  const key = keyFor(name, handlerId);
  if (value === undefined) localStorage.removeItem(key);
  else localStorage.setItem(key, value);
}

export function savedOpen(handlerId: string): boolean {
  return read(OPEN, handlerId) !== "false";
}

export function saveOpen(handlerId: string, open: boolean) {
  write(OPEN, handlerId, String(open));
}

export function savedConversation(handlerId: string): string | undefined {
  return read(CONVERSATION, handlerId) ?? undefined;
}

export function saveConversation(handlerId: string, id: string | undefined) {
  write(CONVERSATION, handlerId, id);
}

// How often the sidebar reads a conversation while the Copilot works on it.
export const ASK_EVERY_MS = 1000;
// The longest message the app takes.
export const MESSAGE_LENGTH = 4000;
// Below this width the sidebar opens over the page, and Escape closes it.
export const OVERLAY = "(width < 1100px)";
export const ASK = "Ask the Copilot";
export const STILL_WORKING = "The Copilot is working on your message";
export const ANSWER_FIRST = "Answer the confirmation first";
export const OPENING = "Opening the conversation";
export const STOPPED =
  "This turn stopped before it finished. Send a new message to carry on.";
export const NO_CONVERSATIONS =
  "No conversations yet. Ask the Copilot something to start one.";
export const SUGGESTED_QUESTIONS = [
  "What needs me today?",
  "How did the latest dispatch go?",
  "Are we meeting the success criteria we agreed?",
  "What does the policy wording say about baggage delays?",
];

// Why the message box can't take a message yet, if it can't.
export function waitingFor(conversation?: Conversation): string | undefined {
  const status = latestTurn(conversation)?.status;
  if (status === "working") return STILL_WORKING;
  if (status === "waiting_for_confirmation") return ANSWER_FIRST;
  return undefined;
}

// Where the latest turn stands, as a screen reader is told it.
export const TURN_STATES: Record<TurnStatus, string> = {
  working: "The Copilot is working",
  waiting_for_confirmation: "Waiting for your confirmation",
  done: "The Copilot answered",
  failed: "The Copilot couldn't finish",
  stopped: "The Copilot stopped",
};

// The small print under an answer: its model calls, their cost and its time.
export function smallPrint(turn: CopilotTurn): string {
  const calls = turn.model_calls ?? 0;
  const seconds = Math.round(turn.seconds ?? 0);
  return [
    `${String(calls)} model ${calls === 1 ? "call" : "calls"}`,
    modelCost(turn.cost ?? 0),
    `${String(seconds)} ${seconds === 1 ? "second" : "seconds"}`,
  ].join(", ");
}

export const SIGNING_OFF = "Signing off";
export const PAID = "Signed off and paid";
export const NOT_SIGNED_OFF = "Not signed off";
export const CANCELED = "Canceled";
export const NOT_KNOWN = "Not known";
export const NEVER_BEGAN = "The Copilot stopped before it signed off.";
export const MAY_HAVE_PAID =
  "The Copilot stopped while signing off, so its page says whether it was paid.";

export interface Outcome {
  tone: "pending" | "paid" | "canceled" | "refused" | "unknown";
  text: string;
  reason?: string | null;
}

// How a confirmation the handler answered went, read from the turn's own card
// for the sign-off, the first after the answer, as a turn signs off once: paid
// only once that card is done, never on an answer of Sign off alone; not signed
// off when the app refused it or it never began; and not known when it began
// but the turn ended without its result, since it may have paid.
export function outcomeOf(turn: CopilotTurn): Outcome {
  if (turn.confirmation_answer === "cancel")
    return { tone: "canceled", text: CANCELED, reason: turn.canceled_because };
  const answeredAt = turn.answered_at ?? "";
  const signOff = turn.steps.find(
    (step) => step.tool === SIGN_OFF && step.started_at >= answeredAt,
  );
  if (signOff?.status === "done") return { tone: "paid", text: PAID };
  if (signOff?.status === "refused")
    return { tone: "refused", text: NOT_SIGNED_OFF, reason: signOff.reason };
  if (turn.status === "working") return { tone: "pending", text: SIGNING_OFF };
  if (signOff)
    return {
      tone: "unknown",
      text: NOT_KNOWN,
      reason: signOff.reason ?? MAY_HAVE_PAID,
    };
  return {
    tone: "refused",
    text: NOT_SIGNED_OFF,
    reason: turn.failure ?? NEVER_BEGAN,
  };
}
