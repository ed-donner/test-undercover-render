# Process

`uv sync` and `npm install` at the repo root install everything, including a git pre-commit hook. `npm run dev` starts the backend, the agent's AgentCore app on port 8080 (`agent.entrypoint:app` with uvicorn, reloading as `agent/` changes), the context layer and the dashboard, passing `.env` to the backend and the agent. Stop Lab 1's `agentcore dev` first, which serves on port 8080 too. `npm run build` builds the dashboard into `dashboard/dist`, which the backend then serves beside the API. `npm run seed` rebuilds the database `npm run dev` uses, on Supabase when `DATABASE_URL` is in `.env`. The agent always needs `DATABASE_URL`, where it saves its progress.

`npm run check` runs every check but the end-to-end tests at once with `concurrently`, each one's output shown in one piece, in this order, then the end-to-end tests on their own, since their timeouts need a machine that isn't busy:

- Python: ruff (lint and format), pyright, and pytest with 80% coverage, across the machine's cores with pytest-xdist
- The server check: the backend imports with only the `server` dependency group installed, in a temporary environment, from uv's cache, that leaves `.venv` alone
- The context check: the context layer imports with only the `context` dependency group installed, in the same way
- The runtime check: `runtime.main`, the file AgentCore Runtime starts, imports with only the `runtime` dependency group installed, in the same way
- TypeScript: ESLint, Prettier, tsc, and vitest with 80% coverage
- Playwright end-to-end tests

The checks need no network and never read `.env`: the tests use SQLite, a stub model, the real context layer on a local port, and stand-ins for the AgentCore Gateway, AgentCore Memory, AgentCore Identity, AgentCore Runtime, Langfuse, the agent, Supabase Auth and the judge. The end-to-end tests sign in through the Auth stand-in with a test password. Tables and connections on Supabase can be checked through the Supabase MCP server, which is read-only.

The pre-commit hook runs the format, lint, type and unit test checks on every commit.

## Planning

When asked to plan, as in "Please plan the pilot", write the plan to `docs/PLAN.md` and write no code.

- Start with the design: the modules, what each one is for, and how they depend on each other. Check it against `docs/CODE_STANDARDS.md` before you write the phases. Describe the agent's instructions by their goals, never as a list of steps.
- Split the work into phases, usually 5 or 6, each building on the last.
- Give each phase detailed success criteria that you can verify yourself: tests that pass, commands and their output, API calls and their responses, and pages you check in the browser with the Playwright MCP server. Write each one as a checkbox.
- Then stop and wait until you are asked to implement the plan.

## Implementing

When asked to implement the plan, as in "Please implement the plan for the pilot", build every phase in order without stopping. For each phase:

1. Build it, with tests. While you work, run only the tests for the code you're changing, without coverage, for example `uv run pytest agent/tests/test_entrypoint.py --no-cov`.
2. Check every success criterion and fix whatever fails. Then run `npm run check` and fix whatever fails.
3. Review the phase's changes, as described below, and fix what the review finds. After the fixes, run only the tests they touch, plus `npm run e2e` if they change the dashboard or the API.
4. Tick off its criteria in `docs/PLAN.md` and update `docs/STATUS.md`.
5. Commit without running `npm run check` again. The pre-commit hook reruns the checks; if it fails, fix the problem and commit again.

When the last phase is done, review the whole branch against `main` in the same way. Fix what the review finds, run the tests the fixes touch, plus `npm run e2e` if they change the dashboard or the API, and commit. Then report the results, including what the reviews found and what you changed.

## Reviewing

The checks show that the code works, but not that it is fit to merge. Every code change gets a review before it is committed.

- The reviewer is a fresh subagent that didn't write the code. Give it `docs/CODE_STANDARDS.md` and the diff, and ask it to review as a strict senior engineer deciding whether to merge the PR.
- It checks every standard, in particular: one way to call each service, with each URL written once; modules that keep to their own job and don't borrow each other's helpers; the framework's own way of doing things over hand-rolled code; functions that do one job; and agent instructions written as goals.
- Fix everything it would block the PR for before you commit. If you disagree with a finding, say so in your report instead of skipping it quietly.

## Rules

- Add tests with each change. Tests never call a model; use a stub model.
- Every page needs a signed-in handler. For browser checks with the Playwright MCP server, sign in on `/sign-in` with a handler's email from `data/handlers.json` and `HANDLER_PASSWORD` from `.env`: Dana Whitfield to act, Marcus Oyelaran to see what a handler who can't sign off over the limit sees.
- Before the live runs with the real model, reseed once with `npm run seed`. Evaluations work their own copies and need no reseed. Keep to the runs the plan asks for: for the context layer, memory and the Gateway, on the direct route with memory off, `uv run -m agent CLM-1001`, then `CLM-1005` and `CLM-1006`, a dispatch at N=25 on the queue page and an evaluation of the evaluation set's five tiny claims, then CLM-1005's and CLM-1006's pages in light and dark mode, and report what they spent from the backend's records and the OpenRouter key's usage.
- Outside a plan, commit each change once you have checked and reviewed it.
- Outside a plan, run `npm run check` before you hand work over.
- Never use `git commit --no-verify`.
- Never lower a threshold, turn off a rule or exclude a file to get a green run. If a rule looks wrong, stop and ask.
- Keep `docs/STATUS.md` up to date.
- Never push.
- Don't open `data/evals/` unless you're asked to.
- Everything must work on Windows: write `package.json` scripts as `uv run` commands or `.mjs` files.
