import { cleanup, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { TRY_AGAIN } from "./components/StateMessage";
import {
  Refusal,
  claim,
  history,
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

it("shows the queue with counts by state", async () => {
  stubApi({
    "GET /api/claims": [
      summary,
      {
        ...summary,
        claim_id: "CLM-1003",
        status: "decided",
        decision: "approve",
        payout: 420,
      },
      { ...summary, claim_id: "CLM-1004", status: "left_for_handler" },
      { ...summary, claim_id: "CLM-1005", status: "sent_back" },
    ],
    "GET /api/dispatches/latest": null,
  });
  renderAt("/");
  const link = await screen.findByRole("link", { name: "CLM-1002" });
  expect(link.getAttribute("href")).toBe("/claims/CLM-1002");
  expect(screen.getByLabelText("Waiting: 1")).toBeDefined();
  expect(screen.getByLabelText("Decided: 1")).toBeDefined();
  expect(screen.getByLabelText("In progress: 0")).toBeDefined();
  expect(screen.getByLabelText("Left for a handler: 1")).toBeDefined();
  const sentBack = screen.getByLabelText("Sent back: 1");
  expect(sentBack.className).toBe("tile status-sent_back");
  expect(sentBack.querySelector("svg.lucide-undo-2")).not.toBeNull();
  const left = screen.getByRole("row", { name: /CLM-1004/ });
  const chip = within(left).getByText("Left for a handler");
  expect(chip.className).toBe("chip status-left_for_handler");
  const row = screen.getByRole("row", { name: /CLM-1003/ });
  expect(within(row).getByText("Approved")).toBeDefined();
  expect(within(row).getByText("$420.00")).toBeDefined();
  expect(screen.getAllByText("$1,150.00")).toHaveLength(4);
  expect(screen.getAllByText("Jul 20, 2026")).toHaveLength(4);
});

it("shows an error when the queue can't load", async () => {
  stubApi({ "GET /api/claims": new Refusal(500, "The backend is down") });
  renderAt("/");
  expect((await screen.findByRole("alert")).textContent).toBe(
    `The backend is down ${TRY_AGAIN}`,
  );
});

it("shows a claim in full", async () => {
  stubApi({
    "GET /api/claims/CLM-1002": claim,
    "GET /api/policies/POL-2002": policy,
    "GET /api/customers/CUS-3002/claims": history,
  });
  renderAt("/claims/CLM-1002");
  expect(await screen.findByText(claim.story)).toBeDefined();
  expect(
    screen.getByRole("heading", { name: claim.summary, level: 1 }),
  ).toBeDefined();
  expect(screen.getByText("Wool suit")).toBeDefined();
  const total = screen.getByRole("rowheader", { name: "Total" }).closest("tr");
  expect(total?.textContent).toContain("$1,150.00");
  expect(screen.getByText("One checked bag not delivered.")).toBeDefined();
  expect(screen.getByText("Carrier report")).toBeDefined();
  expect(await screen.findByText("Premium")).toBeDefined();
  expect(screen.getByText("Electronics Plus")).toBeDefined();
  expect(
    screen.getByText("Prague, Czech Republic, Jun 20, 2026 to Jun 30, 2026"),
  ).toBeDefined();
  expect(
    await screen.findByText("Checked bag arrived 30 hours late in Lisbon"),
  ).toBeDefined();
  expect(screen.getByText("Waiting")).toBeDefined();
});

it("shows a policy without add-ons and a customer with no earlier claims", async () => {
  stubApi({
    "GET /api/claims/CLM-1002": claim,
    "GET /api/policies/POL-2002": { ...policy, add_ons: [] },
    "GET /api/customers/CUS-3002/claims": [],
  });
  renderAt("/claims/CLM-1002");
  expect(await screen.findByText("None")).toBeDefined();
  expect(
    await screen.findByText(
      /^No earlier claims: this is the customer's first claim/,
    ),
  ).toBeDefined();
});

it("says when a claim doesn't exist, and stops asking for it", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const fetchMock = stubApi({});
  renderAt("/claims/CLM-9999");
  expect(
    await screen.findByText("Claim not found. Choose one from the queue."),
  ).toBeDefined();
  await vi.advanceTimersByTimeAsync(5000);
  expect(sent(fetchMock, "GET /api/claims/CLM-9999")).toHaveLength(1);
  vi.useRealTimers();
});

it("shows other errors loading a claim", async () => {
  stubApi({ "GET /api/claims/CLM-1002": new Refusal(500, "Server error") });
  renderAt("/claims/CLM-1002");
  expect((await screen.findByRole("alert")).textContent).toBe(
    `Server error ${TRY_AGAIN}`,
  );
});

it("says when a page doesn't exist", async () => {
  stubApi({});
  renderAt("/nowhere");
  expect(
    await screen.findByText("Page not found. Choose a page from the header."),
  ).toBeDefined();
});
