import type { Measures } from "./api";
import { duration, grade, modelCost, money, percent } from "./format";

// A run that's running or stopped has no run time.
const NOT_FINISHED = "Not finished";
export const NOT_GRADED = "Not graded";

// The scoreboard's measures, in order, each with how it's shown.
export const MEASURES: {
  label: string;
  show: (measures: Measures) => string;
}[] = [
  { label: "Decision accuracy", show: (m) => percent(m.decision_accuracy) },
  { label: "Accuracy", show: (m) => percent(m.accuracy) },
  { label: "Cost of mistakes", show: (m) => money(m.cost_of_mistakes) },
  { label: "Straight-through", show: (m) => percent(m.straight_through) },
  {
    label: "Grade (of 3)",
    show: (m) => (m.grade === null ? NOT_GRADED : grade(m.grade)),
  },
  {
    label: "Model cost per claim",
    show: (m) => modelCost(m.model_cost_per_claim),
  },
  { label: "Time per claim", show: (m) => duration(m.seconds_per_claim) },
  {
    label: "Run time",
    show: (m) =>
      m.run_seconds === null ? NOT_FINISHED : duration(m.run_seconds),
  },
];
