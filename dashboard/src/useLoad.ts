import { useCallback, useEffect, useState } from "react";
import { ApiError, REQUEST_FAILED } from "./api";

export const REFRESH_MS = 2000;

export interface Loaded<T> {
  data?: T;
  error?: Error;
  reload: () => void;
}

// Loads data once, or again refreshMs milliseconds after each answer when that's
// given, stopping if the data isn't found, and again whenever reload is called.
// Waiting for each answer before asking again means a slow backend is never
// sent a pile of requests, and every answer shows.
// `load` must keep the same identity between renders, as with useCallback.
export function useLoad<T>(
  load: () => Promise<T>,
  refreshMs?: number,
): Loaded<T> {
  const [loaded, setLoaded] = useState<Omit<Loaded<T>, "reload">>({});
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
          setLoaded({ data });
          askAgain();
        },
        (error: unknown) => {
          if (!active) return;
          setLoaded((previous) => ({
            data: previous.data,
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
  }, [load, refreshMs, version]);

  const reload = useCallback(() => {
    setVersion((current) => current + 1);
  }, []);
  return { ...loaded, reload };
}
