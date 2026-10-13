// Stands in for Supabase Auth in the end-to-end tests. It signs in our three
// handlers with the test password, signing each access token with a key pair it
// makes as it starts, and serves the public key for the backend to check them.
// It answers the browser's cross-origin checks, since the dashboard calls it
// from another port.
import { generateKeyPairSync, randomUUID, sign } from "node:crypto";
import { readFileSync } from "node:fs";
import {
  createServer,
  type IncomingMessage,
  type ServerResponse,
} from "node:http";
import { json } from "node:stream/consumers";
import { reply } from "./stand_in.ts";

interface Handler {
  handler_id: string;
  email: string;
}

const handlers = JSON.parse(
  readFileSync("data/handlers.json", "utf8"),
) as Handler[];
const password = process.env.HANDLER_PASSWORD;
// The dashboard, the one origin the browser may call this from.
const dashboard = process.env.DASHBOARD ?? "";
const KEY_ID = "e2e-key";
const LIFETIME = 3600;
const { privateKey, publicKey } = generateKeyPairSync("ec", {
  namedCurve: "P-256",
});
const publicKeys = {
  keys: [{ ...publicKey.export({ format: "jwk" }), kid: KEY_ID, alg: "ES256" }],
};
// The handler each refresh token was given to.
const refreshTokens = new Map<string, Handler>();

const base64url = (data: string | Buffer) =>
  Buffer.from(data).toString("base64url");

function user(handler: Handler) {
  return {
    id: handler.handler_id,
    aud: "authenticated",
    role: "authenticated",
    email: handler.email,
    app_metadata: { provider: "email" },
    user_metadata: {},
    created_at: "2026-10-01T00:00:00Z",
  };
}

function accessToken(handler: Handler, expiresAt: number): string {
  const header = base64url(
    JSON.stringify({ alg: "ES256", typ: "JWT", kid: KEY_ID }),
  );
  const claims = base64url(
    JSON.stringify({
      sub: handler.handler_id,
      email: handler.email,
      aud: "authenticated",
      role: "authenticated",
      exp: expiresAt,
    }),
  );
  const signature = sign("sha256", Buffer.from(`${header}.${claims}`), {
    key: privateKey,
    dsaEncoding: "ieee-p1363",
  });
  return `${header}.${claims}.${base64url(signature)}`;
}

function session(handler: Handler) {
  const expiresAt = Math.floor(Date.now() / 1000) + LIFETIME;
  const refreshToken = randomUUID();
  refreshTokens.set(refreshToken, handler);
  return {
    access_token: accessToken(handler, expiresAt),
    token_type: "bearer",
    expires_in: LIFETIME,
    expires_at: expiresAt,
    refresh_token: refreshToken,
    user: user(handler),
  };
}

function answer(response: ServerResponse, status: number, body?: unknown) {
  reply(response, status, body, { "Access-Control-Allow-Origin": dashboard });
}

function refuse(response: ServerResponse) {
  answer(response, 400, {
    code: "invalid_credentials",
    error_code: "invalid_credentials",
    msg: "Invalid login credentials",
  });
}

async function token(request: IncomingMessage, response: ServerResponse) {
  const query = new URLSearchParams((request.url ?? "").split("?")[1]);
  const grant = query.get("grant_type");
  const body = (await json(request)) as Record<string, string | undefined>;
  const handler =
    grant === "password"
      ? handlers.find((h) => h.email === body.email)
      : refreshTokens.get(body.refresh_token ?? "");
  if (!handler || (grant === "password" && body.password !== password))
    refuse(response);
  else answer(response, 200, session(handler));
}

function signedInUser(request: IncomingMessage, response: ServerResponse) {
  const bearer = request.headers.authorization?.split(".")[1] ?? "";
  const { email } = JSON.parse(
    Buffer.from(bearer, "base64url").toString() || "{}",
  ) as { email?: string };
  const handler = handlers.find((h) => h.email === email);
  if (handler) answer(response, 200, user(handler));
  else answer(response, 401, { msg: "Invalid token" });
}

createServer((request, response) => {
  const path = (request.url ?? "").split("?")[0];
  if (request.method === "OPTIONS") {
    response.writeHead(204, {
      "Access-Control-Allow-Origin": dashboard,
      "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
      "Access-Control-Allow-Headers":
        request.headers["access-control-request-headers"] ?? "*",
    });
    response.end();
  } else if (request.method === "POST" && path === "/auth/v1/token") {
    token(request, response).catch(() => {
      refuse(response);
    });
  } else if (path === "/auth/v1/.well-known/jwks.json") {
    answer(response, 200, publicKeys);
  } else if (path === "/auth/v1/user") {
    signedInUser(request, response);
  } else if (request.method === "POST" && path === "/auth/v1/logout") {
    answer(response, 204);
  } else {
    answer(response, 404, { msg: "Not found" });
  }
}).listen(Number(process.env.PORT), "127.0.0.1");
