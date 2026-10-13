// Stands in for the agent's service in the end-to-end tests: it accepts each
// dispatch, evaluation or round the backend asks it to start, listing them at
// /api/started, and each review of the improver's proposals it passes on, listing
// them at /api/reviews.
import { createServer, type IncomingMessage } from "node:http";
import { json } from "node:stream/consumers";
import type { Started } from "./api";
import { reply } from "./stand_in.ts";

const started: Started[] = [];
const reviews: Started[] = [];
const STARTS = new Set(["/api/dispatches", "/api/evaluations", "/api/rounds"]);
const REVIEW = /^\/api\/rounds\/[^/]+\/proposals\/[^/]+\/review$/;

createServer((request, response) => {
  const url = request.url ?? "";
  const accept = (into: Started[]) => {
    keep(request, url, into).then(
      () => {
        reply(response, 202, { status: "accepted" });
      },
      () => {
        reply(response, 422, { detail: "The body isn't JSON" });
      },
    );
  };
  if (request.method === "POST" && STARTS.has(url)) {
    accept(started);
  } else if (request.method === "POST" && REVIEW.test(url)) {
    accept(reviews);
  } else if (url === "/api/started") {
    reply(response, 200, started);
  } else if (url === "/api/reviews") {
    reply(response, 200, reviews);
  } else if (url === "/api/health") {
    reply(response, 200, { status: "ok" });
  } else {
    reply(response, 404, { detail: "Not found" });
  }
}).listen(Number(process.env.PORT), "127.0.0.1");

async function keep(request: IncomingMessage, path: string, into: Started[]) {
  into.push({ path, body: await json(request) });
}
