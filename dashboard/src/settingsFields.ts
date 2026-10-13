import { MOST_AGENTS } from "./components/AgentsChoice";
import type { Settings, SettingsValues } from "./api";
import { grade, money } from "./format";

// How the Settings page shows each setting: its group, its label, its unit and
// its limits. Accuracy and the fractions of cost and time are kept from 0 to 1
// and typed as percentages.
export type Unit = "dollars" | "percent" | "grade" | "agents";

export interface SettingField {
  id: string;
  group: SettingGroup;
  // Its label in its group, and its name on its own, in a list of changes.
  label: string;
  name: string;
  unit: Unit;
  // The most a handler may type, in the unit shown, when there's a most.
  max?: number;
  get: (values: SettingsValues) => number;
  set: (values: SettingsValues, value: number) => SettingsValues;
}

// Each unit as a handler types it: what goes before or after the number, the
// smallest number allowed and the step, and how it's rounded once typed.
export const UNITS: Record<
  Unit,
  { prefix?: string; suffix?: string; min: number; step: number }
> = {
  dollars: { prefix: "$", min: 0.01, step: 0.01 },
  percent: { suffix: "%", min: 0, step: 0.1 },
  grade: { suffix: "of 3", min: 0, step: 0.01 },
  agents: { min: 1, step: 1 },
};

export const settingGroups = [
  "approval",
  "objectives",
  "noise",
  "tolerance",
  "spending",
  "evaluations",
] as const;
export type SettingGroup = (typeof settingGroups)[number];

export const GROUPS: Record<SettingGroup, { title: string; lead: string }> = {
  approval: {
    title: "Approval",
    lead: "Payouts over the limit wait for a senior handler's sign-off. A new limit applies to later decisions only.",
  },
  objectives: {
    title: "Objectives on the held-out set",
    lead: "The lowest scores a new version of the claim agent can have and be kept.",
  },
  noise: {
    title: "Noise",
    lead: "The smallest improvement that counts. Accuracy and grade are in points; cost and time are a share of the old value.",
  },
  tolerance: {
    title: "Tolerance",
    lead: "How much a measure can get worse when another improves.",
  },
  spending: {
    title: "Spending",
    lead: "The most one round of the improver can spend, including its evaluations and the judge.",
  },
  evaluations: {
    title: "The improver's evaluations",
    lead: "How many claim agents work at once in a round's evaluations.",
  },
};

type Measure = keyof SettingsValues["noise"];

const MEASURES: { measure: Measure; label: string; unit: Unit }[] = [
  { measure: "accuracy", label: "Accuracy", unit: "percent" },
  { measure: "grade", label: "Grade", unit: "grade" },
  { measure: "cost_per_claim", label: "Model cost per claim", unit: "percent" },
  { measure: "seconds_per_claim", label: "Time per claim", unit: "percent" },
];

function measureFields(group: "noise" | "tolerance"): SettingField[] {
  return MEASURES.map(({ measure, label, unit }) => ({
    id: `${group}.${measure}`,
    group,
    label,
    name: `${GROUPS[group].title} on ${label.toLowerCase()}`,
    unit,
    get: (values) => values[group][measure],
    set: (values, value) => ({
      ...values,
      [group]: { ...values[group], [measure]: value },
    }),
  }));
}

export const SETTING_FIELDS: SettingField[] = [
  {
    id: "approval_limit",
    group: "approval",
    label: "Approval limit",
    name: "Approval limit",
    unit: "dollars",
    get: (values) => values.approval_limit,
    set: (values, value) => ({ ...values, approval_limit: value }),
  },
  {
    id: "objectives.accuracy",
    group: "objectives",
    label: "Accuracy at least",
    name: "Accuracy objective",
    unit: "percent",
    max: 100,
    get: (values) => values.objectives.accuracy,
    set: (values, value) => ({
      ...values,
      objectives: { ...values.objectives, accuracy: value },
    }),
  },
  {
    id: "objectives.grade",
    group: "objectives",
    label: "Grade at least",
    name: "Grade objective",
    unit: "grade",
    max: 3,
    get: (values) => values.objectives.grade,
    set: (values, value) => ({
      ...values,
      objectives: { ...values.objectives, grade: value },
    }),
  },
  ...measureFields("noise"),
  ...measureFields("tolerance"),
  {
    id: "spending_limit",
    group: "spending",
    label: "Spending limit for each round",
    name: "Spending limit for each round",
    unit: "dollars",
    get: (values) => values.spending_limit,
    set: (values, value) => ({ ...values, spending_limit: value }),
  },
  {
    id: "agents",
    group: "evaluations",
    label: "Claim agents at once",
    name: "Claim agents at once in the improver's evaluations",
    unit: "agents",
    max: MOST_AGENTS,
    get: (values) => values.agents,
    set: (values, value) => ({ ...values, agents: value }),
  },
];

// A setting as a handler types it: dollars to the cent, grades as they are,
// and shares as percentages to a tenth.
export function toInput(unit: Unit, value: number): string {
  if (unit === "dollars") return value.toFixed(2);
  if (unit === "percent") return String(Math.round(value * 1000) / 10);
  return String(value);
}

// A setting as typed, rounded to what the page shows.
export function fromInput(unit: Unit, input: string): number {
  const value = Number(input);
  if (unit === "dollars") return Math.round(value * 100) / 100;
  if (unit === "percent") return Math.round(value * 10) / 1000;
  if (unit === "grade") return Math.round(value * 100) / 100;
  return Math.round(value);
}

// A setting as the page shows it, with its unit.
export function shown(unit: Unit, value: number): string {
  if (unit === "dollars") return money(value);
  if (unit === "percent") return `${toInput(unit, value)}%`;
  if (unit === "grade") return `${grade(value)} of 3`;
  return String(value);
}

export type Inputs = Record<string, string>;

export function inputsOf(values: SettingsValues): Inputs {
  return Object.fromEntries(
    SETTING_FIELDS.map((field) => [
      field.id,
      toInput(field.unit, field.get(values)),
    ]),
  );
}

// The settings alone, without who changed them and when.
function valuesOnly(settings: Settings): SettingsValues {
  return {
    approval_limit: settings.approval_limit,
    objectives: settings.objectives,
    noise: settings.noise,
    tolerance: settings.tolerance,
    spending_limit: settings.spending_limit,
    agents: settings.agents,
  };
}

// The settings as typed: a setting whose input wasn't touched keeps its value
// exactly, so saving never changes what a handler didn't.
export function valuesOf(current: Settings, inputs: Inputs): SettingsValues {
  return SETTING_FIELDS.reduce((values, field) => {
    const input = inputs[field.id] ?? "";
    return input === toInput(field.unit, field.get(current))
      ? values
      : field.set(values, fromInput(field.unit, input));
  }, valuesOnly(current));
}

// Each setting that differs between two sets of values, from the old to the
// new, as the page shows them.
export function changesBetween(
  before: SettingsValues,
  after: SettingsValues,
): string[] {
  return SETTING_FIELDS.filter(
    (field) => field.get(before) !== field.get(after),
  ).map(
    (field) =>
      `${field.name}: ${shown(field.unit, field.get(before))} to ${shown(field.unit, field.get(after))}`,
  );
}
