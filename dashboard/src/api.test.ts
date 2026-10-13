import { afterEach, expect, it, vi } from "vitest";
import { api } from "./api";
import { ApiError } from "./refusals";
import {
  CONVERSATIONS,
  CONVERSATION_ID,
  CONVERSATION_PATH,
  conversation,
} from "./copilotTesting";
import { TOKEN, endSession, freshAccessToken } from "./fakeAuth";
import { Refusal, claim, stubApi } from "./testing";

afterEach(() => {
  vi.unstubAllGlobals();
});

it("reads the backend's JSON", async () => {
  stubApi({ "GET /api/claims/CLM-1002": claim });
  expect((await api.getClaim("CLM-1002")).summary).toBe(claim.summary);
});

it("raises the backend's reason for refusing", async () => {
  stubApi({ "GET /api/claims/CLM-1002": new Refusal(409, "Not now") });
  await expect(api.getClaim("CLM-1002")).rejects.toEqual(
    new ApiError(409, "Not now"),
  );
});

it("falls back to a general message when the reason isn't text", async () => {
  stubApi({ "GET /api/configuration": new Refusal(422, [{ msg: "bad" }]) });
  await expect(api.getConfiguration()).rejects.toThrow("The request failed");
});

it("falls back to a general message when the body isn't JSON", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve(new Response("Internal Server Error", { status: 500 })),
    ),
  );
  await expect(api.getConfiguration()).rejects.toEqual(
    new ApiError(500, "The request failed"),
  );
});

it("sends the session's access token with every request", async () => {
  const fetchMock = stubApi({
    "GET /api/claims/CLM-1002": claim,
    "POST /api/claims/CLM-1002/sign-off": claim,
  });
  await api.getClaim("CLM-1002");
  await api.signOff("CLM-1002");
  const headers = fetchMock.mock.calls.map(([, init]) =>
    new Headers(init?.headers).get("Authorization"),
  );
  expect(headers).toEqual([`Bearer ${TOKEN}`, `Bearer ${TOKEN}`]);
});

it("sends no token when no one is signed in", async () => {
  endSession();
  const fetchMock = stubApi({ "GET /api/claims/CLM-1002": claim });
  await api.getClaim("CLM-1002");
  const [[, init]] = fetchMock.mock.calls;
  expect(new Headers(init?.headers).has("Authorization")).toBe(false);
});

it("sends the Copilot a message or an answer with a renewed sign-in, and reads with the session's", async () => {
  freshAccessToken
    .mockResolvedValueOnce("renewed-1")
    .mockResolvedValueOnce("renewed-2")
    .mockResolvedValueOnce("renewed-3");
  const fetchMock = stubApi({
    [`POST ${CONVERSATIONS}`]: conversation(),
    [`POST ${CONVERSATION_PATH}/messages`]: conversation(),
    [`POST ${CONVERSATION_PATH}/confirmation`]: conversation(),
    [`GET ${CONVERSATION_PATH}`]: conversation(),
    [`GET ${CONVERSATIONS}`]: [],
  });
  await api.startConversation("What needs me today?");
  await api.sendMessage(CONVERSATION_ID, "And tomorrow?");
  await api.answerConfirmation(CONVERSATION_ID, "turn-1", "sign_off");
  await api.getConversation(CONVERSATION_ID);
  await api.listConversations();
  const headers = fetchMock.mock.calls.map(([, init]) =>
    new Headers(init?.headers).get("Authorization"),
  );
  expect(headers).toEqual([
    "Bearer renewed-1",
    "Bearer renewed-2",
    "Bearer renewed-3",
    `Bearer ${TOKEN}`,
    `Bearer ${TOKEN}`,
  ]);
});
