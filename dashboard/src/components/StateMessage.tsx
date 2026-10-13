import { ApiError } from "../refusals";

export const TRY_AGAIN = "Reload the page to try again.";

// What a page or a panel shows in place of its data, saying what to do next:
// that it's loading, that there's nothing to show yet, that what was asked for
// wasn't found, or why it failed. A refusal, such as a sign-in that isn't a
// handler's, won't pass with a reload, so it isn't offered.
export function StateMessage({
  error,
  notFound,
  empty,
}: Readonly<{ error?: Error; notFound?: string; empty?: string }>) {
  if (notFound && error instanceof ApiError && error.status === 404)
    return (
      <p className="message" role="status">
        {notFound}
      </p>
    );
  if (error instanceof ApiError && error.status < 500)
    return (
      <p className="message" role="alert">
        {error.message}
      </p>
    );
  if (error)
    return (
      <p className="message" role="alert">
        {error.message} <span className="muted">{TRY_AGAIN}</span>
      </p>
    );
  return (
    <p className="message" role="status">
      {empty ?? "Loading..."}
    </p>
  );
}
