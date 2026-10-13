import { cleanup, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import {
  configuration,
  firstVersion as first,
  versionDetails as details,
} from "./fixtures";
import { renderAt, stubApi } from "./testing";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("shows the current version and every version with its status", async () => {
  stubApi({ "GET /api/configuration": configuration });
  renderAt("/configuration");
  const current = within(
    await screen.findByRole("region", { name: "Current version" }),
  );
  expect(current.getByText("google/gemini-3.5-flash-lite")).toBeDefined();
  expect(current.getByText("Minimal")).toBeDefined();
  // Neither the held-out accuracy nor the grade, until rounds score it.
  expect(current.getAllByText("Not scored yet")).toHaveLength(2);

  const rows = within(
    screen.getByRole("region", { name: "Versions" }),
  ).getAllByRole("row");
  const two = within(rows[1]);
  expect(two.getByText("Current").className).toBe("chip version-current");
  expect(rows[1].textContent).toContain("+12 −3 lines");
  expect(rows[1].textContent).toContain(
    "openai/gpt-6-luna at low to google/gemini-3.5-flash-lite at minimal",
  );
  expect(rows[1].textContent).toContain("Dana Whitfield, Oct 5");
  expect(within(rows[2]).getByText("Kept")).toBeDefined();
  expect(rows[2].textContent).toContain("The first version");
  expect(
    within(rows[2])
      .getByRole("link", { name: "Version 1" })
      .getAttribute("href"),
  ).toBe("/configuration/versions/1");
});

it("marks the Configuration page in the header", async () => {
  stubApi({ "GET /api/configuration": configuration });
  renderAt("/configuration");
  const nav = within(await screen.findByRole("navigation", { name: "Main" }));
  expect(
    nav
      .getByRole("link", { name: "Configuration" })
      .getAttribute("aria-current"),
  ).toBe("page");
});

it("sends the old Instructions page to the Configuration page", async () => {
  stubApi({ "GET /api/configuration": configuration });
  renderAt("/instructions");
  expect(
    await screen.findByRole("heading", { name: "Configuration", level: 1 }),
  ).toBeDefined();
});

it("shows a version's diff and its instructions, read only", async () => {
  stubApi({ "GET /api/configuration/versions/2": details });
  renderAt("/configuration/versions/2");
  const changes = within(
    await screen.findByRole("region", {
      name: "What changed from version 1",
    }),
  );
  expect(changes.getByText("Refer a stolen phone.").tagName).toBe("DEL");
  expect(changes.getByText("Decline a phone left unattended.").tagName).toBe(
    "INS",
  );
  expect(changes.getByText("Read the claim.").tagName).toBe("SPAN");
  expect(document.querySelectorAll(".diff-gap")).toHaveLength(1);
  const instructions = within(
    screen.getByRole("region", { name: "Instructions" }),
  );
  expect(
    instructions.getByText(/## Contents of the claims manual/),
  ).toBeDefined();
  expect(within(screen.getByRole("main")).queryByRole("textbox")).toBeNull();
});

it("says version 1 has nothing before it", async () => {
  stubApi({
    "GET /api/configuration/versions/1": { ...details, ...first, diff: null },
  });
  renderAt("/configuration/versions/1");
  expect(await screen.findByText(/nothing before it to compare/)).toBeDefined();
});

it("says when a version doesn't exist", async () => {
  stubApi({});
  renderAt("/configuration/versions/9");
  expect(
    await screen.findByText(
      "Version not found. Choose one on the Configuration page.",
    ),
  ).toBeDefined();
});
