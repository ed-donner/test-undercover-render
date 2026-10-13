import {
  act,
  cleanup,
  fireEvent,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import {
  ANSWER_FIRST,
  ASK,
  OVERLAY,
  STILL_WORKING,
  savedConversation,
} from "./copilot";
import {
  CONVERSATIONS,
  CONVERSATION_PATH,
  conversation,
  openSidebar,
  openedBefore,
  showConversation,
  sidebar,
  step,
  turn,
  waiting,
} from "./copilotTesting";
import { freshAccessToken } from "./fakeAuth";
import { Refusal, renderAt, sent, stubApi } from "./testing";

// The Copilot's sidebar on every signed-in page: open or collapsed, a greeting,
// the message box, reading the conversation, and the earlier conversations.
// The cards, the answer and the confirmation card are in CopilotCards.test.tsx.

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

it("is open the first time and stays collapsed once collapsed", async () => {
  stubApi({});
  renderAt("/settings");
  const copilot = await openSidebar();
  expect(copilot.getByText("Signed in as Dana Whitfield")).toBeDefined();
  fireEvent.click(
    copilot.getByRole("button", { name: "Collapse the Copilot" }),
  );
  expect(screen.queryByRole("complementary", { name: "Copilot" })).toBeNull();
  const tab = screen.getByRole("button", { name: "Open the Copilot" });
  expect(tab.querySelector("svg")).not.toBeNull();
  cleanup();
  renderAt("/settings");
  fireEvent.click(
    await screen.findByRole("button", { name: "Open the Copilot" }),
  );
  expect(await openSidebar()).toBeDefined();
});

it("collapses on Escape where it sits over the page, on a narrow window, and not beside it", async () => {
  stubApi({});
  const narrow = vi.fn((query: string) => ({ matches: query === OVERLAY }));
  vi.stubGlobal("matchMedia", narrow);
  renderAt("/settings");
  const escape = async () => {
    fireEvent.keyDown(
      (await openSidebar()).getByRole("button", { name: "New conversation" }),
      { key: "Escape" },
    );
  };
  await escape();
  const tab = screen.getByRole("button", { name: "Open the Copilot" });
  expect(document.activeElement).toBe(tab);
  fireEvent.click(tab);
  expect(document.activeElement).toBe(
    sidebar()
      .getByRole("button", { name: "New conversation" })
      .closest("aside"),
  );
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
  await escape();
  expect(await openSidebar()).toBeDefined();
  expect(narrow).toHaveBeenCalledWith(OVERLAY);
});

it("greets the handler by first name with questions to click", async () => {
  const fetchMock = stubApi({
    [`POST ${CONVERSATIONS}`]: conversation(
      turn({ status: "working", answer: null }),
    ),
  });
  renderAt("/settings");
  const copilot = await openSidebar();
  expect(copilot.getByText("Hello, Dana.")).toBeDefined();
  const questions = within(
    copilot.getByRole("list", { name: "Questions to ask" }),
  );
  expect(questions.getAllByRole("button").map((b) => b.textContent)).toEqual([
    "What needs me today?",
    "How did the latest dispatch go?",
    "Are we meeting the success criteria we agreed?",
    "What does the policy wording say about baggage delays?",
  ]);
  fireEvent.click(
    questions.getByRole("button", { name: "What needs me today?" }),
  );
  await waitFor(() => {
    expect(sent(fetchMock, `POST ${CONVERSATIONS}`)).toEqual([
      { message: "What needs me today?" },
    ]);
  });
});

it("sends with Enter, starts a new line with Shift+Enter", async () => {
  const fetchMock = stubApi({
    [`POST ${CONVERSATIONS}`]: conversation(
      turn({ status: "working", answer: null }),
    ),
  });
  renderAt("/settings");
  const box = (await openSidebar()).getByRole("textbox", { name: ASK });
  fireEvent.change(box, { target: { value: "Line one" } });
  fireEvent.keyDown(box, { key: "Enter", shiftKey: true });
  expect(sent(fetchMock, `POST ${CONVERSATIONS}`)).toEqual([]);
  fireEvent.keyDown(box, { key: "Enter" });
  await waitFor(() => {
    expect(sent(fetchMock, `POST ${CONVERSATIONS}`)).toEqual([
      { message: "Line one" },
    ]);
  });
  expect(freshAccessToken).toHaveBeenCalled();
});

it("holds the box while a turn works or a confirmation waits", async () => {
  showConversation(turn({ status: "working", answer: null }));
  const copilot = await openSidebar();
  await waitFor(() => {
    expect(copilot.getByRole<HTMLTextAreaElement>("textbox").disabled).toBe(
      true,
    );
  });
  cleanup();
  showConversation(waiting());
  const held = (await openSidebar()).getByRole<HTMLTextAreaElement>("textbox");
  await waitFor(() => {
    expect(held.placeholder).toBe(ANSWER_FIRST);
  });
  expect(held.disabled).toBe(true);
});

const readsOf = (fetchMock: ReturnType<typeof stubApi>) =>
  sent(fetchMock, `GET ${CONVERSATION_PATH}`).length;

it("reads the conversation once a second while a turn works, and not after", async () => {
  vi.useFakeTimers();
  const working = showConversation(turn({ status: "working", answer: null }));
  await act(() => vi.advanceTimersByTimeAsync(0));
  expect(readsOf(working)).toBe(1);
  await act(() => vi.advanceTimersByTimeAsync(3000));
  expect(readsOf(working)).toBe(4);
  for (const status of [
    "done",
    "failed",
    "stopped",
    "waiting_for_confirmation",
  ] as const) {
    cleanup();
    const ended = showConversation(turn({ status }));
    await act(() => vi.advanceTimersByTimeAsync(3000));
    expect(readsOf(ended)).toBe(1);
  }
});

it("stops reading the conversation while the sidebar is collapsed", async () => {
  vi.useFakeTimers();
  const working = showConversation(turn({ status: "working", answer: null }));
  await act(() => vi.advanceTimersByTimeAsync(0));
  fireEvent.click(
    sidebar().getByRole("button", { name: "Collapse the Copilot" }),
  );
  await act(() => vi.advanceTimersByTimeAsync(3000));
  expect(readsOf(working)).toBe(1);
});

it("sends a second message in the conversation, showing it working at once", async () => {
  openedBefore();
  const fetchMock = stubApi({
    [`GET ${CONVERSATION_PATH}`]: conversation(turn()),
    [`POST ${CONVERSATION_PATH}/messages`]: conversation(
      turn(),
      turn({
        turn_id: "turn-2",
        number: 2,
        message: "And tomorrow?",
        status: "working",
        answer: null,
      }),
    ),
  });
  renderAt("/settings");
  const copilot = await openSidebar();
  await copilot.findByText("Nothing needs you today.");
  const box = copilot.getByRole<HTMLTextAreaElement>("textbox", { name: ASK });
  fireEvent.change(box, { target: { value: "And tomorrow?" } });
  fireEvent.keyDown(box, { key: "Enter" });
  expect(await copilot.findByText("And tomorrow?")).toBeDefined();
  expect(sent(fetchMock, `POST ${CONVERSATION_PATH}/messages`)).toEqual([
    { message: "And tomorrow?" },
  ]);
  expect(box.value).toBe("");
  expect(box.placeholder).toBe(STILL_WORKING);
  expect(box.disabled).toBe(true);
});

it("reads the conversation again when a message is refused, to show its failed turn", async () => {
  openedBefore();
  const fetchMock = stubApi({
    [`GET ${CONVERSATION_PATH}`]: conversation(turn()),
    [`POST ${CONVERSATION_PATH}/messages`]: new Refusal(
      503,
      "The Copilot isn't running",
    ),
  });
  renderAt("/settings");
  const copilot = await openSidebar();
  await copilot.findByText("Nothing needs you today.");
  const box = copilot.getByRole("textbox", { name: ASK });
  fireEvent.change(box, { target: { value: "And tomorrow?" } });
  fireEvent.keyDown(box, { key: "Enter" });
  expect(await copilot.findByText("The Copilot isn't running")).toBeDefined();
  await waitFor(() => {
    expect(sent(fetchMock, `GET ${CONVERSATION_PATH}`)).toHaveLength(2);
  });
});

it("keeps a refused message in the box, with the app's reason", async () => {
  stubApi({
    [`POST ${CONVERSATIONS}`]: new Refusal(422, "The message is too long"),
  });
  renderAt("/settings");
  const copilot = await openSidebar();
  const box = copilot.getByRole<HTMLTextAreaElement>("textbox", { name: ASK });
  fireEvent.change(box, { target: { value: "What needs me today?" } });
  fireEvent.keyDown(box, { key: "Enter" });
  expect(await copilot.findByText("The message is too long")).toBeDefined();
  expect(box.value).toBe("What needs me today?");
  expect(box.disabled).toBe(false);
});

it("starts afresh when the app no longer has the conversation open", async () => {
  openedBefore();
  const fetchMock = stubApi({
    [`POST ${CONVERSATIONS}`]: conversation(
      turn({ status: "working", answer: null }),
    ),
  });
  renderAt("/settings");
  const copilot = await openSidebar();
  expect(await copilot.findByText("Hello, Dana.")).toBeDefined();
  await waitFor(() => {
    expect(savedConversation("HND-01")).toBeUndefined();
  });
  const box = copilot.getByRole("textbox", { name: ASK });
  fireEvent.change(box, { target: { value: "What needs me today?" } });
  fireEvent.keyDown(box, { key: "Enter" });
  await waitFor(() => {
    expect(sent(fetchMock, `POST ${CONVERSATIONS}`)).toEqual([
      { message: "What needs me today?" },
    ]);
  });
  expect(sent(fetchMock, `POST ${CONVERSATION_PATH}/messages`)).toEqual([]);
});

it("says why a conversation couldn't be read", async () => {
  openedBefore();
  stubApi({ [`GET ${CONVERSATION_PATH}`]: new Refusal(500, "Server error") });
  renderAt("/settings");
  const copilot = await openSidebar();
  expect((await copilot.findByRole("alert")).textContent).toContain(
    "Server error",
  );
  expect(copilot.queryByText("Hello, Dana.")).toBeNull();
});

it("tells a screen reader where the latest turn stands, once", async () => {
  showConversation(turn({ status: "working", answer: null, steps: [step()] }));
  const copilot = await openSidebar();
  await copilot.findByRole("list", { name: "Steps" });
  const statuses = copilot.getAllByRole("status");
  expect(statuses.map((status) => status.textContent)).toEqual([
    "The Copilot is working",
  ]);
  expect(
    copilot
      .getByRole("list", { name: "Conversation" })
      .getAttribute("aria-live"),
  ).toBeNull();
});

it("says what went wrong in a failed turn and that a stopped turn stopped", async () => {
  showConversation(
    turn({ status: "failed", answer: null, failure: "RuntimeError: It broke" }),
  );
  const copilot = await openSidebar();
  expect(await copilot.findByText(/RuntimeError: It broke/)).toBeDefined();
  expect(copilot.getByRole<HTMLTextAreaElement>("textbox").disabled).toBe(
    false,
  );
  cleanup();
  showConversation(turn({ status: "stopped", answer: null }));
  const stopped = await openSidebar();
  expect(
    await stopped.findByText(/This turn stopped before it finished/),
  ).toBeDefined();
  expect(stopped.getByRole<HTMLTextAreaElement>("textbox").disabled).toBe(
    false,
  );
});

it("lists the earlier conversations newest first, and New conversation empties the sidebar", async () => {
  openedBefore();
  const fetchMock = stubApi({
    [`GET ${CONVERSATION_PATH}`]: conversation(turn()),
    [`GET ${CONVERSATIONS}`]: [
      {
        conversation_id: "conversation-2",
        title: "How did the latest dispatch go?",
        created_at: "2026-10-10T10:00:00.000+00:00",
      },
      {
        conversation_id: "conversation-1",
        title: "What needs me today?",
        created_at: "2026-10-10T09:00:00.000+00:00",
      },
    ],
  });
  renderAt("/settings");
  const copilot = await openSidebar();
  expect(await copilot.findByText("Nothing needs you today.")).toBeDefined();
  expect(sent(fetchMock, `GET ${CONVERSATIONS}`)).toEqual([]);
  fireEvent.click(
    copilot.getByRole("button", { name: "Earlier conversations" }),
  );
  const titles = await copilot.findAllByRole("button", { name: /\?/ });
  expect(
    titles.map((t) => t.querySelector(".earlier-title")?.textContent),
  ).toEqual(["How did the latest dispatch go?", "What needs me today?"]);
  fireEvent.click(copilot.getByRole("button", { name: "Back" }));
  fireEvent.click(copilot.getByRole("button", { name: "New conversation" }));
  expect(await copilot.findByText("Hello, Dana.")).toBeDefined();
  expect(copilot.queryByText("Nothing needs you today.")).toBeNull();
});
