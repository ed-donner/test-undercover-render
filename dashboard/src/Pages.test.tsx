import { cleanup, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { endSession } from "./fakeAuth";
import {
  configuration,
  finishedEvaluation,
  runningDispatch,
  scoredEvaluation,
  versionDetails,
} from "./fixtures";
import {
  change,
  empty,
  finishedRound,
  firstRecipe,
  improvement,
  open,
} from "./improvementTesting";
import {
  claim,
  history,
  policy,
  renderAt,
  type Routes,
  stubApi,
  summary,
} from "./testing";

// What every page has in common: a page header with its title and a line on
// what the page is for, and tables whose numbers are right-aligned.

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const PAGES: [string, Routes][] = [
  [
    "/",
    {
      "GET /api/claims": [summary],
      "GET /api/dispatches/latest": runningDispatch,
    },
  ],
  [
    "/claims/CLM-1002",
    {
      "GET /api/claims/CLM-1002": claim,
      "GET /api/claims/CLM-1002/steps": [],
      "GET /api/policies/POL-2002": policy,
      "GET /api/customers/CUS-3002/claims": history,
    },
  ],
  ["/scoreboard", { "GET /api/evaluations": [finishedEvaluation] }],
  ["/scoreboard/run-9", { "GET /api/evaluations/run-9": scoredEvaluation }],
  [
    "/improvement",
    {
      "GET /api/improvement": improvement(
        { ...open, waiting: change },
        {
          rounds: [open, finishedRound],
          versions_tried: [
            { number: 2, verdict: "kept", accuracy: 0.72, grade: 1.9 },
          ],
        },
      ),
    },
  ],
  ["/improvement/recipes/1", { "GET /api/improvement/recipes/1": firstRecipe }],
  ["/configuration", { "GET /api/configuration": configuration }],
  [
    "/configuration/versions/2",
    { "GET /api/configuration/versions/2": versionDetails },
  ],
  ["/settings", {}],
];

// A number with its unit, such as $1,150.00, 64%, 2.20 or 40 s, and the words
// a numeric column shows in place of a number. A bare whole number is an id,
// such as a version's, and reads from the left.
const NUMBERS = [/^[+−-]?\$[\d,.]+/, /^[\d.]+%/, /^\d+\.\d+/, /^\d+ (?:s|min)/];
const IN_PLACE_OF_A_NUMBER = new Set([
  "",
  "None",
  "Not graded",
  "Not finished",
]);
const isNumber = (text: string) => NUMBERS.some((number) => number.test(text));

// The headings of the columns that hold numbers but aren't marked to align
// them right, in every table on the page.
function unalignedNumbers(): string[] {
  const unaligned: string[] = [];
  for (const table of document.querySelectorAll("table")) {
    const headings = [...table.querySelectorAll("thead th")];
    // A row of details under another, such as a round's reason, spans the
    // columns and holds no numbers of its own.
    const rows = [...table.querySelectorAll("tbody tr")].filter(
      (row) => row.children.length === headings.length,
    );
    headings.forEach((heading, column) => {
      const cells = rows.map((row) => row.children[column]);
      const texts = cells.map((cell) => cell.textContent.trim());
      const numeric =
        texts.some(isNumber) &&
        texts.every((text) => isNumber(text) || IN_PLACE_OF_A_NUMBER.has(text));
      const aligned = [heading, ...cells].every((cell) =>
        cell.classList.contains("num"),
      );
      if (numeric && !aligned) unaligned.push(heading.textContent);
    });
  }
  return unaligned;
}

it.each(PAGES)(
  "%s has a page header and right-aligned numbers",
  async (path, routes) => {
    stubApi(routes);
    renderAt(path);
    const title = await screen.findByRole("heading", { level: 1 });
    expect(title.textContent).not.toBe("");
    expect(title.closest(".page-header")).not.toBeNull();
    await waitFor(() => {
      expect(screen.queryByText("Loading...")).toBeNull();
    });
    expect(unalignedNumbers()).toEqual([]);
  },
);

it("the sign-in page has a page header", async () => {
  endSession();
  stubApi({});
  renderAt("/sign-in");
  const title = await screen.findByRole("heading", { level: 1 });
  expect(title.closest(".page-header")).not.toBeNull();
  expect(
    document.querySelector(".page-header .lead")?.textContent,
  ).toBeTruthy();
});

const EMPTY_STATES: [string, Routes, RegExp][] = [
  [
    "/",
    { "GET /api/claims": [summary], "GET /api/dispatches/latest": null },
    /^No dispatch yet\. Start one to work the waiting claims\.$/,
  ],
  [
    "/scoreboard",
    { "GET /api/evaluations": [] },
    /^No evaluations yet\. Start one above/,
  ],
  [
    "/claims/CLM-1002",
    {
      "GET /api/claims/CLM-1002": claim,
      "GET /api/claims/CLM-1002/steps": [],
      "GET /api/policies/POL-2002": policy,
      "GET /api/customers/CUS-3002/claims": [],
    },
    /^No steps yet\. They appear here as the agent works/,
  ],
  [
    "/improvement",
    { "GET /api/improvement": empty },
    /^No rounds yet\. Starting a round has the improver/,
  ],
  ["/nowhere", {}, /^Page not found\. Choose a page from the header\.$/],
];

it.each(EMPTY_STATES)(
  "%s says what to do when there's nothing to show",
  async (path, routes, message) => {
    stubApi(routes);
    renderAt(path);
    await waitFor(() => {
      const states = screen.queryAllByRole("status");
      expect(states.some((state) => message.test(state.textContent))).toBe(
        true,
      );
    });
  },
);

it("marks the Queue in the header on a claim's page", async () => {
  stubApi(PAGES[1][1]);
  renderAt("/claims/CLM-1002");
  const nav = within(await screen.findByRole("navigation", { name: "Main" }));
  await waitFor(() => {
    expect(
      nav.getByRole("link", { name: "Queue" }).getAttribute("aria-current"),
    ).toBe("page");
  });
  expect(
    nav.getByRole("link", { name: "Scoreboard" }).getAttribute("aria-current"),
  ).toBeNull();
});
