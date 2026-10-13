import { expect, it, vi } from "vitest";

// auth.ts itself, on a stand-in for supabase-js's client.
const supabase = vi.hoisted(() => ({
  auth: {
    signInWithPassword: vi.fn(),
    signOut: vi.fn(() => Promise.resolve({ error: null })),
    getSession: vi.fn(),
    refreshSession: vi.fn(),
    onAuthStateChange: vi.fn<
      (tell: (event: string, session: object | null) => void) => {
        data: { subscription: { unsubscribe: () => void } };
      }
    >(),
  },
}));
const createClient = vi.hoisted(() => vi.fn(() => supabase));

vi.mock("@supabase/supabase-js", () => ({ createClient }));
vi.unmock("./auth");

const auth = await import("./auth");
// Vitest clears the calls before each test, so keep how the client was made.
const made = [...createClient.mock.calls];

it("makes the client from the environment once", () => {
  expect(made).toEqual([["https://supabase.test", "test-publishable-key"]]);
});

it("signs in with an email and a password", async () => {
  supabase.auth.signInWithPassword.mockResolvedValue({ error: null });
  await auth.signIn("dana@example.com", "secret");
  expect(supabase.auth.signInWithPassword).toHaveBeenCalledWith({
    email: "dana@example.com",
    password: "secret",
  });
});

it("says plainly when the email or password is wrong", async () => {
  supabase.auth.signInWithPassword.mockResolvedValue({
    error: {
      code: "invalid_credentials",
      message: "Invalid login credentials",
    },
  });
  await expect(auth.signIn("dana@example.com", "wrong")).rejects.toThrow(
    auth.WRONG_PASSWORD,
  );
});

it("passes on any other refusal", async () => {
  supabase.auth.signInWithPassword.mockResolvedValue({
    error: { code: "over_request_rate_limit", message: "Too many requests" },
  });
  await expect(auth.signIn("dana@example.com", "secret")).rejects.toThrow(
    "Too many requests",
  );
});

it("signs out of this browser only", async () => {
  await auth.signOut();
  expect(supabase.auth.signOut).toHaveBeenCalledWith({ scope: "local" });
});

it("gives the session's access token, or nothing", async () => {
  supabase.auth.getSession.mockResolvedValue({
    data: { session: { access_token: "token-1" } },
  });
  expect(await auth.accessToken()).toBe("token-1");
  supabase.auth.getSession.mockResolvedValue({ data: { session: null } });
  expect(await auth.accessToken()).toBeUndefined();
});

it("follows sign-ins and sign-outs until told to stop", () => {
  const unsubscribe = vi.fn();
  supabase.auth.onAuthStateChange.mockReturnValue({
    data: { subscription: { unsubscribe } },
  });
  const seen: boolean[] = [];
  const stop = auth.followSession((signedIn) => seen.push(signedIn));
  const [[tell]] = supabase.auth.onAuthStateChange.mock.calls;
  tell("INITIAL_SESSION", null);
  tell("SIGNED_IN", { access_token: "token-1" });
  expect(seen).toEqual([false, true]);
  stop();
  expect(unsubscribe).toHaveBeenCalled();
});

it("renews a sign-in with less than 20 minutes left before the Copilot gets it", async () => {
  const now = Date.now() / 1000;
  supabase.auth.refreshSession.mockResolvedValue({
    data: { session: { access_token: "token-2" } },
    error: null,
  });
  supabase.auth.getSession.mockResolvedValue({
    data: { session: { access_token: "token-1", expires_at: now + 21 * 60 } },
  });
  expect(await auth.freshAccessToken()).toBe("token-1");
  expect(supabase.auth.refreshSession).not.toHaveBeenCalled();
  supabase.auth.getSession.mockResolvedValue({
    data: { session: { access_token: "token-1", expires_at: now + 19 * 60 } },
  });
  expect(await auth.freshAccessToken()).toBe("token-2");
  expect(supabase.auth.refreshSession).toHaveBeenCalledTimes(1);
  supabase.auth.getSession.mockResolvedValue({ data: { session: null } });
  expect(await auth.freshAccessToken()).toBeUndefined();
});

it("passes on a renewal Supabase refuses", async () => {
  supabase.auth.getSession.mockResolvedValue({
    data: { session: { access_token: "token-1", expires_at: 0 } },
  });
  supabase.auth.refreshSession.mockResolvedValue({
    data: { session: null },
    error: { message: "Refresh token expired" },
  });
  await expect(auth.freshAccessToken()).rejects.toThrow(
    "Refresh token expired",
  );
});
