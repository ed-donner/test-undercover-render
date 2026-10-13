import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// npm run dev and npm run build read .env from the repo root, when there is
// one; the environment's VITE_ variables come first. The unit tests and the
// end-to-end tests set their own values, so the checks never read it.
const REPO_ROOT = fileURLToPath(new URL("..", import.meta.url));
const READS_ENV = new Set(["development", "production"]);

// The libraries the dashboard uses, each in a chunk of its own beside the app's.
const LIBRARIES = [
  {
    name: "react",
    test: /node_modules[\\/](react|react-dom|react-router|scheduler)[\\/]/,
  },
  { name: "supabase", test: /node_modules[\\/]@supabase[\\/]/ },
  { name: "icons", test: /node_modules[\\/]lucide-react[\\/]/ },
];

export default defineConfig(({ mode }) => ({
  plugins: [react()],
  envDir: READS_ENV.has(mode) ? REPO_ROOT : false,
  build: {
    rolldownOptions: { output: { codeSplitting: { groups: LIBRARIES } } },
  },
  server: {
    proxy: { "/api": process.env.UNDERCOVER_API ?? "http://127.0.0.1:8000" },
  },
  test: {
    environment: "jsdom",
    env: {
      VITE_SUPABASE_URL: "https://supabase.test",
      VITE_SUPABASE_PUBLISHABLE_KEY: "test-publishable-key",
    },
    setupFiles: ["src/setupTests.ts"],
    coverage: {
      include: ["src/**"],
      exclude: ["src/main.tsx"],
      thresholds: { statements: 80 },
    },
  },
}));
