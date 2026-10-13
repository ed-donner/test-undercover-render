# Security changes before UnderCover goes on AWS

From our IT team, with information security.

SIDENOTE: For consistency with the course, please read `labs/week3day2_lab1.ipynb` and build the check in step 2 in the same style as the lab, and read `labs/week3day2_lab2.ipynb`, which deploys the app, without running it. Where the lab and this document differ, follow this document. Include this sidenote in your plan too.

## Where we're heading

UnderCover is moving onto our AWS account. The app goes first: the backend and the dashboard on AWS Lambda, at a public address our handlers can reach from anywhere, with the database still on Supabase. An AgentCore Gateway then goes in front of the routes the claim agent uses, with a Policy that refuses any payment over $1,000, and after that the claim agent moves onto the Gateway's tools.

Information security needs four changes before the app has a public address, and this document takes them one step at a time. Each step says what has to be true when it's finished and how we'll check it. The requirements describe what the app does rather than how its code is organized, and the notes at the end say where things are in our last build.

## What information security found

- The claim agent sends nothing to identify itself, so anyone who can reach the backend can record a decision or pay a claim, and every read is open. The agent's service records improvement rounds and reviews in a handler's name, and anyone who can reach the backend could do the same.
- The agent reads text that customers write. Our security team wrote a claim with an instruction to the AI hidden in its story, CLM-1901 in `data/security/`. Their experiment in `labs/week3day2_lab1.ipynb` found that GPT-6 Luna declines it, but a smaller model approves it in full, and a list of keywords misses the same instruction once it's reworded. A second model reading each claim first caught both versions and flagged none of the 25 claims in the queue.
- The app only runs on a laptop, with the dashboard on a development server and a backend that seeds its own database when it starts.

## Step 1: An API key for the agent

1. The key is in `.env` as `UNDERCOVER_API_KEY`, a random value of at least 32 characters, such as one from Python's `secrets.token_urlsafe(32)`. If it isn't there yet, add it without printing it.
2. Every request from the agent's side to the backend carries the key in an `X-API-Key` header. That covers the claim agent's tools and everything else in the agent that calls the backend, such as the dispatcher, the improver and the agent's service, including a process that loads `.env` after it starts.
3. Every backend route that only the agent's side calls refuses a request without the right key with a 401. That includes recording decisions, payments, steps, model calls and work times, and everything the agent's service records about runs and rounds, including a round it starts and a review it records for a handler. The key is compared in constant time, with Python's `secrets.compare_digest`.
4. The reads that both the dashboard and the agent use accept either the key or a signed-in handler, and refuse a request with neither with a 401. Every other route the dashboard calls needs a signed-in handler.
5. The key never stands in for a handler. The dashboard's actions (signing off a payout, starting a dispatch, an evaluation or a round, reviewing a proposal and changing a setting) still need a signed-in handler and refuse a request with only the key. The agent's service then records a round or a review for that handler with the key, as it does today.
6. `GET /api/health` stays open, for the deployment's health checks.
7. When `UNDERCOVER_API_KEY` isn't set, the backend still starts and handlers can still use the dashboard, but every request that needs the key is refused. The agent's service refuses to start without the key and says it's missing.

Done when:

- Tests cover an agent route with no key, a wrong key and the right key; a shared read with the key, with a handler's sign-in and with neither; a handler action with only the key; and the backend with no key set.
- With `npm run dev` running, the dashboard works as before for a signed-in handler, the agent's command line works CLM-1001 and a dispatch then works the rest of the queue as before, and a `curl` to an agent route without the key gets a 401.

## Step 2: A check for instructions hidden in a claim

1. Before the claim agent's first model call on a claim, a second model reads every field of the claim the customer wrote, as the claim agent would read the claim, and says whether it tries to instruct whoever handles the claim. Use the instructions and the two fields from the security team's experiment, the reason first and then `instructions_found`, with Structured Outputs.
2. The check runs on GPT-6 Luna (`openai/gpt-6-luna`) at reasoning effort `none`. When the platform runs on the one model in `MODEL_NAME`, the check uses that model with no reasoning effort set, and `MODEL_NAME` is still read in one place.
3. When the check finds an instruction, the claim agent's model never sees the claim. The agent records a referral with a payout of zero and the check's reason, so the claim goes to a handler. No section of the wording or the manual applies, so the decision's section says it came from the security check.
4. When the check finds nothing, the claim agent works the claim as before.
5. The check runs once for each claim, at the start of its work. Work that carries on from saved progress, after a restart or a sign-off, doesn't run it again, and a claim that starts again from its first message is checked again.
6. Each of the check's model calls, retries included, is recorded with its cost as one of the claim's model calls, so it counts in the claim's cost on the scoreboard. The claim's work on the dashboard shows the check's result as its first step.
7. A check whose answer can't be read is tried again, up to three attempts in all. If it still fails, or fails with an error or a timeout, the claim doesn't go on to the claim agent's model, and it fails as any other error in a claim's work does.
8. The check sits outside the claim agent's versioned configuration, so the improver can't change it or turn it off.
9. CLM-1901 is seeded into the queue with its policy and its customer from `data/security/`, which seeding reads beside `data/claims.json`, and `data/claims.json` stays as it is. Its handler's decision isn't seeded, so it stays out of both evaluation sets and no score changes.

Done when:

- Tests on a stub model cover a claim the check flags (referred with the reason, and no call to the claim agent's model), a claim it passes, a check that fails, and CLM-1901 in the queue and in neither evaluation set.
- After one `npm run seed`, with `npm run dev` running on the default model, a dispatch refers CLM-1901 with the check's reason, which the dashboard shows on the claim, and decides the other claims as before. An evaluation of the evaluation set's tiny five flags none of them.

## Step 3: The agent's own API

The Gateway makes a tool of every operation in the API document it's given, and the claim agent will get its tools from it. A document with only the agent's operations keeps the dashboard's routes, the evaluations and the sign-off out of the agent's reach.

1. `GET /api/agent/openapi.json` returns an OpenAPI document with exactly the claim agent's eight operations: `get_claim`, `get_policy`, `get_claim_history`, `search_documents`, `read_section`, `calculate_payout`, `record_decision` and `pay_claim`. It's generated from the app's own routes and has no `servers` entry, since the deployment adds the app's address. Checking the key adds no inputs to the operations, so the document has no key parameter for the Gateway to turn into a tool input.
2. Each operation keeps its `operation_id`, which becomes the tool's name on the Gateway, and its one-line docstring, which becomes the tool's description. The payment's input keeps the name `amount`, which the Gateway's Policy reads.
3. The document needs the key or a signed-in handler, as the shared reads do.
4. The payment operation refuses any amount over the approval limit with a 403 that names the limit, before it looks at the claim. An over-limit payment then gets the same answer on any claim, which is what we expect to see when we try the Gateway's Policy in log-only mode.
5. A handler's sign-off pays the claim: the backend records the payment as part of the sign-off and the claim is decided. The sign-off doesn't need the agent's service, which the app on Lambda can't reach.
6. After a sign-off, nothing in the agent calls the payment operation for that claim, since it would now be refused. If the agent pauses for the sign-off and is resumed afterwards, the resume finishes its work without paying.

Done when:

- Tests check the document's exact set of operations and that it has no `servers`; a payment over the limit refused with a 403 on a claim that was never approved; a sign-off that pays the claim once; and an agent resumed after a sign-off that makes no payment call.
- With `npm run dev` running, after the dispatch in step 2, Dana Whitfield signs off a held payout on the dashboard and it's paid once.

## Step 4: Ready for Lambda

The backend and the dashboard go to Lambda as one package behind a Function URL, with the database on Supabase. The same app also has to keep running as an ordinary web server, as it does on the laptop.

The package:

1. One command builds the dashboard into a folder of static files, with the Supabase address and publishable key built in, read from `.env` when there is one and otherwise from the environment, so the build also works on a server with no `.env`. The build prints no warnings, and the checks still never read `.env`.
2. When that folder exists, the backend serves it at `/`. Its files are served at their own paths, and any other path outside `/api/` gets `index.html`, so the dashboard's pages load on a refresh. Every `/api/` path works as before, and an unknown one still gets a 404 in JSON. When the folder doesn't exist, the backend runs as it does today, and `npm run dev` is unchanged.
3. The backend has a Lambda handler for the app, made with Mangum with the startup hook turned off (`lifespan="off"`), so nothing seeds the database on Lambda. The app answers every request correctly without its startup hook having run.
4. `pyproject.toml` has a `server` dependency group, which we added, with the packages the backend needs on a server, uvicorn and Mangum among them. The deployment installs exactly this group. Keep it in step with what the backend imports, and add a check to `npm run check` that the backend imports with only this group installed, in a temporary environment of its own that leaves the project's environment alone.
5. The deployment package holds the backend, the data files it reads and the dashboard's build, with the server group's packages. At run time the backend imports nothing from outside the package (the agent's code included), reads files only from the package, and writes no files, since Lambda's file system is read-only.
6. The backend runs with only `DATABASE_URL`, `VITE_SUPABASE_URL` and `UNDERCOVER_API_KEY` set, which is the function's whole environment. Anything else it reads has a default or is needed only by work that can't start on Lambda.

The database:

7. Lambda starts a copy of the function for each request that arrives while the others are busy, so connections kept open by each copy would soon reach the pooler's connection limit. When `AWS_LAMBDA_FUNCTION_NAME` is set, the backend opens a connection for each request and keeps none between requests (SQLAlchemy's `NullPool`), with prepared statements turned off (psycopg's `prepare_threshold=None`). On Lambda, `DATABASE_URL` points at Supabase's transaction pooler on port 6543, which doesn't support prepared statements. On the laptop and on a web server, connections work as they do today.

The record:

8. `docs/TECH_STACK.md` gets a Deployment section that names the command that builds the dashboard and the folder it writes, what goes in the package, the Lambda handler, the app a web server runs, and the environment variables.

Done when:

- A test calls the Lambda handler with a Function URL event for `/api/health`, and with a stand-in dashboard build gets `index.html` for `/` and for a dashboard page.
- A test with `AWS_LAMBDA_FUNCTION_NAME` set finds a connection opened for each request with prepared statements off.
- The backend started on the laptop with `AWS_LAMBDA_FUNCTION_NAME` set and `DATABASE_URL` on port 6543 serves the claims to a signed-in handler.
- The server group check passes in `npm run check`.
- After the dashboard is built, the backend started on its own with uvicorn serves the dashboard at `http://127.0.0.1:8000`, where Dana Whitfield signs in and sees the claims, checked through the Playwright MCP server.
- The deployment package, built in a temporary folder with Linux packages for Python 3.12, is under Lambda's limit of 50 MB zipped. Report its size.

## What stays the same

- The rules in `docs/SPEC.md`, with the changes above. Update SPEC.md for the key, the check and the sign-off that pays.
- The claim agent's instructions, tools and versioned configuration, apart from the check before its first model call.
- The approval limit is still a setting, and the payment's limit reads it from there.
- The API rules in `docs/TECH_STACK.md`: every operation has an `operation_id`, a one-line docstring and no optional inputs.
- The agent's service stays on the laptop, where only the backend calls it.
- Tests never call a model, Supabase Auth or AWS, `npm run check` never reads `.env`, and the code follows `docs/CODE_STANDARDS.md`.
- `npm run seed` rebuilds everything, as it does today.
- Everything `npm run dev` starts, `npm run build` and `npm run check` work on Windows too (`docs/PROCESS.md`).
- Nothing in this change touches AWS, which comes when we deploy.

## What done looks like

- `npm run check` is green with `.env` moved out of the way, with the tests from each step.
- The live checks from each step pass after one `npm run seed`, with the default model. Report what they spent.
- `docs/SPEC.md`, `docs/TECH_STACK.md`, `docs/PROCESS.md`, `docs/STATUS.md` and `data/README.md` describe the product as it now is.

## Notes from our last build

These notes come from our own build of the improver, on the `week2day5-end` branch. If your build took a different path, a note may not match your code: follow its intent where it applies and skip it where it doesn't.

- **What our deployment expects:** it runs `npm run build` and takes the dashboard's files from `dashboard/dist`, gives Lambda the handler `backend.main.handler`, runs `backend.main:app` on a web server, and packs `backend/`, `data/` and `dashboard/dist/`. There's no `build` script in `package.json` yet, so add one, and put `handler` at the end of `backend/main.py`.
- **The agent's requests** all go through one `httpx.Client` in `agent/connection.py`, which the claim agent's client `agent/api.py` and the improver's `agent/improver_api.py` share, so the header goes there. The command line, `uv run -m agent CLM-1001`, loads `.env` after it imports the agent's modules, and the agent's tests swap the client for a test client, so read the key in `call` as each request is sent rather than setting it on the client.
- **The routes** are in `backend/main.py`, `backend/runs.py`, `backend/configuration.py` and `backend/improvement.py`. The handler's sign-in is `SignedIn` in `backend/dependencies.py`, and the dashboard already sends the handler's token on every request. The service's routes under `/api/rounds` take a `handler_id` and only check that it belongs to a handler.
- **The claim graph** is in `agent/harness.py`: the model and its tools, then `wait_for_sign_off` (an `interrupt`) and `pay`. The first message only names the claim and the model fetches it with `get_claim`, so the check fetches the claim itself. Making the check the graph's first node also covers a claim that starts again from its first message. `with_structured_output` only returns the call's usage, for its cost, with `include_raw=True`.
- **The sign-off** (`sign_off_claim`) puts the claim back in progress and asks the agent's service to resume it. The service's `resume_claim` refuses unless the claim is in progress and signed off, and `pay` then pays it. All three change in step 3.
- **The payment** (`pay_claim`) checks the claim's decision before the amount, and step 3 puts the limit first.
- **Seeding** is `seed` in `backend/database.py`. An evaluation picks its claims from the handlers' decisions, so CLM-1901 stays out of both sets as long as its decision isn't seeded.
- **The startup hook** in `backend/main.py` seeds the database when it finds no tables.
- **The build:** `dashboard/vite.config.ts` sets `envDir` for development only, and Vitest shares that config, so a build reads no `.env` yet, and the tests keep their own values.
- **The connections:** the pool is set up in `engine_for` in `backend/database.py`, with `CONNECTIONS = 4` for each process.
- **The end-to-end tests** play the agent's service in `e2e/api.ts`, through the dashboard's proxy with no key, and `playwright.config.ts` gives the test backend no key, so give the test backend a fixed key and send it from `e2e/api.ts`. `finishOpenRound` reads `/api/improvement` with no sign-in, and `agent.spec.ts` follows the old sign-off, where the agent pays.
- **The import check:** something like `uv run --isolated --only-group server python -c "import backend.main"` keeps the project's `.venv` as it is, whereas `uv sync --only-group server` would strip it.

## Planning

Follow `docs/PROCESS.md`, but write this plan to `docs/PLAN_SECURE.md` and tick it off there. Take the four steps in order, one phase each, and commit at the end of each phase. Do the live checks last, after reseeding once.
