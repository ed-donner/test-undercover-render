import { createClient } from "@supabase/supabase-js";

// The dashboard's only way to Supabase Auth. The project's address and its
// publishable key are meant to be public, and supabase-js keeps the session
// in the browser and refreshes its access token.
const supabase = createClient(
  import.meta.env.VITE_SUPABASE_URL,
  import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY,
);

export const WRONG_PASSWORD = "The email or password is wrong.";

// Signs a handler in, or throws Supabase's reason for refusing.
export async function signIn(email: string, password: string): Promise<void> {
  const { error } = await supabase.auth.signInWithPassword({ email, password });
  if (error)
    throw new Error(
      error.code === "invalid_credentials" ? WRONG_PASSWORD : error.message,
    );
}

// Signs the handler out of this browser only.
export async function signOut(): Promise<void> {
  await supabase.auth.signOut({ scope: "local" });
}

// The session's access token, or nothing when no one is signed in.
export async function accessToken(): Promise<string | undefined> {
  const { data } = await supabase.auth.getSession();
  return data.session?.access_token;
}

// A sign-in lasts an hour; one with less than this left is renewed before the
// Copilot is given it, so it lasts the Copilot's turn.
export const RENEW_WITHIN_SECONDS = 20 * 60;

// The session's access token, renewed first when it has less than
// RENEW_WITHIN_SECONDS left, or nothing when no one is signed in.
export async function freshAccessToken(): Promise<string | undefined> {
  const { data } = await supabase.auth.getSession();
  const session = data.session;
  if (!session) return undefined;
  const left = (session.expires_at ?? 0) - Date.now() / 1000;
  if (left >= RENEW_WITHIN_SECONDS) return session.access_token;
  const { data: renewed, error } = await supabase.auth.refreshSession();
  if (error) throw new Error(error.message);
  return renewed.session?.access_token;
}

// Tells the callback whether a handler is signed in, at once and again on each
// sign-in and sign-out, until the function it returns is called.
export function followSession(
  callback: (signedIn: boolean) => void,
): () => void {
  const { data } = supabase.auth.onAuthStateChange((_event, session) => {
    callback(session !== null);
  });
  return () => {
    data.subscription.unsubscribe();
  };
}
