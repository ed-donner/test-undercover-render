import {
  cleanup,
  fireEvent,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { SettingsPage } from "./api";
import {
  wholeText,
  Refusal,
  marcus,
  panel,
  renderAt,
  sent,
  settings,
  stubApi,
} from "./testing";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  localStorage.clear();
  delete document.documentElement.dataset.theme;
});

const changedSettings = {
  ...settings.current,
  number: 2,
  spending_limit: 0.75,
  changed_by: "Dana Whitfield",
  changed_at: "2026-10-05T18:05:00+00:00",
};

const changed: SettingsPage = {
  ...settings,
  current: changedSettings,
  changes: [changedSettings, settings.current],
};

const group = (name: string) => within(screen.getByRole("group", { name }));

async function spendingInput() {
  await screen.findByRole("group", { name: "Spending" });
  return group("Spending").getByLabelText("Spending limit for each round");
}

async function save() {
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  fireEvent.click(
    within(await screen.findByRole("dialog")).getByRole("button", {
      name: "Save the settings",
    }),
  );
}

it("shows each setting with its unit and when it last changed", async () => {
  stubApi({ "GET /api/settings": changed });
  renderAt("/settings");
  const spending = await spendingInput();
  expect(spending).toHaveProperty("value", "0.75");
  expect(
    document.getElementById(spending.getAttribute("aria-describedby") ?? "")
      ?.textContent,
  ).toBe("$");
  expect(screen.getByText(/Last changed by Dana Whitfield on/)).toBeDefined();
  const accuracy = group("Objectives on the held-out set").getByLabelText(
    "Accuracy at least",
  );
  expect(accuracy).toHaveProperty("value", "60");
  expect(accuracy.getAttribute("max")).toBe("100");
  const history = await panel("Changes");
  expect(
    history.getByText("Spending limit for each round: $0.50 to $0.75"),
  ).toBeDefined();
  const models = await panel("Models allowed");
  expect(models.getByText("$0.10 in, $0.50 out").className).toContain("num");
});

it("asks before saving, listing each change, and sends every setting", async () => {
  const fetchMock = stubApi({
    "GET /api/settings": settings,
    "PUT /api/settings": changed,
  });
  renderAt("/settings");
  fireEvent.change(await spendingInput(), { target: { value: "0.75" } });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  const dialog = within(await screen.findByRole("dialog"));
  expect(
    dialog.getByText("Spending limit for each round: $0.50 to $0.75"),
  ).toBeDefined();

  fireEvent.click(dialog.getByRole("button", { name: "Cancel" }));
  expect(sent(fetchMock, "PUT /api/settings")).toEqual([]);

  await save();
  await waitFor(() => {
    expect(sent(fetchMock, "PUT /api/settings")).toHaveLength(1);
  });
  const { current } = settings;
  expect(sent(fetchMock, "PUT /api/settings")).toEqual([
    {
      approval_limit: current.approval_limit,
      objectives: current.objectives,
      noise: current.noise,
      tolerance: current.tolerance,
      spending_limit: 0.75,
      agents: current.agents,
    },
  ]);
  expect(
    await screen.findByText(/Last changed by Dana Whitfield/),
  ).toBeDefined();
  expect(screen.getByRole("button", { name: "Save" })).toHaveProperty(
    "disabled",
    true,
  );
});

it("never changes a setting the handler didn't touch", async () => {
  const precise = { ...settings.current, spending_limit: 0.755 };
  stubApi({ "GET /api/settings": { ...settings, current: precise } });
  renderAt("/settings");
  expect(await spendingInput()).toHaveProperty("value", "0.76");
  expect(screen.getByRole("button", { name: "Save" })).toHaveProperty(
    "disabled",
    true,
  );
});

it("shows why the backend refused a setting", async () => {
  stubApi({
    "GET /api/settings": settings,
    "PUT /api/settings": new Refusal(422, [
      {
        type: "greater_than",
        loc: ["body", "spending_limit"],
        msg: "Input should be greater than 0",
        input: 0,
      },
    ]),
  });
  renderAt("/settings");
  fireEvent.change(await spendingInput(), { target: { value: "0.6" } });
  await save();
  expect((await screen.findByRole("alert")).textContent).toBe(
    "spending_limit: Input should be greater than 0",
  );
});

it("shows the settings read only to a handler who can't change them", async () => {
  stubApi({ "GET /api/settings": settings, "GET /api/me": marcus });
  renderAt("/settings");
  expect(
    await screen.findByText(
      wholeText(
        "Only a handler who can sign off payouts over $1,000.00 can change the settings. Marcus Oyelaran can't.",
      ),
    ),
  ).toBeDefined();
  expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
  expect(screen.queryByRole("spinbutton")).toBeNull();
});

it("keeps the appearance chosen in this browser", async () => {
  stubApi({ "GET /api/settings": settings });
  renderAt("/settings");
  await screen.findByRole("group", { name: "Appearance" });
  fireEvent.click(group("Appearance").getByLabelText("Dark"));
  expect(document.documentElement.dataset.theme).toBe("dark");
  expect(localStorage.getItem("undercover-appearance")).toBe("dark");
  fireEvent.click(group("Appearance").getByLabelText("Same as this computer"));
  expect(document.documentElement.dataset.theme).toBeUndefined();
});
