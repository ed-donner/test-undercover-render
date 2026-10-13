import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { renderAt, stubApi } from "./testing";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const QUEUE_ROUTES = {
  "GET /api/claims": [],
  "GET /api/dispatches/latest": null,
};

it("shows the handler's initials, and keeps Settings and Sign out in their menu", async () => {
  stubApi(QUEUE_ROUTES);
  renderAt("/");
  const who = within(await screen.findByLabelText("Signed in"));
  const avatar = who.getByRole("button", { name: "Account" });
  const nav = within(screen.getByRole("navigation", { name: "Main" }));
  expect(nav.getAllByRole("link").map((link) => link.textContent)).toEqual([
    "Queue",
    "Scoreboard",
    "Improvement",
    "Configuration",
  ]);
  expect(avatar.textContent).toBe("DW");
  expect(avatar.getAttribute("aria-expanded")).toBe("false");
  expect(who.queryByRole("link", { name: "Settings" })).toBeNull();

  fireEvent.click(avatar);
  expect(avatar.getAttribute("aria-expanded")).toBe("true");
  expect(who.getAllByText("Senior Claims Handler")).toHaveLength(2);
  expect(who.getByText("dana.whitfield@undercover.example")).toBeDefined();
  expect(who.getByRole("button", { name: "Sign out" })).toBeDefined();
  fireEvent.click(who.getByRole("link", { name: "Settings" }));
  expect(
    await screen.findByRole("heading", { name: "Settings", level: 1 }),
  ).toBeDefined();
  expect(who.queryByRole("link", { name: "Settings" })).toBeNull();
});

it("closes the menu on Escape, back on the avatar, on a click outside it, or as focus leaves it", async () => {
  stubApi(QUEUE_ROUTES);
  renderAt("/");
  const who = within(await screen.findByLabelText("Signed in"));
  const avatar = who.getByRole("button", { name: "Account" });
  const menuOpen = () => who.queryByRole("button", { name: "Sign out" });

  fireEvent.click(avatar);
  fireEvent.keyDown(document, { key: "Escape" });
  expect(menuOpen()).toBeNull();
  expect(document.activeElement).toBe(avatar);

  fireEvent.click(avatar);
  fireEvent.pointerDown(who.getByText("dana.whitfield@undercover.example"));
  expect(menuOpen()).not.toBeNull();
  fireEvent.pointerDown(screen.getByRole("heading", { name: "Claims queue" }));
  expect(menuOpen()).toBeNull();

  fireEvent.click(avatar);
  fireEvent.blur(avatar, { relatedTarget: menuOpen() });
  expect(menuOpen()).not.toBeNull();
  fireEvent.blur(avatar, {
    relatedTarget: screen.getByRole("button", { name: "Start a dispatch" }),
  });
  expect(menuOpen()).toBeNull();
});

it("shows the header and nav while the handler loads", async () => {
  const fetchMock = stubApi(QUEUE_ROUTES);
  fetchMock.mockImplementation(() => new Promise<Response>(() => undefined));
  renderAt("/");
  expect(await screen.findByRole("navigation", { name: "Main" })).toBeDefined();
  expect(screen.getByText("Loading...")).toBeDefined();
  expect(screen.queryByLabelText("Signed in")).toBeNull();
});
