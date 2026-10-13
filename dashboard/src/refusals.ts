// How a refusal from the backend reads: its status, and its reason as a
// sentence a handler can act on.

export const REQUEST_FAILED = "The request failed";

// How FastAPI refuses a request it can't accept, one entry for each input.
interface InputError {
  loc: (string | number)[];
  msg: string;
}

function isInputErrors(detail: unknown): detail is InputError[] {
  return (
    Array.isArray(detail) &&
    detail.every(
      (error: unknown) =>
        typeof error === "object" &&
        error !== null &&
        "loc" in error &&
        "msg" in error,
    )
  );
}

// The backend's reason for refusing, as a sentence a handler can act on.
export function reasonFor(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (isInputErrors(detail))
    return detail
      .map((error) => `${error.loc.slice(1).join(".")}: ${error.msg}`)
      .join("; ");
  return REQUEST_FAILED;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}
