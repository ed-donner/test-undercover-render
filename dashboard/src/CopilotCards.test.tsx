import {
  cleanup,
  fireEvent,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { CARD_KINDS, MAY_HAVE_PAID, NEVER_BEGAN } from "./copilot";
import type { CardKind } from "./conversation";
import {
  CONVERSATION_PATH,
  confirmation,
  conversation,
  openSidebar,
  openedBefore,
  showConversation,
  sidebar,
  step,
  turn,
  waiting,
} from "./copilotTesting";
import { Refusal, renderAt, sent, stubApi } from "./testing";

// The Copilot's cards in the sidebar: each step's card, the answer, formatted,
// and the confirmation card a sign-off waits on, with how the sign-off went.

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const SOURCE = {
  file: "policy_wording.md",
  system: "Policy administration",
  owner: "Head of product",
  reviewed: "2026-09-01",
};

it("shows each card with its kind, call and state", async () => {
  showConversation(
    turn({
      status: "working",
      answer: null,
      steps: [
        step({ step_id: 1 }),
        step({
          step_id: 2,
          tool: "read_section",
          kind: "context",
          input: "policy_wording 3",
          answer: '{"title": "Trip delay"}',
          sources: [SOURCE],
        }),
        step({
          step_id: 3,
          tool: "start_dispatch",
          kind: "action",
          input: "10",
          status: "refused",
          answer: null,
          reason: "A dispatch is running",
        }),
        step({
          step_id: 4,
          tool: "list_steps",
          status: "failed",
          reason: "It broke",
        }),
        step({
          step_id: 5,
          tool: "list_claims",
          input: "",
          status: "working",
          seconds: 2.5,
        }),
      ],
    }),
  );
  const copilot = await openSidebar();
  const list = within(await copilot.findByRole("list", { name: "Steps" }));
  const [lookup, read, action, failed, working] = list.getAllByRole("listitem");
  expect(lookup.textContent).toContain("get_claim CLM-1012");
  expect(within(lookup).getByLabelText("Done")).toBeDefined();
  expect(lookup.textContent).toContain("0.4 s");
  expect(action.className).toContain("card-action");
  expect(within(action).getByText("Refused")).toBeDefined();
  expect(action.textContent).toContain("A dispatch is running");
  expect(within(failed).getByText("Failed")).toBeDefined();
  expect(failed.textContent).toContain("It broke");
  expect(within(working).getByLabelText("Working")).toBeDefined();
  expect(working.textContent).toContain("2.5 s");
  const open = within(read).getByRole("button");
  expect(open.getAttribute("aria-expanded")).toBe("false");
  fireEvent.click(open);
  expect(open.getAttribute("aria-expanded")).toBe("true");
  expect(within(read).getByText("Asked")).toBeDefined();
  expect(within(read).getByText("Came back")).toBeDefined();
  expect(read.textContent).toContain("policy_wording.md");
  expect(read.textContent).toContain(
    "Policy administration, owned by the Head of product",
  );
});

it.each(Object.entries(CARD_KINDS))(
  "marks a %s card with its icon",
  async (kind, { label }) => {
    showConversation(turn({ steps: [step({ kind: kind as CardKind })] }));
    const card = within(
      await (await openSidebar()).findByRole("list", { name: "Steps" }),
    );
    expect(card.getByLabelText(label).tagName).toBe("svg");
  },
);

it("shows the working indicator while the turn works and no card does", async () => {
  showConversation(turn({ status: "working", answer: null, steps: [step()] }));
  const copilot = await openSidebar();
  expect(await copilot.findByText("Working")).toBeDefined();
  cleanup();
  showConversation(
    turn({
      status: "working",
      answer: null,
      steps: [step({ status: "working" })],
    }),
  );
  await (await openSidebar()).findByLabelText("Working");
  expect(sidebar().queryByText("Working")).toBeNull();
});

const ANSWER = [
  "CLM-1003 needs you:",
  "",
  "- It is held for sign-off.",
  "",
  "| Claim | Payout |",
  "| --- | --- |",
  "| CLM-1003 | $3,750.00 |",
].join("\n");

it("formats the answer with claim links and its small print", async () => {
  showConversation(turn({ answer: ANSWER }));
  const copilot = await openSidebar();
  const [link] = await copilot.findAllByRole("link", { name: "CLM-1003" });
  expect(link.getAttribute("href")).toBe("/claims/CLM-1003");
  expect(copilot.getByRole("table")).toBeDefined();
  expect(copilot.getByText("It is held for sign-off.")).toBeDefined();
  expect(copilot.getByText("4 model calls, $0.0021, 12 seconds")).toBeDefined();
});

it("links a claim id once, even in a link, and opens another site in a tab of its own", async () => {
  showConversation(
    turn({
      answer:
        "See [CLM-1003](/claims/CLM-1003), https://example.com/CLM-1004 and [the guide](//example.com/claims).",
    }),
  );
  const copilot = await openSidebar();
  const links = await copilot.findAllByRole("link");
  expect(links.map((link) => link.getAttribute("href"))).toEqual([
    "/claims/CLM-1003",
    "https://example.com/CLM-1004",
    "//example.com/claims",
  ]);
  expect(document.querySelector(".answer a a")).toBeNull();
  expect(links[2].getAttribute("target")).toBe("_blank");
});

it("shows the confirmation card from the app's records and answers its own turn", async () => {
  const fetchMock = showConversation(
    turn({ turn_id: "turn-0" }),
    waiting({ turn_id: "turn-1", number: 2 }),
  );
  const card = within(
    await screen.findByRole("region", { name: "Confirm the sign-off" }),
  );
  expect(card.getByRole("link", { name: "CLM-1003" })).toBeDefined();
  expect(card.getByText(confirmation.customer_name)).toBeDefined();
  expect(card.getByText("$3,750.00")).toBeDefined();
  expect(card.getByText(confirmation.reason)).toBeDefined();
  fireEvent.click(card.getByRole("button", { name: "Sign off and pay" }));
  await waitFor(() => {
    expect(sent(fetchMock, `POST ${CONVERSATION_PATH}/confirmation`)).toEqual([
      { turn_id: "turn-1", answer: "sign_off" },
    ]);
  });
  fireEvent.click(card.getByRole("button", { name: "Cancel" }));
  await waitFor(() => {
    expect(
      sent(fetchMock, `POST ${CONVERSATION_PATH}/confirmation`),
    ).toContainEqual({
      turn_id: "turn-1",
      answer: "cancel",
    });
  });
});

const ANSWERED_AT = "2026-10-10T09:01:00.000+00:00";
const signOff = (changes: Parameters<typeof step>[0]) =>
  step({
    tool: "sign_off_claim",
    kind: "action",
    input: "CLM-1003",
    started_at: "2026-10-10T09:01:00.500+00:00",
    ...changes,
  });

async function outcomeFor(answered: Parameters<typeof turn>[0]) {
  cleanup();
  showConversation(
    waiting({
      status: "working",
      answered_at: ANSWERED_AT,
      confirmation_answer: "sign_off",
      ...answered,
    }),
  );
  return within(
    await screen.findByRole("region", { name: "Confirm the sign-off" }),
  );
}

it("says Signed off and paid only once the sign-off is done", async () => {
  const outcomes: [Parameters<typeof turn>[0], string, string | undefined][] = [
    [{}, "Signing off", undefined],
    [
      { steps: [signOff({ status: "working", finished_at: null })] },
      "Signing off",
      undefined,
    ],
    [
      { steps: [signOff({ status: "done" })], status: "done" },
      "Signed off and paid",
      undefined,
    ],
    [
      {
        steps: [
          signOff({
            status: "refused",
            reason: "Claim CLM-1003 is not waiting for sign-off",
          }),
        ],
        status: "done",
      },
      "Not signed off",
      "Claim CLM-1003 is not waiting for sign-off",
    ],
    [
      { steps: [signOff({ status: "done", input: "CLM-1003, as asked" })] },
      "Signed off and paid",
      undefined,
    ],
    [
      {
        steps: [signOff({ status: "failed", reason: "It timed out" })],
        status: "failed",
        failure: "It timed out",
      },
      "Not known",
      "It timed out",
    ],
    [
      {
        steps: [signOff({ status: "working", finished_at: null })],
        status: "stopped",
      },
      "Not known",
      MAY_HAVE_PAID,
    ],
    [
      { status: "failed", failure: "The model refused" },
      "Not signed off",
      "The model refused",
    ],
    [{ status: "stopped" }, "Not signed off", NEVER_BEGAN],
    [{ confirmation_answer: "cancel", status: "done" }, "Canceled", undefined],
    [
      {
        confirmation_answer: "cancel",
        canceled_because: "The claim changed since the card was shown",
        status: "done",
      },
      "Canceled",
      "The claim changed since the card was shown",
    ],
    [
      {
        steps: [
          signOff({
            status: "refused",
            reason: "One sign-off a turn.",
            started_at: "2026-10-10T09:00:30.000+00:00",
          }),
        ],
      },
      "Signing off",
      undefined,
    ],
  ];
  for (const [answered, outcome, reason] of outcomes) {
    const card = await outcomeFor(answered);
    const shown = card.getByRole("status");
    expect(shown.textContent).toBe(reason ? `${outcome} ${reason}` : outcome);
    expect(card.queryByRole("button", { name: "Sign off and pay" })).toBeNull();
  }
});

it("shows a refused answer on the card that was answered, and no other, and reads the conversation again", async () => {
  openedBefore();
  const fetchMock = stubApi({
    [`GET ${CONVERSATION_PATH}`]: conversation(
      waiting({
        turn_id: "turn-0",
        status: "done",
        answered_at: ANSWERED_AT,
        confirmation_answer: "cancel",
      }),
      waiting({ turn_id: "turn-1", number: 2 }),
    ),
    [`POST ${CONVERSATION_PATH}/confirmation`]: new Refusal(
      409,
      "The claim changed",
    ),
  });
  renderAt("/settings");
  await screen.findByRole("button", { name: "Sign off and pay" });
  const [earlier, waitingCard] = screen.getAllByRole("region", {
    name: "Confirm the sign-off",
  });
  fireEvent.click(
    within(waitingCard).getByRole("button", { name: "Sign off and pay" }),
  );
  expect(
    await within(waitingCard).findByText("The claim changed"),
  ).toBeDefined();
  expect(within(earlier).queryByText("The claim changed")).toBeNull();
  await waitFor(() => {
    expect(sent(fetchMock, `GET ${CONVERSATION_PATH}`)).toHaveLength(2);
  });
});
