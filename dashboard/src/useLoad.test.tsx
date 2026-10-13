import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ApiError } from "./api";
import { REFRESH_MS, useLoad } from "./useLoad";

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

const wait = (ms: number) => act(() => vi.advanceTimersByTimeAsync(ms));

// A backend that answers each request after answerMs with how many it has
// answered, counting the requests it's answering at once.
function backend(answerMs: number) {
  let answered = 0;
  const inFlight = { now: 0, most: 0 };
  const load = vi.fn(
    () =>
      new Promise<number>((resolve) => {
        inFlight.now += 1;
        inFlight.most = Math.max(inFlight.most, inFlight.now);
        setTimeout(() => {
          inFlight.now -= 1;
          answered += 1;
          resolve(answered);
        }, answerMs);
      }),
  );
  return { load, inFlight };
}

it("shows a slow answer, and asks again only once it has one", async () => {
  // Slower than the refresh, as a busy backend is.
  const answerMs = REFRESH_MS + 1000;
  const cycle = answerMs + REFRESH_MS;
  const { load, inFlight } = backend(answerMs);
  const { result } = renderHook(() => useLoad(load, REFRESH_MS));

  await wait(answerMs);
  expect(result.current.data).toBe(1);
  await wait(2 * cycle + 100);
  expect(result.current.data).toBe(3);
  expect(inFlight.most).toBe(1);
});

it("asks every refresh while the answers come quickly", async () => {
  const { load } = backend(100);
  const { result } = renderHook(() => useLoad(load, REFRESH_MS));

  await wait(100);
  expect(result.current.data).toBe(1);
  await wait(REFRESH_MS + 100);
  expect(result.current.data).toBe(2);
  expect(load).toHaveBeenCalledTimes(2);
});

it("keeps asking after an error, keeping the data it had", async () => {
  const load = vi
    .fn<() => Promise<number>>()
    .mockResolvedValueOnce(1)
    .mockRejectedValueOnce(new ApiError(500, "Server error"))
    .mockResolvedValueOnce(3);
  const { result } = renderHook(() => useLoad(load, REFRESH_MS));

  await wait(0);
  expect(result.current.data).toBe(1);
  await wait(REFRESH_MS);
  expect(result.current.error?.message).toBe("Server error");
  expect(result.current.data).toBe(1);
  await wait(REFRESH_MS);
  expect(result.current.data).toBe(3);
  expect(load).toHaveBeenCalledTimes(3);
});

it("stops asking for data that isn't found", async () => {
  const load = vi.fn(() => Promise.reject(new ApiError(404, "Not found")));
  renderHook(() => useLoad(load, REFRESH_MS));
  await wait(5 * REFRESH_MS);
  expect(load).toHaveBeenCalledTimes(1);
});

it("shows only the answer asked for after a reload", async () => {
  const { load } = backend(REFRESH_MS);
  const { result } = renderHook(() => useLoad(load, REFRESH_MS));

  await wait(REFRESH_MS / 2);
  act(() => {
    result.current.reload();
  });
  // The first request answers 1, which the reload has made out of date.
  await wait(REFRESH_MS / 2);
  expect(result.current.data).toBeUndefined();
  await wait(REFRESH_MS / 2);
  expect(result.current.data).toBe(2);
});

it("stops asking once it's unmounted", async () => {
  const { load } = backend(100);
  const { unmount } = renderHook(() => useLoad(load, REFRESH_MS));
  await wait(100);
  unmount();
  await wait(5 * REFRESH_MS);
  expect(load).toHaveBeenCalledTimes(1);
});
