import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { Claim, Evaluation } from "./api";
import { Check } from "./components/Judging";
import {
  finishedEvaluation as finished,
  scoredEvaluation as scored,
} from "./fixtures";
import {
  Refusal,
  type Routes,
  claim,
  history,
  panel,
  policy,
  renderAt,
  sent,
  stubApi,
  summary,
} from "./testing";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const running: Evaluation = {
  ...finished,
  run_id: "run-9",
  number: 9,
  agents: 5,
  evaluation_set: "held_out",
  tiny: true,
  status: "running",
  finished_at: null,
  seconds: null,
  size: 5,
  measures: { ...finished.measures, grade: null, run_seconds: null },
};

function showScoreboard(routes: Routes = {}) {
  const fetchMock = stubApi({
    "GET /api/evaluations": [running, finished],
    ...routes,
  });
  renderAt("/scoreboard");
  return fetchMock;
}

it("lists the evaluations in the backend's order, with their measures", async () => {
  showScoreboard();
  const list = await panel("Evaluations");
  const rows = (await list.findAllByRole("row")).slice(1);
  expect(
    rows.map((row) => within(row).getAllByRole("link")[0].textContent),
  ).toEqual(["Evaluation #9", "Evaluation #7"]);
  const [newest, older] = rows.map((row) => within(row));
  expect(newest.getByText("Held-out set, 5 claims")).toBeDefined();
  expect(newest.getByText("Running")).toBeDefined();
  expect(older.getByText("Evaluation set, 25 claims")).toBeDefined();
  expect(older.getByText("openai/gpt-6-luna")).toBeDefined();
  for (const shown of [
    "80%",
    "64%",
    "$1,600.00",
    "88%",
    "2.20",
    "$0.0125",
    "40 s",
  ])
    expect(older.getByText(shown)).toBeDefined();
  expect(newest.getByText("Not graded")).toBeDefined();
  expect(older.getByText("2 min 41 s")).toBeDefined();
  expect(newest.queryByText("2 min 41 s")).toBeNull();
  expect(
    older.getByText(/Oct 3, .*, version 1, 25 claim agents at once/),
  ).toBeDefined();
  const link = older.getByRole("link", { name: "Evaluation #7" });
  expect(link.getAttribute("href")).toBe("/scoreboard/run-7");
});

it("says when there are no evaluations yet", async () => {
  stubApi({ "GET /api/evaluations": [] });
  renderAt("/scoreboard");
  expect(
    await screen.findByText(/^No evaluations yet\. Start one above/),
  ).toBeDefined();
});

it("starts an evaluation with the choices made", async () => {
  const fetchMock = showScoreboard({
    "POST /api/evaluations": { status: "accepted" },
  });
  const form = await panel("Start an evaluation");
  const set = form.getByRole("combobox", { name: "Set" });
  const claims = form.getByRole("combobox", { name: "Claims" });
  const agents = form.getByRole("combobox", { name: "Claim agents at once" });
  expect(
    [set, claims, agents].map((c) => (c as HTMLSelectElement).value),
  ).toEqual(["evaluation", "all", "3"]);

  fireEvent.change(set, { target: { value: "held_out" } });
  fireEvent.change(claims, { target: { value: "tiny" } });
  fireEvent.change(agents, { target: { value: "5" } });
  fireEvent.click(form.getByRole("button", { name: "Start an evaluation" }));
  await waitFor(() => {
    expect(sent(fetchMock, "POST /api/evaluations")).toEqual([
      { evaluation_set: "held_out", tiny: true, agents: 5 },
    ]);
  });
});

it.each([
  [409, "A dispatch is running"],
  [503, "The agent's service isn't running"],
])("shows a refusal with status %i", async (status, detail) => {
  showScoreboard({ "POST /api/evaluations": new Refusal(status, detail) });
  const form = await panel("Start an evaluation");
  fireEvent.click(form.getByRole("button", { name: "Start an evaluation" }));
  expect((await form.findByRole("alert")).textContent).toBe(detail);
});

it("shows an evaluation's claims beside the handlers' decisions", async () => {
  stubApi({ "GET /api/evaluations/run-9": scored });
  renderAt("/scoreboard/run-9");
  expect(
    await screen.findByRole("heading", { name: "Evaluation #9", level: 1 }),
  ).toBeDefined();
  const measures = await panel("Measures");
  const shown = (label: string) =>
    measures.getByText(label).nextSibling?.textContent;
  expect(shown("Decision accuracy")).toBe("80%");
  expect(shown("Run time")).toBe("2 min 41 s");
  expect(shown("Grade (of 3)")).toBe("2.20");
  expect(measures.getByText(/judge cost/).textContent).toContain(
    "Model cost $0.3125 and judge cost $0.0005.",
  );
  const rows = (await panel("Claims")).getAllByRole("row").slice(1);
  const [right, held, undecided] = rows.map((row) => within(row));
  expect(right.getByText("Right").className).toBe("chip score-right");
  expect(right.getByText("B").className).toBe("chip grade-B");
  expect(right.getByText("2.20")).toBeDefined();
  const column = (name: string) =>
    within(screen.getByRole("region", { name: "Claims" }))
      .getAllByRole("columnheader")
      .findIndex((header) => header.textContent === name);
  const cells = right.getAllByRole("cell");
  expect(cells[column("Same grounds")].textContent).toBe("Yes");
  expect(cells[column("Same section")].textContent).toBe("No");
  expect(undecided.getByText("Not graded")).toBeDefined();
  expect(right.getAllByText("$250.00")).toHaveLength(2);
  expect(held.getByText("Miss").className).toBe("chip score-miss");
  expect(held.getByText("$680.00")).toBeDefined();
  expect(held.getByText("$1,200.00")).toBeDefined();
  expect(held.getByText("$520.00")).toBeDefined();
  expect(undecided.getByText("No decision")).toBeDefined();
  expect(undecided.getByText("Declined")).toBeDefined();
  expect(undecided.getByText("Miss")).toBeDefined();
  const link = right.getByRole("link", { name: "CLM-1104-E9" });
  expect(link.getAttribute("href")).toBe("/claims/CLM-1104-E9");
});

it("says when an evaluation doesn't exist", async () => {
  stubApi({});
  renderAt("/scoreboard/run-404");
  expect(
    await screen.findByText(
      "Evaluation not found. Choose one on the Scoreboard.",
    ),
  ).toBeDefined();
});

it("shows a copy's evaluation, and no sign-off for a held copy", async () => {
  const heldCopy: Claim = {
    ...claim,
    claim_id: "CLM-1112-E9",
    status: "waiting_for_sign_off",
    thread_id: "t-1",
    attempts: 1,
    evaluation_id: "run-9",
    copy_of: "CLM-1112",
    decision: {
      decision: "approve",
      payout: 1200,
      section: "Section 5",
      reason: "The loss is covered.",
      decided_at: "2026-10-03T17:03:00+00:00",
      signed_off_by: null,
      signed_off_at: null,
    },
  };
  stubApi({
    "GET /api/claims/CLM-1112-E9": heldCopy,
    "GET /api/claims/CLM-1112-E9/steps": [],
    "GET /api/policies/POL-2002": policy,
    "GET /api/customers/CUS-3002/claims": history,
  });
  renderAt("/claims/CLM-1112-E9");
  const note = await screen.findByText(/A copy of/);
  expect(note.textContent).toBe("A copy of CLM-1112 in an evaluation");
  const link = within(note).getByRole("link", { name: "evaluation" });
  expect(link.getAttribute("href")).toBe("/scoreboard/run-9");
  const decision = await panel("Decision");
  expect(
    decision.getByText(
      "Held for sign-off. In an evaluation this counts as finished, and a copy can't be signed off.",
    ),
  ).toBeDefined();
  expect(decision.queryByRole("button", { name: "Sign off" })).toBeNull();
});

it("links to the Scoreboard from the header", async () => {
  stubApi({ "GET /api/claims": [summary], "GET /api/dispatches/latest": null });
  renderAt("/");
  const link = await screen.findByRole("link", { name: "Scoreboard" });
  expect(link.getAttribute("href")).toBe("/scoreboard");
});

it("shows a stopped evaluation as stopped, with no run time", async () => {
  const stopped = { ...running, status: "stopped" as const };
  stubApi({
    "GET /api/evaluations": [stopped],
    "GET /api/evaluations/run-9": {
      ...scored,
      status: "stopped",
      measures: running.measures,
    },
  });
  renderAt("/scoreboard");
  const [row] = (await (await panel("Evaluations")).findAllByRole("row")).slice(
    1,
  );
  expect(within(row).getByText("Stopped")).toBeDefined();
  expect(within(row).getAllByRole("cell").at(-1)?.textContent).toBe(
    "Not finished",
  );
  cleanup();

  renderAt("/scoreboard/run-9");
  const measures = await panel("Measures");
  expect(screen.getByText("Stopped")).toBeDefined();
  expect(measures.getByText("Run time").nextSibling?.textContent).toBe(
    "Not finished",
  );
});

it("says the judge found a check from even odds", () => {
  render(
    <p>
      <Check chance={0.5} /> <Check chance={0.49} />
    </p>,
  );
  expect(screen.getByText("Yes No")).toBeDefined();
});
