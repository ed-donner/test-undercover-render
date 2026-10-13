import type {
  DecisionKind,
  EvaluationSet,
  RoundStage,
  RoundStatus,
  RoundSummary,
  RunStatus,
  Source,
  Status,
  Verdict,
  VersionStatus,
} from "./api";

const dollars = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
});

const day = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  year: "numeric",
  timeZone: "UTC",
});

const dayAndClock = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
});

const clock = new Intl.DateTimeFormat("en-US", {
  hour: "numeric",
  minute: "2-digit",
  second: "2-digit",
});

// Model costs are often under a cent.
const modelDollars = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 4,
  maximumFractionDigits: 4,
});

// A context file's source as a handler reads it, such as "Claims operations,
// owned by the Head of claims operations, reviewed Sep 1, 2026". An owner that
// is a role, a head of something, is "the" head.
export function sourceOf(source: Source): string {
  const owner = source.owner.startsWith("Head of ")
    ? `the ${source.owner}`
    : source.owner;
  return `${source.system}, owned by ${owner}, reviewed ${date(source.reviewed)}`;
}

export function money(amount: number): string {
  return dollars.format(amount);
}

// A share, such as 0.8, as a whole percentage: 80%.
export function percent(share: number): string {
  return `${String(Math.round(share * 100))}%`;
}

// The judge's grade, from 0 to 3, to two places: 2.20.
export function grade(score: number): string {
  return score.toFixed(2);
}

export function modelCost(amount: number): string {
  return modelDollars.format(amount);
}

// A length of time, such as 41 s or 2 min 41 s.
export function duration(seconds: number): string {
  const whole = Math.round(seconds);
  const minutes = Math.floor(whole / 60);
  const rest = `${String(whole % 60)} s`;
  if (minutes === 0) return rest;
  return whole % 60 === 0
    ? `${String(minutes)} min`
    : `${String(minutes)} min ${rest}`;
}

export function date(isoDate: string): string {
  return day.format(new Date(`${isoDate}T00:00:00Z`));
}

export function time(isoTime: string): string {
  return clock.format(new Date(isoTime));
}

export function dateTime(isoTime: string): string {
  return dayAndClock.format(new Date(isoTime));
}

export function agentsAtOnce(agents: number): string {
  return `${String(agents)} claim ${agents === 1 ? "agent" : "agents"} at once`;
}

// A handler's initials, from their first and last names, such as DW for Dana
// Whitfield.
export function initials(name: string): string {
  const [first = "", ...rest] = name.split(" ");
  const last = rest.at(-1) ?? "";
  return (first.charAt(0) + last.charAt(0)).toUpperCase();
}

export function label(code: string): string {
  const words = code.replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export const statusLabels: Record<Status, string> = {
  waiting: "Waiting",
  in_progress: "In progress",
  waiting_for_sign_off: "Waiting for sign-off",
  sent_back: "Sent back",
  decided: "Decided",
  left_for_handler: "Left for a handler",
};

export const runLabels: Record<RunStatus, string> = {
  running: "Running",
  finished: "Finished",
  stopped: "Stopped",
};

export const versionLabels: Record<VersionStatus, string> = {
  current: "Current",
  kept: "Kept",
  rolled_back: "Rolled back",
  under_test: "Under test",
};

// Who approved a version or a recipe that needed no approval.
export const NO_APPROVAL_NEEDED = "Nobody needed to";

export const roundLabels: Record<RoundStatus, string> = {
  open: "Open",
  finished: "Finished",
  stopped: "Stopped",
};

// A verdict keeps or rolls back a version, so it reads as the version's status.
export const verdictLabels: Record<Verdict, string> = {
  kept: versionLabels.kept,
  rolled_back: versionLabels.rolled_back,
};

// Each stage of a round in order, as the page names it in the round's progress.
export const stageLabels: Record<RoundStage, string> = {
  first_evaluations: "First evaluations",
  improving: "The improver is working",
  change_waiting: "A change is waiting for approval",
  evaluating: "Evaluations",
  verdict: "Verdict",
  recipe_waiting: "A new recipe is waiting for approval",
};
export const roundStages = Object.keys(stageLabels) as RoundStage[];

// A verdict's reason in words: the rule names measures such as cost_per_claim.
export function inWords(reason: string | null): string {
  return (reason ?? "").replaceAll("_", " ");
}

// Why a run stopped, as a sentence: "Stopped: The agent stopped answering." A
// reason that already ends with a stop, as an error's message may, keeps it.
export function stoppedBecause(reason: string): string {
  return `Stopped: ${reason}${/[.!?]$/.test(reason) ? "" : "."}`;
}

// Where an open round has got to, such as "First evaluations, 2 of 3", or
// "Kept: accuracy improved" once its verdict is in.
export function whereRoundIs(round: RoundSummary): string {
  if (round.stage === null) return "";
  if (round.stage === "verdict" && round.verdict)
    return `${verdictLabels[round.verdict]}: ${inWords(round.verdict_reason)}`;
  const name = stageLabels[round.stage];
  return round.progress ? `${name}, ${round.progress}` : name;
}

export const evaluationSetLabels: Record<EvaluationSet, string> = {
  evaluation: "Evaluation set",
  held_out: "Held-out set",
};

export function evaluationSetName(set: EvaluationSet, size: number): string {
  return `${evaluationSetLabels[set]}, ${String(size)} claims`;
}

export const decisionLabels: Record<DecisionKind, string> = {
  approve: "Approved",
  decline: "Declined",
  refer: "Referred",
};

const addOnNames: Record<string, string> = {
  adventure_sports: "Adventure Sports",
  pre_existing_waiver: "Pre-Existing Condition Waiver",
  electronics_plus: "Electronics Plus",
};

export function addOnName(code: string): string {
  return addOnNames[code] ?? label(code);
}
