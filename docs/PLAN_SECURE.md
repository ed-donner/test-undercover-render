# Plan: security changes before UnderCover goes on AWS

This plan makes the four changes in `docs/SECURE.md`, one phase for each step, then runs the live checks and brings the docs up to date in a fifth phase. Each phase leaves `npm run check` green and is committed before the next one starts.

SIDENOTE: For consistency with the course, please read `labs/week3day2_lab1.ipynb` and build the check in step 2 in the same style as the lab, and read `labs/week3day2_lab2.ipynb`, which deploys the app, without running it. Where the lab and this document differ, follow this document. Include this sidenote in your plan too.

When it's done, everything the agent's side sends to the backend carries an API key, and every route says who may call it: the agent with its key, a signed-in handler, either one for the reads they share, or anyone for the health check. Before the claim agent's model sees a claim, a second model reads it for instructions hidden in what the customer wrote, and a claim it flags is referred to a handler with the check's reason. CLM-1901, the security team's claim with a hidden instruction, is in the queue. The backend serves a document of the claim agent's eight operations for the Gateway, refuses any payment over the approval limit before it looks at the claim, and pays a held payout as part of the handler's sign-off, without the agent's service. The claim agent's work on a claim ends when its payout is held, so the claim graph no longer pauses. One command builds the dashboard, the backend serves that build beside the API, and the same app runs on Lambda through Mangum, with a connection for each request through Supabase's transaction pooler.

Phases 1 to 4 are checked with tests, local commands and a SQLite backend. Phase 5 reseeds Supabase once and runs every live check, on the real model, in one go.

## Design

### Modules

The backend:

- `api_key.py` (new): checking the agent's API key. It reads `UNDERCOVER_API_KEY` on each request and compares it with the key a request sent with `secrets.compare_digest`, as bytes, so a header with characters outside ASCII is refused rather than raising. An unset or empty key matches nothing, not even an empty header. Nothing else reads the variable, as `auth.py` is the only module that reads `VITE_SUPABASE_URL`.
- `dependencies.py`: gains the gates. FastAPI's `APIKeyHeader("X-API-Key", auto_error=False)` reads the key. `AgentKey` lets through a request with the right key and refuses any other with a 401, "This needs the agent's API key". `HandlerOrAgent` lets through the right key or a signed-in handler, and refuses a request with neither with a 401, "Sign in, or send the agent's API key"; it reads the token with an `HTTPBearer(auto_error=False)` and checks it as `SignedIn` does, through one shared function. `SignedIn` and `senior(action)` stay as they are. A security scheme adds no parameter to an operation, and the agent's document leaves the schemes out, so the key is never a tool input on the Gateway.
- `agent_api.py` (new): the claim agent's own API document. It holds the eight operation ids and builds the document with FastAPI's `get_openapi` from the app's routes that have them, with no `servers`. It removes `components.securitySchemes` and every operation's `security`, which AWS lists as unsupported in a Gateway's OpenAPI target; the Gateway sends the key from its credential provider instead.
- `dashboard.py` (new): serves the dashboard's build from `dashboard/dist`, through a Starlette `StaticFiles` that falls back to `index.html` for any path outside `/api/` it has no file for. The folder is looked up on each request, so with no build every path outside the routes is a 404 in JSON, as today, and the tests can point it at a stand-in build.
- `main.py`: a gate on every route; `get_agent_api`; `pay_claim` checks the amount against the approval limit first; `sign_off_claim` pays; the dashboard's build mounted after every route; and `handler = Mangum(app, lifespan="off")` at the end, as the deployment expects.
- `runs.py`, `configuration.py`, `improvement.py`: a gate on every route. `configuration.py` gains `get_screening`, the model the check runs on, which sits outside the versions.
- `agent_service.py`: loses `resume_claim`, since the sign-off no longer needs the agent's service.
- `database.py`: seeding reads `data/security/` beside the queue's files. On Lambda (`AWS_LAMBDA_FUNCTION_NAME` set), `engine_for` opens Postgres with SQLAlchemy's `NullPool` and psycopg's `prepare_threshold=None`; elsewhere it is unchanged.
- `models.py`: `StepKind` gains `screening`, and a `ScreeningModel` shape for `get_screening`.

The agent:

- `connection.py`: `call` sends the key in an `X-API-Key` header with every request, reading `UNDERCOVER_API_KEY` as each request is sent, so the command line, which loads `.env` after it imports the agent's modules, and the tests, which swap the client, both send it. `api_key()` returns the key or raises "UNDERCOVER_API_KEY is missing. Add it to .env". The header's name is written here alone.
- `api.py`: gains `get_screening`, and `StepKind` gains `screening`.
- `screening.py` (new): the check, in the lab's words: `SCREEN_INSTRUCTIONS` and `Screening`, with `reason` before `instructions_found` and the lab's field descriptions, and `screen(llm, claim)`, which asks the model through `with_structured_output(Screening, method="function_calling", strict=True, include_raw=True)`, Structured Outputs in a strict tool call that LangChain reads after the call, and returns the reply and its answer, or none when the answer can't be read. It records nothing and calls no backend.
- `tools.py`: `ClaimState` gains `screening`, the check's result (its reason and `instructions_found`), kept with `keep_last` like the decision and empty until the check has run.
- `harness.py`: the claim graph gains its first two nodes, `screen` and `refer`, and loses the pause: a held approval ends the claim's work, so `wait_for_sign_off`, the resume branch in `carry_on` and `finish_held_copy` go (below). `claim_graphs(version, pool)` reads the check's model with `get_screening` once for the run's graphs.
- `service.py`: refuses to start without the key, before it opens the checkpoint pool, saying it's missing. It loses `resume_claim`, `resume` and the `resuming` set.
- `dispatcher.py`: loses `resuming`, since nothing picks a claim up after its sign-off any more.

Inside the agent, `harness` now uses `screening` beside `tools`, `api` and `openrouter`; `screening` imports nothing else from the agent, since the harness records the check's usage with `usage_of`. The agent still reaches the backend only through `api.py` and `improver_api.py` on the one client in `connection.py`.

The dashboard:

- `StepList.tsx`: a `screening` step shows as "Security check", with a shield icon and the check's line.
- `DecisionPanel.tsx`: loses "Signed off by ... Waiting for the agent to pay it", since a sign-off pays the claim at once. "Waiting for the agent to pay it." stays for an approval within the limit that isn't paid yet.
- `api.ts`: `StepKind` gains `screening`. It never sends the key.
- `vite.config.ts`: Vite reads `.env` from the repo root in development and production mode, so `npm run build` builds in the Supabase address and publishable key; the tests and the end-to-end dashboard still read none. The build splits the libraries into chunks of their own with Rolldown's `codeSplitting` groups, since today's single 551 kB chunk makes Vite warn. The warning's limit stays as it is.

The rest:

- `package.json`: `build` (`vite build dashboard`, writing `dashboard/dist`) and `check:server` (below), which `check` runs after `check:python`.
- `playwright.config.ts`, `e2e/servers.ts`, `e2e/api.ts`, `e2e/agent_stand_in.ts`: the test backend gets a fixed key, written once in `e2e/servers.ts`; `e2e/api.ts` sends it with every request it plays for the agent; the agent's stand-in loses the resume path and `/api/resumed`.

### Who may call what

| Gate | Operations |
| --- | --- |
| Anyone | `health` |
| The agent's key | `start_claim`, `record_step`, `record_model_call`, `record_work_time`, `record_decision`, `calculate_payout`, `pay_claim`, `fail_claim`, `get_version`, `get_current_version`, `get_screening`, `search_documents`, `read_section`, `create_dispatch`, `create_evaluation`, `create_round_evaluation`, `record_run_claims`, `finish_run`, `stop_runs`, `create_round`, `stop_rounds`, `get_round`, `get_improver_view`, `record_change_proposal`, `record_recipe_proposal`, `record_review`, `create_version`, `create_recipe`, `record_verdict`, `record_improver_call`, `finish_round` |
| The key or a signed-in handler | `list_claims`, `get_claim`, `get_policy`, `get_claim_history`, `get_agent_api` |
| A signed-in handler | `get_signed_in_handler`, `list_steps`, `get_configuration`, `get_version_details`, `get_settings`, `change_settings`, `get_latest_dispatch`, `start_dispatch`, `list_evaluations`, `get_evaluation`, `start_evaluation`, `sign_off_claim`, `get_improvement`, `get_recipe`, `start_round`, `stop_round`, `approve_proposal`, `reject_proposal` |

The table follows who calls each route today: the agent's operations are those in `agent/api.py` and `agent/improver_api.py`, and the dashboard's those in `dashboard/src/api.ts`. The four reads both use are the shared ones. `get_improver_view`, which holds the handlers' decisions on the evaluation set, now needs the key. The actions that need a handler who can sign off over the limit keep `senior(action)`. A test holds these four lists and checks that, together, they name every operation in the app exactly once, so a new route without a gate fails the checks.

### The API key

- `.env` gains `UNDERCOVER_API_KEY`, from `secrets.token_urlsafe(32)` (43 characters), appended without printing it.
- The key never stands in for a handler. The dashboard's actions keep their handler gates, so a request with only the key gets the handler's 401. The agent's service records a round or a review for a handler with the key, as today: the backend checks that the `handler_id` belongs to a handler, and only the service holds the key.
- With no key set, the backend starts, handlers use the dashboard through their sign-in, and every route that needs the key refuses.
- The backend's calls to the agent's service carry no key. The service stays on the laptop, where only the backend calls it.

### The check for hidden instructions

The claim graph, with its new nodes first:

```
START -> screen --(instructions found)--> refer -> END
            |
            +--(none found)--> agent <-> tools --(paid at once)--> pay -> END
                                             +--(held, declined or referred)--> END
```

- `screen` reads the claim with `api.get_claim` and gives the check the claim as the `get_claim` tool gives it to the claim agent, as JSON, which holds every field the customer wrote. The system message is the lab's `SCREEN_INSTRUCTIONS`. It records each model call with its cost through `record_model_call`, with the claim's run, so the check counts in the claim's model cost on the scoreboard and in a round's spending. Then it records the check's result as a `screening` step, such as "No instructions found. The claim describes a stolen watch ..." or "Instructions found. The story tells the AI claims assistant to approve the claim in full ...", which is always the first step on the claim's thread, and returns the result into `ClaimState`'s `screening`.
- An answer that can't be read raises `UnreadableScreening` after its call is recorded. The node's `RetryPolicy(max_attempts=3, retry_on=UnreadableScreening)` tries the check again, three attempts in all, and nothing else: the default `retry_on` would also retry timeouts, rate limits and `Refused`, so the policy names its one error, as the dispatcher's `RETRY` names `TRANSIENT`. After the third attempt, the error goes on like any other error in the claim graph: the attempt fails with `fail_claim`, and the dispatcher works the claim once more from the start. A rate limit or a timeout from the check's model leaves the claim in progress, as one from the claim agent's model does, and any other error fails the attempt, each after one call. In every case the claim agent's model never runs.
- `after_screen` reads `screening` from the state. When the check found an instruction, `refer` records a referral with a payout of zero, the reason in `screening`, and the section "Security check: no section of the wording or the manual applies", and the graph ends. The claim agent's model never sees the claim. A repeat after a restart is a repeat of the same decision, which the backend accepts.
- When it found none, the graph goes to the claim agent as today.
- The check runs once per thread, as its first step. `carry_on` from saved progress starts after it, with the result in the saved state. A claim stopped during the check runs the check again, since the node's step was never saved. A new attempt, or a claim with nothing saved that starts again from its first message, is checked again.
- The check's model comes from the backend: `get_screening` returns `openai/gpt-6-luna` at `none`, or, with `MODEL_NAME` set, that model at `default`, through `model_or_free` in `backend/free_models.py`, which is still the one place that reads `MODEL_NAME`. The agent builds it with `chat_model` like the version's model. It isn't part of a version, so no proposal, version or setting can change it, and the improver has no way to it.
- The check's call is part of the claim graph's run, so Langfuse traces it inside the claim's trace.
- Seeding adds CLM-1901, POL-2901 and Derek Vance (CUS-3901) from `data/security/` to what it reads from `data/claims.json`, `data/policies.json` and `data/customers.json`, which stay as they are. It never reads `data/security/decisions.json`, so CLM-1901 is in neither evaluation set. The queue has 26 claims, 51 policies and 50 customers.

### The agent's own API

- `get_agent_api` (`GET /api/agent/openapi.json`) returns the OpenAPI document of exactly `get_claim`, `get_policy`, `get_claim_history`, `search_documents`, `read_section`, `calculate_payout`, `record_decision` and `pay_claim`, built from the app's own routes, with their operation ids and one-line docstrings, no `servers`, no `components.securitySchemes` and no `security` on any operation. The payment's body keeps `amount`, which the Gateway's Policy reads as `context.input.amount`. It needs the key or a signed-in handler.
- `pay_claim` first refuses any amount over the approval limit in force with a 403, "A payout over $1,000.00 needs a handler's sign-off", before it reads the claim, so an over-limit payment gets the same answer on any claim, CLM-9999 included. The rest of its checks follow as today. The message is written once and named in the limit it uses.

### The sign-off that pays

- `sign_off_claim` records the handler and the time on the decision and the payment of the approved payout in one transaction, and the claim is decided. It no longer calls the agent's service, so it works on Lambda, where the service can't be reached.
- The claim agent's work on a claim ends when its payout is held: `after_tools` ends the graph for an approval the backend holds for sign-off, as it does for a decline or a referral, and `pay` is reached only by an approval the backend can pay at once. Its thread finishes with nothing left to run, so carrying it on, after a restart or a sign-off, runs nothing and never calls `pay_claim`, which would refuse the amount.
- So the graph loses `wait_for_sign_off` and its `interrupt()`, `carry_on` loses its resume branch (`Command(resume=True)`), and `work_in_run` loses `finish_held_copy`, which only cleared the paused threads of evaluations' copies held for sign-off. An evaluation's held copy now ends like any other decided claim, and the backend still counts it as finished.
- The agent's service loses `resume_claim`, and the dispatcher no longer leaves out claims being resumed.

### Ready for Lambda

- `npm run build` runs `vite build dashboard` and writes `dashboard/dist`, with `VITE_SUPABASE_URL` and `VITE_SUPABASE_PUBLISHABLE_KEY` from `.env` when there is one and otherwise from the environment, as Vite reads `VITE_` variables. It prints no warnings. Only `VITE_` variables reach the build, so the API key never does.
- When `dashboard/dist` exists, the backend serves it: its files at their own paths, `index.html` for any other path outside `/api/`, every `/api/` route as before and a 404 in JSON for an unknown one. The mount comes after every route, so `/docs` and `/openapi.json` still work. Without the folder the backend answers as today, and `npm run dev` is unchanged.
- `handler = Mangum(app, lifespan="off")` at the end of `backend/main.py`, so nothing seeds on Lambda. Nothing else happens in the startup hook, and the tests already call the app without it.
- The `server` group in `pyproject.toml` lists what the backend needs on a server: fastapi, httpx, mangum, openrouter, `psycopg[binary]`, `pyjwt[crypto]`, sqlalchemy and uvicorn today. `npm run check:server` runs `uv run --isolated --only-group server python -c "import backend.main, psycopg, uvicorn"` in a temporary environment that leaves `.venv` alone. psycopg and uvicorn are named because SQLAlchemy loads the driver only on connecting and nothing imports the web server.
- At run time the backend imports nothing from outside `backend/` and the server group, reads files only from `backend/`, `data/` and `dashboard/dist/`, and writes none. With `DATABASE_URL` set it never opens SQLite.
- The backend reads `DATABASE_URL`, `VITE_SUPABASE_URL` and `UNDERCOVER_API_KEY` on Lambda. `UNDERCOVER_DB`, `UNDERCOVER_AGENT`, `JUDGE_URL` and `MODEL_NAME` have defaults or are optional, and `OPENROUTER_API_KEY` is read only by the judge, in `finish_run`, which only the agent's service calls.
- On Lambda, a connection is opened for each request and closed at its end (`NullPool`), with prepared statements off (`prepare_threshold=None`), for the transaction pooler on port 6543. The schema still comes from `search_path` in the URL's `options`, which an earlier test showed the transaction pooler keeps; phase 5's live check confirms it.
- `docs/TECH_STACK.md` gains a Deployment section: `npm run build` and `dashboard/dist`; the package (`backend/` and `data/` without tests or `__pycache__`, `dashboard/dist/`, and the server group's packages for Linux and Python 3.12); the Lambda handler `backend.main.handler`; `backend.main:app` for a web server; and the environment (`DATABASE_URL` on port 6543, `VITE_SUPABASE_URL`, `UNDERCOVER_API_KEY`).

### The tests

- The root `conftest.py` sets `UNDERCOVER_API_KEY` to a test key for every test, so the backend's and the agent's tests share it. The `client` fixture sends it, as the agent's side does, and a new `dashboard` fixture is a client with no key, as a handler's browser is. Tests that read what only the dashboard reads sign in as Dana with `signed_in()`, in the backend's tests and in the agent's records helpers.
- `backend/tests/test_api_key.py` (new) holds the lists of the agent's operations and the shared reads, and `test_sign_in.py`'s list of operations that need a handler grows to the whole of that gate.
- The agent's stub graph gets a stub of its own for the check, which passes every claim unless a test flags one, so the claim agent's scripts don't change. Tests that count a claim's steps or model calls gain the check's.
- Tests and counts that expect 25 claims in the queue expect 26.
- The tests of the pause go with it: the graph's nodes and edges in `test_claim_agent.py` lose `wait_for_sign_off` and gain `screen` and `refer`, the pause test becomes a test that a held approval ends the graph, and `test_restart.py`'s claim stopped on its way into the pause gives way to the phase 3 test below. Tests of `finish_held_copy` become tests that an evaluation's held copy ends with nothing left to run.
- The end-to-end tests: the test backend gets a fixed key, which `e2e/api.ts` sends; `finishOpenRound` reads `/api/improvement` as Dana, with a token from the Auth stand-in's password sign-in; the sign-off test checks the claim is paid without the test paying it.

### Following the labs

- Lab 1's check is `SCREEN_INSTRUCTIONS`, the `Screening` model with `reason` before `instructions_found`, a GPT-6 Luna `ChatOpenAI` at `none` and `with_structured_output(Screening)`, run in a `before_agent` hook that ends the run when it finds an instruction. The claim agent is a hand-written `StateGraph` whose nodes do what middleware would, so the hook becomes the graph's first node with a conditional edge to `refer`. The instructions and the fields are the lab's, word for word. Where the brief differs, it wins: the check reads the claim as the claim agent does rather than the lab's policy and claim, a flagged claim is referred with the check's reason rather than left without a decision, and the check's calls are recorded.
- Lab 2, read without running it, expects of this build: `npm run build` writing `dashboard/dist` with the Supabase lines from `.env`; the server group exported with `uv export --only-group server` and installed for Linux; `backend/`, `data/` and `dashboard/dist/` in the package, without tests and `__pycache__`; `backend.main.handler`; a function whose environment is `DATABASE_URL` on port 6543, `VITE_SUPABASE_URL` and `UNDERCOVER_API_KEY`; `GET /api/claims/CLM-1901` refused without the key and answered with it; `/api/agent/openapi.json` read with the key, to which it adds `servers`; the eight operations as tools named `undercover-app___<operation_id>` with the key sent in `X-API-Key`; a payment of $4,800 on CLM-1901 refused by the app's own limit, and one of $400 refused because CLM-1901 was never approved; and a sign-off on the deployed dashboard that pays. The tests in phases 3 and 4 check each of these on the app.

### Checked against the code standards

- One way to call each service (rule 7): the key's header is written once on each side, in `agent/connection.py` and `backend/dependencies.py`, and once in `e2e/servers.ts` for the tests. The agent still reaches the backend only through `api.py` and `improver_api.py`, and the backend no longer calls the agent's service after a sign-off.
- One job a module (rule 8): `api_key.py` checks the key, `dependencies.py` turns it and the sign-in into gates, `agent_api.py` builds the agent's document, `dashboard.py` serves the build, and `screening.py` asks the check's model. `screening.py` records nothing; the harness records the check's calls and steps.
- Literals once (rule 9): the variable `UNDERCOVER_API_KEY` is read in `backend/api_key.py` and `agent/connection.py`, the refusals and the security check's section are named once, and the payment's limit message is shared by its two refusals.
- The framework's own way (rule 10): FastAPI's `APIKeyHeader`, `HTTPBearer` and dependencies for the gates, `get_openapi` for the document, Starlette's `StaticFiles` for the build, Mangum for Lambda, SQLAlchemy's `NullPool` and psycopg's `prepare_threshold` for the database, and a LangGraph node with a conditional edge on `ClaimState` and a `RetryPolicy` that names its one error, with LangChain's `with_structured_output`, for the check. Ending the graph on a held payout drops the claim agent's one use of `interrupt()`.
- One job a function (rule 11): `screen` checks and records the result, `refer` records the referral, and `sign_off_claim` records the sign-off and the payment with one helper shared with `pay_claim`.
- The agent (rule 13): the check is part of the claim graph in the harness, its model comes from the backend, and the rule on payments over the limit is enforced by the backend whatever the agent does.
- Instructions as goals (rule 14): the check's instructions say what to look for and what is normal. Code, not a model, refers the claim.
- Bringing code up to standard first (rule 12): `pay_claim` and `sign_off_claim` get their shared payment helper before the new behavior.

### How the criteria are checked

Phases 1 to 4 use pytest, vitest and Playwright, which never read `.env` and use SQLite and stand-ins, plus commands on a SQLite backend seeded into the scratchpad with a throwaway key. Phase 5 reseeds Supabase once with `npm run seed`, runs `npm run dev` on the default model, and checks pages in the browser through the Playwright MCP server, signed in as Dana Whitfield or Marcus Oyelaran with `HANDLER_PASSWORD`. A token for curl comes from Supabase Auth's password sign-in. No command prints the API key.

## Phase 1: An API key for the agent

Add the key to `.env`, `backend/api_key.py` and the gates in `dependencies.py`, and put a gate on every route. Send the key from `agent/connection.py`, and make the agent's service refuse to start without it. Update the tests' fixtures and the end-to-end tests to send the key and sign in where the dashboard does.

- [x] `grep -c '^UNDERCOVER_API_KEY=' .env` prints `1`, and `uv run --env-file .env python -c "import os; print(len(os.environ['UNDERCOVER_API_KEY']))"` prints `43`; the key was added without printing it
- [x] pytest: `record_decision` on a claim in progress with no key and with a wrong key returns 401 and records nothing; with the right key it returns 200
- [x] pytest: every operation the agent's key gates returns 401 with no key, including with Dana's token and no key
- [x] pytest: each shared read returns 200 with the key, 200 with Dana's sign-in and no key, and 401 with neither or with only a wrong key
- [x] pytest: with only the key, `sign_off_claim`, `start_dispatch`, `start_evaluation`, `start_round`, `stop_round`, `approve_proposal`, `reject_proposal` and `change_settings` each return 401, change nothing and send nothing to the agent's service
- [x] pytest: the lists of operations for anyone, the agent's key, the key or a handler, and a handler name every operation in the app exactly once
- [x] pytest: with `UNDERCOVER_API_KEY` unset, `health` returns 200, Dana reads the claims, and every operation the key gates returns 401, even with an empty `X-API-Key` header
- [x] pytest: with the key, the agent's service records a round and a review for Dana as before
- [x] pytest (agent): the key is read as each request is sent: with the key changed after the agent's modules are imported, the next request through `connection.call` carries the new key
- [x] pytest (agent): the agent's service, started with its lifespan and no key, fails to start with "UNDERCOVER_API_KEY is missing. Add it to .env" before opening the checkpoint pool
- [x] `grep -rn "UNDERCOVER_API_KEY" backend agent --include='*.py'` finds it only in `backend/api_key.py`, `agent/connection.py` and tests; `grep -rn "compare_digest" backend` finds it in `backend/api_key.py`; `grep -rn "X-API-Key\|UNDERCOVER_API_KEY" dashboard/src` finds nothing
- [x] The shared OpenAPI rules test passes, and no operation in `/openapi.json` has a header parameter
- [x] e2e: every spec passes with the test backend's key, and `finishOpenRound` reads the round as Dana
- [x] On a scratchpad SQLite database seeded with `uv run -m backend.seed` and a backend started with a throwaway key: `curl` to `POST /api/claims/CLM-1001/start` with no key prints 401, `GET /api/claims` with neither key nor token prints 401 and with the key 200, and `/api/health` prints 200
- [x] `npm run check` passes with `.env` moved out of the way

## Phase 2: A check for instructions hidden in a claim

Seed CLM-1901 from `data/security/`. Add `get_screening`, `agent/screening.py`, the `screen` and `refer` nodes with the check's `RetryPolicy`, and the `screening` step on the dashboard.

- [x] `uv run -m backend.seed` prints `Seeded 26 claims, 51 policies, 50 customers and 3 handlers into undercover.db, with 25 held-out claims and 50 handlers' decisions for evaluations, ...`, and `git status data` shows no change
- [x] pytest: CLM-1901 is waiting in the queue with POL-2901 and Derek Vance, `handler_decisions` has no row for it, and an evaluation of each set, whole and tiny, makes no copy of it
- [x] pytest: `get_screening` with the key returns `openai/gpt-6-luna` at `none`, with `MODEL_NAME` set returns that model at `default`, and without the key returns 401; a kept version on another model leaves it as it was
- [x] pytest: `Screening`'s fields are `reason` then `instructions_found` with the lab's descriptions, and the check's system message is the lab's instructions word for word
- [x] Stub test, a flagged claim: the claim is decided as a referral with a payout of zero, the check's reason and the security check's section; the claim agent's stub model is never called; the first step is the `screening` step; the check's call is recorded as one of the claim's model calls, in its run, with its cost
- [x] Stub test, a passed claim: the check is sent the claim as the `get_claim` tool gives it, the first step is the `screening` step, and the claim agent then decides and pays the claim as before
- [x] Stub test: two unreadable answers then a readable one record three model calls and the claim goes on; three unreadable answers fail the attempt, back in the queue, with three model calls recorded and no call to the claim agent's model
- [x] Stub test: a timeout from the check's model makes one model call and leaves the claim in progress, and any other error makes one model call and fails the attempt; neither calls the claim agent's model
- [x] Stub test: the check's result is in the claim graph's saved state as `screening`, with its reason and `instructions_found`, and `refer` takes the referral's reason from it
- [x] Stub test: a claim stopped after the check and carried on doesn't run it again; a claim with nothing saved that starts again from its first message, and a second attempt, are each checked again
- [x] `grep -rn MODEL_NAME backend agent --include='*.py'` finds it only in `backend/free_models.py` and tests, and the boundaries test allows `harness` to use `screening`, and `screening` to use nothing else in the agent
- [x] vitest: a `screening` step shows as "Security check" with its line, first in the claim's steps
- [x] e2e: the queue lists 26 claims; a `screening` step recorded through the API on a claim shows as its first step
- [x] `npm run check` passes with `.env` moved out of the way

## Phase 3: The agent's own API

Add `backend/agent_api.py` and `get_agent_api`. Put the limit first in `pay_claim`. Make the sign-off pay, end the claim's work when its payout is held, and remove the pause, the resume branch, `finish_held_copy` and `resume_claim` from the backend, the agent's service, the dispatcher and the end-to-end stand-in. Update the decision panel.

- [x] pytest: `/api/agent/openapi.json` with the key holds exactly the eight operations, each with its operation id and its one-line docstring as its description, has no `servers`, no `components.securitySchemes`, no `security` on any operation and no header parameter, keeps `amount` in `pay_claim`'s body, and passes the API rules
- [x] pytest: the document returns 200 with Dana's sign-in and 401 with neither the key nor a sign-in
- [x] pytest: `pay_claim` of $4,800 on CLM-1901, which was never approved, and on CLM-9999 each return 403 with "A payout over $1,000.00 needs a handler's sign-off" and record nothing; $400 on CLM-1901 returns 409, as never approved; with the approval limit changed to $2,000 a $1,500 payment passes the limit check and the message names $2,000.00
- [x] pytest: Dana's sign-off on a payout of $1,350.00 held for sign-off decides the claim and records one payment of $1,350.00 signed off by Dana Whitfield, with no call to the agent's service; a `pay_claim` of $1,350.00 afterwards returns 403, and a second sign-off returns 409
- [x] Stub test: a claim agent approves $1,350.00, `work_claim` reports `CLM-1002  approve  $1,350.00, waiting for sign-off`, and the graph ends with nothing left to run on the thread and no call to `pay_claim`; after Dana's sign-off, `carry_on` on the same thread runs nothing, makes no call to `pay_claim`, and the claim keeps its one payment
- [x] Stub test: an evaluation's copy approved over the limit ends with nothing left to run on its thread and counts as finished, as before
- [x] Stub test: an approval of $420.00 is still paid once by the graph
- [x] `grep -rn "resume_claim\|resuming\|/resumed" agent backend e2e dashboard/src` finds nothing, and `grep -n "interrupt\|wait_for_sign_off\|finish_held_copy\|PAUSE" agent/harness.py` finds nothing
- [x] vitest: after a sign-off the decision panel shows "Paid $1,350.00, signed off by Dana Whitfield at" a time, and never "Waiting for the agent to pay it"
- [x] e2e: Dana signs off CLM-1020 held at $1,350.00 on its page, which shows it paid without the test paying it, and the agent's stand-in receives no call
- [x] `npm run check` passes with `.env` moved out of the way

## Phase 4: Ready for Lambda

Add `npm run build` and the chunk split, `backend/dashboard.py` and its mount, the Lambda handler, the connection per request on Lambda, `check:server` in `npm run check`, and the Deployment section in `docs/TECH_STACK.md`. Build the deployment package in the scratchpad and report its size.

- [x] `npm run build` writes `dashboard/dist` and prints no warning
- [x] The build holds the Supabase address from `.env`, and with `.env` moved away and the two `VITE_` variables in the environment it holds theirs; `grep -rlF` with the API key finds nothing in `dashboard/dist`, checked without printing the key
- [x] pytest, with a stand-in build: `/` and `/claims/CLM-1001` return its `index.html`, `/assets/app.js` returns the file, `/api/health` returns `{"status": "ok"}` and `/api/nothing` returns a 404 in JSON; with no build, `/` returns a 404 in JSON
- [x] pytest: the Lambda handler, called with a Function URL event, answers `/api/health` with 200, `GET /api/claims` with the key with 26 claims, and `/` and a dashboard page with the stand-in build's `index.html`, all without the startup hook
- [x] pytest: with `AWS_LAMBDA_FUNCTION_NAME` set and a Postgres `DATABASE_URL`, with psycopg's connect replaced by a recorder, two requests open two connections, each with `prepare_threshold=None`; without it, the engine keeps its pool of 4
- [x] `npm run check:server` passes, and the list of packages in `.venv` is the same before and after it
- [x] `grep -rnE "^\s*(from agent(\.| )|import agent($|\.|,| ))" backend` finds nothing (the plan's first pattern, `"from agent\|import agent"`, also matched the backend's own `agent_service` and `agent_api`)
- [x] The deployment package, built in the scratchpad with the lab's `uv export --only-group server` and `uv pip install --target ... --python-platform x86_64-manylinux2014 --python-version 3.12 --only-binary :all:`, plus `backend/` and `data/` without tests or `__pycache__` and `dashboard/dist/`, is under 50 MB zipped; the report gives its size: 20.2 MB zipped, 72.4 MB unzipped
- [x] `docs/TECH_STACK.md` has the Deployment section described in the design
- [x] `npm run dev` starts the backend, the agent's service and the dashboard as before
- [x] `npm run check` passes, with the server check, with `.env` moved out of the way

## Phase 5: The live checks and the docs

Reseed once, then run every live check in this order, on the default model. Then update the docs, review the whole branch against `week3day2-start` with a fresh subagent and fix what it finds.

- [x] `npm run seed` prints 26 claims, 51 policies and 50 customers into the `undercover` schema on Postgres
- [x] Step 1: with `npm run dev` running, signed in as Dana Whitfield, the queue, a claim, the Scoreboard, the Improvement, Configuration and Settings pages load with no errors in `browser_console_messages`; `curl` to `POST /api/claims/CLM-1001/start` without the key prints 401
- [x] Step 1: `uv run -m agent CLM-1001` prints `CLM-1001  approve  $420.00`, and its steps start with the security check, passed
- [x] Steps 1 and 2: a dispatch at N=25 on the queue page works the other 25 claims; CLM-1901 is referred with a payout of zero, the check's reason and the security check's section, which its page shows (screenshot), and its model calls are the check's alone; no other claim is flagged, and the decisions are reported beside the last live run's
- [x] Step 2: an evaluation of the evaluation set's five tiny claims on the Scoreboard flags none of them
- [x] Step 3: Dana signs off a held payout from the dispatch on its page, which shows it paid at once, and the Supabase MCP server's `select count(*) from undercover.payments where claim_id = '...'` returns 1; `curl` with the key to `/api/agent/openapi.json` lists the eight operations
- [x] Step 4: with `npm run dev` stopped, the backend started with only `DATABASE_URL`, `VITE_SUPABASE_URL`, `UNDERCOVER_API_KEY` and `AWS_LAMBDA_FUNCTION_NAME` in its environment, read from `.env` without printing them, with `:5432/` swapped for `:6543/` in `DATABASE_URL` as the lab does, serves `GET /api/claims` to Dana's token from Supabase Auth, so the transaction pooler keeps the `undercover` schema; the Supabase MCP server shows no connection left open by it afterwards
- [x] Step 4: after `npm run build`, `uv run --env-file .env uvicorn backend.main:app` serves the dashboard at `http://127.0.0.1:8000`, where Dana Whitfield signs in and sees the claims, and a reload on a claim's page loads it, with no console errors
- [x] Report what the live checks spent, from the backend's records and the OpenRouter key's usage; on GPT-6 Luna it comes to under $0.25: the backend recorded $0.0383 and the key's usage rose by $0.0383
- [x] `docs/SPEC.md`: the agent identifies itself with a key on every request, the check for hidden instructions and the referral it makes, the agent's work ending when a payout is held, and the sign-off that pays
- [x] `docs/TECH_STACK.md`: the key and its header, the gates, the check and its model from `get_screening`, the agent's document, the claim graph without its pause, the sign-off that pays, `UNDERCOVER_API_KEY` in `.env`, and the Deployment section
- [x] `docs/CODE_STANDARDS.md`: rule 10 no longer names `interrupt()` for the claim agent
- [x] `docs/PROCESS.md`: `npm run build`, the server check in `npm run check`, and these live checks in place of the improver's
- [x] `data/README.md`: seeding puts CLM-1901, its policy and its customer in the queue, and leaves its handler's decision out of both evaluation sets
- [x] `docs/STATUS.md` describes what's built, the live checks and what they cost, and the known gaps, without the gap the key closes
- [x] A fresh subagent reviews the whole branch against `week3day2-start`, not `main`, with `docs/CODE_STANDARDS.md`; everything it would block the merge for is fixed, or explained in the report where I disagree
- [x] `npm run check` passes, both with `.env` in place and with it moved out of the way

## Not in this plan

- Deploying to AWS, the AgentCore Gateway and its Policy, and moving the claim agent onto the Gateway's tools: the labs and Day 3 do these.
- A key on the backend's calls to the agent's service, which stays on the laptop.
- Hiding `/docs` and `/openapi.json` on the public address. They describe the routes and grant nothing, and `docs/STATUS.md` lists them as a known gap.
- A second key for each caller, rotating the key, and limiting how often a caller can try one.
- A check on what comes out of the model, the lab's assignment.
- Rejecting a held payout, real payments, messages to customers and sign-up, as `docs/SPEC.md` says.
