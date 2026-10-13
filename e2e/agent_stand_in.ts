// Stands in for the agent's AgentCore app in the end-to-end tests: it answers
// /ping, answers the health check, and takes every other payload the backend
// posts to /invocations with the agent's key, starting nothing and listing them
// at /api/started. On POST /api/stop it stops each run and round it was given
// that's still going, through the app's operations with the agent's key, so the
// next test can start its own.
import { createServer } from "node:http";
import { json } from "node:stream/consumers";
import type { Payload } from "./api";
import { roundPath, runPath } from "./paths.ts";
import { reply } from "./stand_in.ts";

const started: Payload[] = [];
const app = process.env.UNDERCOVER_API ?? "";
const key = process.env.UNDERCOVER_API_KEY ?? "";
const OVER = { reason: "The test is over" };

// Stops one piece of work the stand-in was given, if it's still going; the app
// leaves one that isn't as it is.
async function stop(path: string) {
  const response = await fetch(`${app}${path}/failure`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-API-Key": key },
    body: JSON.stringify(OVER),
  });
  if (!response.ok)
    throw new Error(`${path}/failure answered ${String(response.status)}`);
}

async function stopTheWork() {
  for (const payload of started) {
    if (payload.operation === "work_run")
      await stop(runPath(String(payload.run_id)));
    else if (typeof payload.round_id === "string")
      await stop(roundPath(payload.round_id));
  }
}

createServer((request, response) => {
  const url = request.url ?? "";
  if (request.method === "POST" && url === "/invocations") {
    json(request).then(
      (payload) => {
        const taken = payload as Payload;
        if (taken.operation === "health") {
          reply(response, 200, { healthy: true });
          return;
        }
        if (request.headers.authorization !== `Bearer ${key}`) {
          reply(response, 401, { detail: "This needs the agent's API key" });
          return;
        }
        started.push(taken);
        reply(response, 200, { accepted: true });
      },
      () => {
        reply(response, 400, { error: "Invalid JSON" });
      },
    );
  } else if (request.method === "POST" && url === "/api/stop") {
    stopTheWork().then(
      () => {
        reply(response, 200, { stopped: true });
      },
      (error: unknown) => {
        reply(response, 500, { error: String(error) });
      },
    );
  } else if (url === "/ping") {
    reply(response, 200, { status: "Healthy" });
  } else if (url === "/api/started") {
    reply(response, 200, started);
  } else {
    reply(response, 404, { error: "Not found" });
  }
}).listen(Number(process.env.PORT), "127.0.0.1");
