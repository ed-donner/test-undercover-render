import { defineConfig } from "@playwright/test";
import {
  AGENT_KEY,
  AGENT_STAND_IN,
  BACKEND,
  AUTH_STAND_IN,
  COPILOT_STAND_IN,
  DASHBOARD,
  JUDGE_STAND_IN,
} from "./e2e/servers";
import { HANDLERS, TEST_PASSWORD } from "./e2e/handlers";

// The tests run their own backend and dashboard, on their own ports and
// database, so they never touch the servers started by `npm run dev`. Every
// test runs signed in as Dana Whitfield unless it chooses another handler.
export default defineConfig({
  testDir: "e2e",
  outputDir: "e2e/test-results",
  reporter: "list",
  // The test files share one database and one set of stand-ins, so they run one
  // at a time and never see each other's work part done.
  workers: 1,
  use: { baseURL: DASHBOARD },
  projects: [
    { name: "sign in", testMatch: /sign_in\.setup\.ts/ },
    {
      name: "dashboard",
      dependencies: ["sign in"],
      use: { storageState: HANDLERS.dana.storage },
    },
  ],
  webServer: [
    {
      command: `uv run -m backend.seed && uv run -m uvicorn backend.main:app --port ${new URL(BACKEND).port}`,
      url: `${BACKEND}/api/health`,
      // Empty DATABASE_URL, MODEL_NAME, UNDERCOVER_AGENT_RUNTIME and
      // UNDERCOVER_COPILOT_RUNTIME keep the tests on SQLite, the default model and
      // the stand-ins for the agent and the Copilot, whatever the shell has.
      env: {
        UNDERCOVER_DB: "e2e/undercover.db",
        DATABASE_URL: "",
        MODEL_NAME: "",
        UNDERCOVER_AGENT: AGENT_STAND_IN,
        UNDERCOVER_AGENT_RUNTIME: "",
        UNDERCOVER_COPILOT: COPILOT_STAND_IN,
        UNDERCOVER_COPILOT_RUNTIME: "",
        VITE_SUPABASE_URL: AUTH_STAND_IN,
        JUDGE_URL: JUDGE_STAND_IN,
        OPENROUTER_API_KEY: "e2e-key",
        UNDERCOVER_API_KEY: AGENT_KEY,
      },
    },
    {
      command: "node e2e/judge_stand_in.ts",
      url: `${JUDGE_STAND_IN}/health`,
      env: { PORT: new URL(JUDGE_STAND_IN).port },
    },
    {
      command: "node e2e/agent_stand_in.ts",
      url: `${AGENT_STAND_IN}/ping`,
      env: {
        PORT: new URL(AGENT_STAND_IN).port,
        UNDERCOVER_API: BACKEND,
        UNDERCOVER_API_KEY: AGENT_KEY,
      },
    },
    {
      command: "node e2e/copilot_stand_in.ts",
      url: `${COPILOT_STAND_IN}/ping`,
      env: { PORT: new URL(COPILOT_STAND_IN).port, UNDERCOVER_API: BACKEND },
    },
    {
      command: "node e2e/auth_stand_in.ts",
      url: `${AUTH_STAND_IN}/auth/v1/.well-known/jwks.json`,
      env: {
        PORT: new URL(AUTH_STAND_IN).port,
        HANDLER_PASSWORD: TEST_PASSWORD,
        DASHBOARD,
      },
    },
    {
      command: `npx vite dashboard --port ${new URL(DASHBOARD).port} --strictPort --mode e2e`,
      url: DASHBOARD,
      env: {
        UNDERCOVER_API: BACKEND,
        VITE_SUPABASE_URL: AUTH_STAND_IN,
        VITE_SUPABASE_PUBLISHABLE_KEY: "e2e-publishable-key",
      },
    },
  ],
});
