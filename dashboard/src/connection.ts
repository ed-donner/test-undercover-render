import { accessToken } from "./auth";
import { ApiError, reasonFor } from "./refusals";

// How the dashboard's API sends each request to the backend and reads its
// answer or its refusal. Only api.ts uses it.

// Sends a request with the signed-in handler's access token, if any. A message to
// the Copilot, or an answer to its confirmation, goes with a sign-in renewed
// first when it has little time left, since the Copilot works with it.
export async function request<T>(
  path: string,
  init: RequestInit = {},
  signIn: () => Promise<string | undefined> = accessToken,
): Promise<T> {
  const token = await signIn();
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(path, { ...init, headers });
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as {
      detail?: unknown;
    };
    throw new ApiError(response.status, reasonFor(body.detail));
  }
  return (await response.json()) as T;
}

export function send<T>(
  method: "POST" | "PUT",
  path: string,
  body?: object,
  signIn: () => Promise<string | undefined> = accessToken,
) {
  if (body === undefined) return request<T>(path, { method }, signIn);
  const headers = { "Content-Type": "application/json" };
  return request<T>(
    path,
    { method, headers, body: JSON.stringify(body) },
    signIn,
  );
}

export const post = <T>(path: string, body?: object) =>
  send<T>("POST", path, body);
