import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { endSession, refuseSignIn, signIn, signOut } from "./fakeAuth";
import { renderAt, stubApi } from "./testing";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function fillIn(email: string, password: string) {
  fireEvent.change(screen.getByLabelText("Email"), {
    target: { value: email },
  });
  fireEvent.change(screen.getByLabelText("Password"), {
    target: { value: password },
  });
  fireEvent.click(screen.getByRole("button", { name: "Sign in" }));
}

it("sends a visitor to sign in, then back to the page they asked for", async () => {
  endSession();
  stubApi({ "GET /api/evaluations": [] });
  renderAt("/scoreboard");
  expect(
    await screen.findByRole("heading", { name: "Sign in", level: 1 }),
  ).toBeDefined();
  expect(screen.queryByRole("navigation")).toBeNull();

  fillIn("dana.whitfield@undercover.example", "the password");
  expect(
    await screen.findByRole("heading", { name: "Scoreboard", level: 1 }),
  ).toBeDefined();
  expect(signIn).toHaveBeenLastCalledWith(
    "dana.whitfield@undercover.example",
    "the password",
  );
});

it("shows why a sign-in was refused", async () => {
  endSession();
  refuseSignIn("Too many sign-ins. Try again in a minute.");
  stubApi({});
  renderAt("/sign-in");
  await screen.findByRole("heading", { name: "Sign in", level: 1 });
  fillIn("dana.whitfield@undercover.example", "wrong");
  expect((await screen.findByRole("alert")).textContent).toBe(
    "Too many sign-ins. Try again in a minute.",
  );
});

it("waits for an email and a password before signing in", async () => {
  endSession();
  stubApi({});
  renderAt("/sign-in");
  const button = await screen.findByRole("button", { name: "Sign in" });
  expect(button.getAttribute("aria-disabled")).toBe("true");
});

it("shows who is signed in, and signs them out", async () => {
  stubApi({ "GET /api/claims": [], "GET /api/dispatches/latest": null });
  renderAt("/");
  const who = within(await screen.findByLabelText("Signed in"));
  expect(who.getByText("Dana Whitfield")).toBeDefined();
  expect(who.getByText("Senior Claims Handler")).toBeDefined();

  fireEvent.click(who.getByRole("button", { name: "Account" }));
  fireEvent.click(who.getByRole("button", { name: "Sign out" }));
  expect(
    await screen.findByRole("heading", { name: "Sign in", level: 1 }),
  ).toBeDefined();
  expect(signOut).toHaveBeenCalled();
});

it("sends a signed-in handler on from the sign-in page", async () => {
  stubApi({ "GET /api/claims": [], "GET /api/dispatches/latest": null });
  renderAt("/sign-in");
  expect(
    await screen.findByRole("heading", { name: "Claims queue" }),
  ).toBeDefined();
});

it("offers to sign out when the sign-in isn't one of our handlers", async () => {
  const fetchMock = stubApi({});
  fetchMock.mockImplementation(() =>
    Promise.resolve(
      Response.json(
        { detail: "visitor@example.com isn't one of our claims handlers" },
        { status: 403 },
      ),
    ),
  );
  renderAt("/");
  expect((await screen.findByRole("alert")).textContent).toBe(
    "visitor@example.com isn't one of our claims handlers",
  );
  fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
  expect(
    await screen.findByRole("heading", { name: "Sign in", level: 1 }),
  ).toBeDefined();
});
