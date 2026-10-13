// The servers the end-to-end tests run on ports of their own, so they never touch
// the ones `npm run dev` starts: the backend, the dashboard, and the stand-ins
// for the agent's service, for Supabase Auth and for the judge.
export const BACKEND = "http://127.0.0.1:8001";
export const DASHBOARD = "http://localhost:5174";
export const AGENT_STAND_IN = "http://127.0.0.1:8003";
export const AUTH_STAND_IN = "http://127.0.0.1:8004";
export const JUDGE_STAND_IN = "http://127.0.0.1:8005";

// The test backend's API key for the agent's side, and the header that carries it.
export const AGENT_KEY = "e2e-agent-key-0123456789abcdefghijklmnopq";
export const AGENT_KEY_HEADERS = { "X-API-Key": AGENT_KEY };
