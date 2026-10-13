import { useState } from "react";
import { REQUEST_FAILED } from "./refusals";

// Runs an action that asks the backend to do one thing, such as signing off a
// payout or sending the Copilot a message, one request at a time, and keeps the
// backend's reason if it refuses. `run` takes what the action does it with and
// says whether it was done.
export function useAction<A extends unknown[]>(
  action: (...args: A) => Promise<unknown>,
) {
  const [error, setError] = useState<string>();
  const [sending, setSending] = useState(false);

  async function run(...args: A): Promise<boolean> {
    if (sending) return false;
    setSending(true);
    setError(undefined);
    try {
      await action(...args);
      return true;
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : REQUEST_FAILED);
      return false;
    } finally {
      setSending(false);
    }
  }

  return { run, sending, error };
}
