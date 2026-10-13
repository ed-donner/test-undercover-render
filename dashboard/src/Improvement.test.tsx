import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { RecipeDetails, RoundView, WaitingProposal } from "./api";
import {
  APPROVAL,
  change,
  empty,
  improvement,
  measures,
  open,
  PROPOSAL_ID,
  REJECTION,
  ROUND_ID,
  showPage,
  START,
} from "./improvementTesting";
import {
  wholeText,
  marcus,
  panel,
  Refusal,
  renderAt,
  type Routes,
  sent,
  stubApi,
} from "./testing";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("with no rounds says so, and starts a round once", async () => {
  const fetchMock = showPage(empty, { [START]: { status: "accepted" } });
  const rounds = await panel("Rounds");
  expect(
    rounds.getByText(/^No rounds yet\. Starting a round has the improver/),
  ).toBeDefined();
  const start = screen.getByRole("button", { name: "Start a round" });
  fireEvent.click(start);
  fireEvent.click(start);
  await vi.waitFor(() => {
    expect(sent(fetchMock, START)).toHaveLength(1);
  });
  expect(screen.queryByRole("button", { name: "Stop the round" })).toBeNull();
});

it("shows why a round can't start", async () => {
  showPage(empty, {
    [START]: new Refusal(409, "An evaluation is running"),
  });
  fireEvent.click(await screen.findByRole("button", { name: "Start a round" }));
  expect((await screen.findByRole("alert")).textContent).toBe(
    "An evaluation is running",
  );
});

it("offers to stop a round while it's open", async () => {
  const stop = `POST /api/improvement/rounds/${ROUND_ID}/stop`;
  const fetchMock = showPage(improvement(open), { [stop]: open });
  fireEvent.click(
    await screen.findByRole("button", { name: "Stop the round" }),
  );
  const dialog = screen.getByRole("dialog", { name: "Stop round 1?" });
  expect(sent(fetchMock, stop)).toHaveLength(0);
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Stop the round" }),
  );
  await vi.waitFor(() => {
    expect(sent(fetchMock, stop)).toHaveLength(1);
  });
  expect(screen.queryByRole("button", { name: "Start a round" })).toBeNull();
});

it.each([
  [
    "First evaluations, 2 of 3",
    { stage: "first_evaluations", progress: "2 of 3" },
  ],
  ["The improver is working", { stage: "improving", progress: null }],
  [
    "A change is waiting for approval",
    { stage: "change_waiting", progress: null },
  ],
  ["Evaluations, 1 of 3", { stage: "evaluating", progress: "1 of 3" }],
  [
    "Kept: accuracy improved",
    {
      stage: "verdict",
      progress: null,
      verdict: "kept",
      verdict_reason: "accuracy improved",
    },
  ],
  [
    "A new recipe is waiting for approval",
    { stage: "recipe_waiting", progress: null },
  ],
] as const)("shows where a round has got to: %s", async (words, stage) => {
  showPage(improvement({ ...open, waiting: null, ...stage }));
  const round = await panel("Round 1");
  const current = round
    .getByRole("list", { name: "Where the round has got to" })
    .querySelector("[aria-current=step]");
  expect(current?.textContent).toBe(words);
  const rounds = await panel("Rounds");
  expect(rounds.getByText(words)).toBeDefined();
});

it("shows a finished round's verdict and why", async () => {
  const finished: RoundView = {
    ...open,
    status: "finished",
    stage: null,
    waiting: null,
    version: 2,
    verdict: "rolled_back",
    verdict_reason: "cost_per_claim got worse",
  };
  showPage(improvement(finished));
  const round = await panel("Round 1");
  expect(round.getByText("Rolled back", { selector: ".chip" }).className).toBe(
    "chip verdict-rolled_back",
  );
  expect(round.getByText(/cost per claim got worse/)).toBeDefined();
  expect(
    round.queryByRole("list", { name: "Where the round has got to" }),
  ).toBeNull();
});

it.each([
  [null, "The spending limit cut short its first evaluations"],
  [null, "The agent's service restarted"],
  ["Dana Whitfield", "Stopped by Dana Whitfield"],
])("says who or what stopped a round: %s", async (by, because) => {
  showPage(
    improvement({
      ...open,
      status: "stopped",
      stage: null,
      waiting: null,
      stopped_by: by,
      stopped_because: because,
    }),
  );
  const round = await panel("Round 1");
  expect(round.getByText("Stopped", { selector: ".chip" })).toBeDefined();
  expect(round.getByText(because, { selector: "p" })).toBeDefined();
});

it("shows a change waiting and approves that proposal", async () => {
  const fetchMock = showPage(improvement(open), {
    [APPROVAL]: { status: "accepted" },
  });
  const proposal = await panel("A change is waiting for approval");
  expect(proposal.getByText(change.reason)).toBeDefined();
  expect(
    proposal.getByText("A stolen phone needs a police report."),
  ).toBeDefined();
  expect(proposal.getByText("openai/gpt-6-luna")).toBeDefined();
  expect(proposal.getByText("google/gemini-3.5-flash-lite")).toBeDefined();

  fireEvent.click(proposal.getByRole("button", { name: "Approve" }));
  expect(sent(fetchMock, APPROVAL)).toHaveLength(0);
  const dialog = screen.getByRole("dialog", { name: "Approve the change?" });
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Approve the change" }),
  );
  await vi.waitFor(() => {
    expect(sent(fetchMock, APPROVAL)).toEqual([undefined]);
  });
});

it("rejects a proposal with a reason", async () => {
  const fetchMock = showPage(improvement(open), {
    [REJECTION]: { status: "accepted" },
  });
  const proposal = await panel("A change is waiting for approval");
  fireEvent.click(proposal.getByRole("button", { name: "Reject" }));
  const send = proposal.getByRole("button", { name: "Reject the change" });
  fireEvent.click(send);
  expect(sent(fetchMock, REJECTION)).toHaveLength(0);
  fireEvent.change(proposal.getByLabelText("Why reject it?"), {
    target: { value: "Keep each rule general" },
  });
  fireEvent.click(send);
  await vi.waitFor(() => {
    expect(sent(fetchMock, REJECTION)).toEqual([
      { reason: "Keep each rule general" },
    ]);
  });
});

it.each([
  "A dispatch is running",
  `Proposal ${PROPOSAL_ID} isn't waiting for a handler: it was rejected`,
])("shows why an approval was refused: %s", async (detail) => {
  showPage(improvement(open), { [APPROVAL]: new Refusal(409, detail) });
  const proposal = await panel("A change is waiting for approval");
  fireEvent.click(proposal.getByRole("button", { name: "Approve" }));
  fireEvent.click(
    within(screen.getByRole("dialog")).getByRole("button", {
      name: "Approve the change",
    }),
  );
  expect((await screen.findByRole("alert")).textContent).toBe(detail);
});

it("keeps a refusal on screen once the proposal is no longer waiting", async () => {
  const detail = `Proposal ${PROPOSAL_ID} isn't waiting for a handler: it was approved`;
  const routes: Routes = { [APPROVAL]: new Refusal(409, detail) };
  showPage(improvement(open), routes);
  const proposal = await panel("A change is waiting for approval");
  fireEvent.click(proposal.getByRole("button", { name: "Approve" }));
  fireEvent.click(
    within(screen.getByRole("dialog")).getByRole("button", {
      name: "Approve the change",
    }),
  );
  await screen.findByRole("alert");
  routes["GET /api/improvement"] = improvement({
    ...open,
    stage: "evaluating",
    waiting: null,
  });
  await vi.waitFor(
    () => {
      expect(
        screen.queryByRole("region", {
          name: "A change is waiting for approval",
        }),
      ).toBeNull();
    },
    { timeout: 3000 },
  );
  expect(screen.getByRole("alert").textContent).toBe(detail);
});

it("closes the dialog when a new proposal takes the place of the one shown", async () => {
  const routes: Routes = { [APPROVAL]: { status: "accepted" } };
  const fetchMock = showPage(improvement(open), routes);
  const proposal = await panel("A change is waiting for approval");
  fireEvent.click(proposal.getByRole("button", { name: "Approve" }));
  expect(
    screen.getByRole("dialog", { name: "Approve the change?" }),
  ).toBeDefined();
  routes["GET /api/improvement"] = improvement({
    ...open,
    waiting: { ...change, proposal_id: "proposal-3", reason: "A new reason" },
  });
  expect(
    await screen.findByText("A new reason", {}, { timeout: 3000 }),
  ).toBeDefined();
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(sent(fetchMock, APPROVAL)).toHaveLength(0);
});

it("shows a recipe waiting in the same diff", async () => {
  const recipe: WaitingProposal = {
    ...change,
    kind: "recipe",
    model_before: null,
    reasoning_effort_before: null,
    model_after: null,
    reasoning_effort_after: null,
  };
  showPage(improvement({ ...open, stage: "recipe_waiting", waiting: recipe }));
  const proposal = await panel("A new recipe is waiting for approval");
  expect(proposal.getByText("+1").closest(".diff")).not.toBeNull();
  expect(proposal.queryByText("Model before")).toBeNull();
});

it("shows Marcus what he can't do in place of the buttons", async () => {
  showPage(improvement(open), { "GET /api/me": marcus });
  const proposal = await panel("A change is waiting for approval");
  expect(proposal.queryByRole("button", { name: "Approve" })).toBeNull();
  expect(proposal.queryByRole("button", { name: "Reject" })).toBeNull();
  expect(
    await proposal.findByText(
      wholeText(
        "Only a handler who can sign off payouts over $1,000.00 can approve or reject the improver's proposals. Marcus Oyelaran can't.",
      ),
    ),
  ).toBeDefined();
  cleanup();
  showPage(empty, { "GET /api/me": marcus });
  expect(
    await screen.findByText(
      wholeText(
        "Only a handler who can sign off payouts over $1,000.00 can start a round. Marcus Oyelaran can't.",
      ),
    ),
  ).toBeDefined();
  expect(screen.queryByRole("button", { name: "Start a round" })).toBeNull();
});

it("lists the rounds with their scores, verdicts, reviews and cost", async () => {
  const finished: RoundView = {
    ...open,
    status: "finished",
    stage: null,
    waiting: null,
    version: 2,
    reason: "Two stolen phones were approved",
    verdict: "kept",
    verdict_reason: "accuracy improved",
    held_out_before: measures(0.6, 1.5),
    held_out_after: measures(0.72, null),
    reviews: [
      {
        kind: "change",
        review: "rejected",
        reviewed_by: "Dana Whitfield",
        reviewed_at: "2026-10-04T09:12:00+00:00",
        rejection_reason: "Keep each rule general",
      },
      {
        kind: "change",
        review: "approved",
        reviewed_by: "Dana Whitfield",
        reviewed_at: "2026-10-04T09:20:00+00:00",
        rejection_reason: null,
      },
    ],
  };
  showPage(improvement(finished));
  const rounds = await panel("Rounds");
  const [header, row, details] = rounds.getAllByRole("row");
  const headings = within(header).getAllByRole("columnheader");
  const cells = within(row).getAllByRole("cell");
  const column = (name: string) =>
    headings.findIndex((heading) => heading.textContent === name);
  const accuracy = cells[column("Held-out accuracy")];
  expect(accuracy.textContent).toBe("60% to 72%");
  expect(accuracy.className).toContain("num");
  expect(cells[column("Held-out grade")].textContent).toBe(
    "1.50 to Not graded",
  );
  expect(cells[column("Held-out grade")].className).toContain("num");
  expect(cells[column("Verdict")].textContent).toBe("Kept accuracy improved");
  const reviews = details.textContent;
  expect(reviews).toContain(
    "The improver's reason: Two stolen phones were approved",
  );
  expect(reviews).toContain("Dana Whitfield rejected the change");
  expect(reviews).toContain("Keep each rule general");
  expect(reviews).toContain("Dana Whitfield approved the change");
  expect(cells[column("Cost")].textContent).toBe("$0.1234 of $0.50");
  expect(cells[column("Cost")].className).toContain("num");
});

it("charts each version tried against version 1", async () => {
  showPage(
    improvement(null, {
      first_version: { number: 1, verdict: null, accuracy: 0.6, grade: 1.5 },
      versions_tried: [
        { number: 2, verdict: "rolled_back", accuracy: 0.56, grade: 1.2 },
        { number: 3, verdict: "kept", accuracy: 0.72, grade: 1.9 },
      ],
    }),
  );
  const tried = await panel("Versions tried");
  const charts = tried.getAllByRole("figure");
  expect(
    charts.map((chart) => chart.querySelector("figcaption")?.textContent),
  ).toEqual(["Held-out accuracy", "Held-out grade"]);
  for (const chart of charts) {
    const points = [...chart.querySelectorAll("circle")];
    expect(points.map((point) => point.getAttribute("class"))).toEqual([
      "chart-point point-rolled_back",
      "chart-point point-kept",
    ]);
    expect(chart.querySelector(".chart-first")?.textContent).toBe("Version 1");
    expect(chart.textContent).toContain("Version tried");
  }
  // Each axis starts a step below the lowest score, so close scores stand apart.
  const ticks = (chart: HTMLElement) =>
    [...chart.querySelectorAll(".chart-tick text")].map(
      (tick) => tick.textContent,
    );
  expect(ticks(charts[0])).toEqual([
    "40%",
    "50%",
    "60%",
    "70%",
    "80%",
    "90%",
    "100%",
  ]);
  expect(ticks(charts[1])).toEqual([
    "0.50",
    "1.00",
    "1.50",
    "2.00",
    "2.50",
    "3.00",
  ]);
  expect(within(charts[0]).getByRole("img").getAttribute("aria-label")).toBe(
    "Held-out accuracy. Version 1 60%, version 2 56%, rolled back, version 3 72%, kept.",
  );
});

it("shows a recipe with its diff", async () => {
  const two: RecipeDetails = {
    ...empty.recipes[0],
    number: 2,
    current: true,
    reason: "Shorter",
    proposed_by: "Round 1",
    round_id: ROUND_ID,
    approved_by: "Dana Whitfield",
    approved_at: "2026-10-04T09:40:00+00:00",
    lines_added: 1,
    lines_removed: 2,
    recipe: "1. Read the results.\n",
    diff: change.diff,
  };
  stubApi({ "GET /api/improvement/recipes/2": two });
  renderAt("/improvement/recipes/2");
  expect(
    await screen.findByRole("heading", { name: "Recipe 2" }),
  ).toBeDefined();
  const changes = await panel("What changed from recipe 1");
  expect(
    changes.getByText("A stolen phone needs a police report."),
  ).toBeDefined();
  expect(
    (await panel("Recipe")).getByText("1. Read the results."),
  ).toBeDefined();
});

it("clears a refusal once another proposal waits", async () => {
  const detail = `Proposal ${PROPOSAL_ID} isn't waiting for a handler: it was approved`;
  const routes: Routes = { [APPROVAL]: new Refusal(409, detail) };
  showPage(improvement(open), routes);
  const proposal = await panel("A change is waiting for approval");
  fireEvent.click(proposal.getByRole("button", { name: "Approve" }));
  fireEvent.click(
    within(screen.getByRole("dialog")).getByRole("button", {
      name: "Approve the change",
    }),
  );
  await screen.findByRole("alert");
  routes["GET /api/improvement"] = improvement({
    ...open,
    waiting: { ...change, proposal_id: "proposal-3", reason: "A new reason" },
  });
  await screen.findByText("A new reason", {}, { timeout: 3000 });
  expect(screen.queryByRole("alert")).toBeNull();
});
