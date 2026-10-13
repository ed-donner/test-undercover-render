import { cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { Claim } from "./api";
import {
  approval,
  approved,
  decidedAt,
  decisionPanel,
  held,
  showClaim,
  step,
} from "./claimTesting";
import { time } from "./format";
import { Refusal, marcus, panel, sent, wholeText } from "./testing";

// A senior handler sends a held decision back to the agent with a note, and the
// claim page shows each decision sent back.

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const NOTE = "Meridian Air has already paid $350 for the lost bag.";
const sentBackAt = "2026-09-27T18:05:00+00:00";

it("lets a senior handler send a held payment back with a note", async () => {
  const { routes, fetchMock } = showClaim(held);
  const panel = await decisionPanel();
  expect(panel.getByRole("button", { name: "Sign off" })).toBeDefined();
  const sendBack = panel.getByRole("button", { name: "Send back" });
  expect(sendBack.getAttribute("aria-expanded")).toBe("false");
  fireEvent.click(sendBack);

  const note = panel.getByLabelText("What should the agent look at again?");
  expect(note.getAttribute("maxlength")).toBe("1000");
  expect(note.hasAttribute("required")).toBe(true);
  const submit = panel.getByRole("button", { name: "Send back to the agent" });
  expect(submit.getAttribute("aria-disabled")).toBe("true");
  fireEvent.click(submit);
  expect(sent(fetchMock, "POST /api/claims/CLM-1002/send-back")).toEqual([]);

  const back: Claim = {
    ...held,
    status: "sent_back",
    decision: null,
    sent_back_decisions: [
      {
        ...approval,
        payout: 1350,
        note: NOTE,
        sent_back_by: "Dana Whitfield",
        sent_back_at: sentBackAt,
      },
    ],
  };
  routes["POST /api/claims/CLM-1002/send-back"] = back;
  routes["GET /api/claims/CLM-1002"] = back;
  fireEvent.change(note, { target: { value: `  ${NOTE}  ` } });
  expect(submit.getAttribute("aria-disabled")).toBe("false");
  fireEvent.click(submit);
  expect(
    await panel.findByText(
      "Sent back to the agent, which hasn't taken it up yet. The next dispatch works on it.",
    ),
  ).toBeDefined();
  expect(sent(fetchMock, "POST /api/claims/CLM-1002/send-back")).toEqual([
    { note: NOTE },
  ]);
});

it("tells a handler who can't send a payment back why", async () => {
  const { routes } = showClaim(held);
  routes["GET /api/me"] = marcus;
  const panel = await decisionPanel();
  expect(
    await panel.findByText(
      wholeText(
        "Only a handler who can sign off payouts over $1,000.00 can sign this off or send it back. Marcus Oyelaran can't.",
      ),
    ),
  ).toBeDefined();
  expect(panel.queryByRole("button", { name: "Send back" })).toBeNull();
});

it("shows why a send back was refused", async () => {
  const { routes } = showClaim(held);
  const panel = await decisionPanel();
  routes["POST /api/claims/CLM-1002/send-back"] = new Refusal(
    409,
    "Claim CLM-1002 is not waiting for sign-off",
  );
  fireEvent.click(panel.getByRole("button", { name: "Send back" }));
  fireEvent.change(panel.getByRole("textbox"), { target: { value: NOTE } });
  fireEvent.click(
    panel.getByRole("button", { name: "Send back to the agent" }),
  );
  expect((await panel.findByRole("alert")).textContent).toBe(
    "Claim CLM-1002 is not waiting for sign-off",
  );
});

it("shows each decision sent back with its note, beside the new decision", async () => {
  const sentBack = {
    ...approval,
    payout: 1350,
    note: NOTE,
    sent_back_by: "Dana Whitfield",
    sent_back_at: sentBackAt,
  };
  showClaim({ ...approved, sent_back_decisions: [sentBack] }, [
    step(1, "sent_back", `Sent back by Dana Whitfield: ${NOTE}`),
  ]);
  const decisions = await panel("Decisions sent back");
  expect(decisions.getByText("Approved")).toBeDefined();
  expect(decisions.getByText("$1,350.00")).toBeDefined();
  expect(decisions.getByText(approval.reason)).toBeDefined();
  expect(decisions.getByText(NOTE)).toBeDefined();
  expect(
    decisions.getByText(`Sent back by Dana Whitfield at ${time(sentBackAt)}`),
  ).toBeDefined();
  expect(
    decisions.getByText(
      `Decided by UnderCover Agent, version 1 at ${time(decidedAt)}`,
    ),
  ).toBeDefined();
  const steps = await panel("Agent at work");
  const note = steps.getByText(`Sent back by Dana Whitfield: ${NOTE}`);
  expect(note.closest(".step")?.textContent).toContain("Handler's note");
  expect(
    note.closest(".step")?.querySelector("svg.lucide-undo-2"),
  ).not.toBeNull();
});

it("shows no decisions sent back for a claim with none", async () => {
  showClaim(approved);
  await decisionPanel();
  expect(
    screen.queryByRole("region", { name: "Decisions sent back" }),
  ).toBeNull();
});
