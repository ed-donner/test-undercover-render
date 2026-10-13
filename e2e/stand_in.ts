// What the end-to-end tests' stand-ins share: answering a request with JSON.
import type { ServerResponse } from "node:http";

export function reply(
  response: ServerResponse,
  status: number,
  body?: unknown,
  headers: Record<string, string> = {},
) {
  response.writeHead(status, {
    "Content-Type": "application/json",
    ...headers,
  });
  response.end(body === undefined ? undefined : JSON.stringify(body));
}
