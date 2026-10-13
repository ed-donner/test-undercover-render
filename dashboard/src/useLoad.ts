import { useCallback, useEffect, useState } from "react";
import { ApiError, REQUEST_FAILED } from "./refusals";

export const REFRESH_MS = 2000;

export interface Loaded<T> {
  data?: T;
  error?: Error;
  reload: () => void;
  // Shows what the backend just gave back for a change, such as the
  // conversation after a message, then asks again from there.
  show: (data: T) => void;
}

// What came back, kept with the load it came from, so a different load, such as
// another claim's page, starts afresh rather than showing the last one's data.
interface Answer<T> {
  load?: () => Promise<T>;
  data?: T;
  error?: Error;
}

// Loads data once, or again refreshMs milliseconds after each answer when that's
// given, while keepAsking says so of the data, if given, stopping if the data
// isn't found, and again whenever reload or show is called. Waiting for each
// answer before asking again means a slow backend is never sent a pile of
// requests, and every answer shows.
// `load` and `keepAsking` must keep the same identity between renders, as with
// useCallback or a function outside the component.
export function useLoad<T>(
  load: () => Promise<T>,
  refreshMs?: number,
  keepAsking?: (data: T) => boolean,
): Loaded<T> {
  const [answer, setAnswer] = useState<Answer<T>>({});
  const [version, setVersion] = useState(0);

  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    function askAgain() {
      if (refreshMs !== undefined) timer = setTimeout(fetchNow, refreshMs);
    }
    function fetchNow() {
      load().then(
        (data) => {
          if (!active) return;
          setAnswer({ load, data });
          if (keepAsking?.(data) ?? true) askAgain();
        },
        (error: unknown) => {
          if (!active) return;
          setAnswer((previous) => ({
            load,
            data: previous.load === load ? previous.data : undefined,
            error: error instanceof Error ? error : new Error(REQUEST_FAILED),
          }));
          if (!(error instanceof ApiError && error.status === 404)) askAgain();
        },
      );
    }
    fetchNow();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [load, refreshMs, keepAsking, version]);

  const reload = useCallback(() => {
    setVersion((current) => current + 1);
  }, []);
  const show = useCallback(
    (data: T) => {
      setAnswer({ load, data });
      setVersion((current) => current + 1);
    },
    [load],
  );
  const current = answer.load === load ? answer : {};
  return { data: current.data, error: current.error, reload, show };
}
