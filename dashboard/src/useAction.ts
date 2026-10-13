import { useState } from "react";
import { REQUEST_FAILED } from "./refusals";

// Runs an action that asks the backend to do one thing, such as signing off a
// payout or saving the settings, one request at a time, and keeps the
// backend's reason if it refuses.
export function useAction(action: () => Promise<unknown>) {
  const [error, setError] = useState<string>();
  const [sending, setSending] = useState(false);

  function run() {
    if (sending) return;
    setSending(true);
    setError(undefined);
    action()
      .catch((reason: unknown) => {
        setError(reason instanceof Error ? reason.message : REQUEST_FAILED);
      })
      .finally(() => {
        setSending(false);
      });
  }

  return { run, sending, error };
}
