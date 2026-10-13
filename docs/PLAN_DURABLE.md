# Plan: durable state

This plan builds what `docs/DURABLE.md` asks for on top of the finished harness, in six phases. Each phase leaves `npm run check` green and is committed before the next one starts.

SIDENOTE: For consistency with the course, please read `labs/week2day3.ipynb` and build the solution in the same style as the lab. Where the lab and this brief differ, follow the brief. Include this sidenote in your plan too.

When it's done, the backend works out payouts with UnderCover's payout rules and keeps its records in Supabase. The claim agent is a LangGraph graph that saves its progress in the same database after every step. An approval over the limit pauses the graph, and a handler's sign-off on the dashboard reaches the agent's own service, which picks the claim up and pays it. A claim stopped partway carries on from its last step, and the backend makes sure nothing is decided or paid twice. Every claim's work is traced in Langfuse, in one session per claim and thread.

## Design

### Modules

The backend:

- `database.py`: the tables, the engine and seeding, written once with SQLAlchemy Core for SQLite and Postgres. It owns `DATABASE_URL`, `UNDERCOVER_DB` and the `undercover` schema.
- `payout.py` (new): the payout rules from `labs/week2day1_payout.py`, as plain functions of a policy, the plans and the approval limit. It uses `models.py` and nothing else.
- `agent_service.py` (new): the one call the backend makes to the agent's service, and its address, `UNDERCOVER_AGENT` or `http://127.0.0.1:8002`.
- `main.py`: the operations. It uses `database`, `documents`, `payout`, `agent_service` and `models`.
- `documents.py`, `models.py` and `seed.py` keep their jobs, on SQLAlchemy.

The agent, in four parts:

- `api.py`: the backend's API, one function per operation. It gains `calculate_payout` and `get_latest_run`, and the payout request's shapes, `Benefit` and `Line`.
- `tools.py`: every tool and the contexts they read. It gains `calculate_payout` and loses `pay_claim`. `record_decision` also tells the graph what the backend recorded.
- `harness.py`: builds and runs the agents: the model, the checkpointer, the claim graph with its state, nodes and edges (in place of the middleware), `work_claim`, `carry_on`, the queue agent and `run_queue`.
- `service.py` (new): the agent's service, a small FastAPI app with the one operation the backend calls. It uses `harness` to carry the claim on and `api` to check the claim.
- `__main__.py`: the command line. It opens the checkpointer and calls `harness`.

The agent reaches the backend only through `api.py`, and the backend reaches the agent only through `agent_service.py`. Neither imports the other. Inside the agent: `service` and `__main__` use `harness`, `harness` uses `tools` and `api`, and `tools` uses `api`.

The dashboard changes only its types in `api.ts` and the decision panel. The end-to-end tests gain a stand-in for the agent's service, `e2e/agent_stand_in.ts`.

### How a claim is worked

1. `work_claim` starts the claim as a new attempt with a new thread id, as today, and runs the claim graph on that thread.
2. The claim agent reads the claim, looks up the sections it needs, works out any payout with `calculate_payout`, and records its decision. Recording the decision ends its turn.
3. A decline or a referral is decided, and the graph ends. For an approval the backend says whether it can be paid now. If it can, the graph pays it. If it needs a sign-off, the graph pauses with `interrupt()` and `work_claim` reports it as waiting for sign-off.
4. A handler signs off on the dashboard. The backend saves the sign-off, moves the claim to in progress and tells the agent's service. The service carries the claim on from the pause, and the graph pays it.
5. If the agent is stopped at any point, the claim stays in progress with its progress saved. The next queue run carries it on from its last saved step, on the same thread and attempt, before it starts working new claims.
6. A claim that fails with an error before it is decided goes back in the queue and starts afresh, as today.

### Following the lab

As in the lab: a `TypedDict` state with `add_messages`; an `agent` node that calls the model with the tools bound; LangGraph's `ToolNode`; conditional edge functions named `after_agent` and `after_tools`; the pause in a node of its own, because a resumed node runs again from the top; the payment in a node of its own; `PostgresSaver` with `autocommit=True`, `prepare_threshold=0` and `row_factory=dict_row`, and the schema set with `search_path`; `durability="sync"`; `Command(resume=...)`; and `get_state()` with its `next` and `interrupts`.

Where the brief differs, we follow the brief:

- The claim agent records its decision with the `record_decision` tool, so there is no separate decide node with structured output.
- The graph never compares a payout with the limit. It pauses when the backend's reply to `record_decision` says the claim waits for sign-off.
- Payments are made by the backend's `pay_claim`, which refuses a second payment, in place of the lab's `payments` table.
- Each attempt has its own thread id, a new UUID kept on the claim, in place of the claim id.
- The tables go in the `undercover` schema, and each process opens a pool of at most 4 connections in place of the lab's single connection.

### Claim states

| State | Meaning | Label on screen | Color |
| --- | --- | --- | --- |
| `waiting` | In the queue: not started, or back after a failed attempt | Waiting | Cerulean |
| `in_progress` | The agent is working on it, or is about to pay an approval, including one a handler has just signed off | In progress | Marigold |
| `waiting_for_sign_off` | Approved with a payout over the limit, and the agent has paused until a handler signs off | Waiting for sign-off | Coral |
| `decided` | Paid, declined or referred | Decided | Sea Green |
| `left_for_handler` | The agent failed on it twice | Left for a handler | Raspberry |

A claim moves `waiting` → `in_progress` → `decided`, or `in_progress` → `waiting_for_sign_off` → `in_progress` → `decided`. An approval within the limit now stays in progress until it is paid, so a claim stopped between its decision and its payment is still found and carried on. A failure before the decision still moves a claim back to `waiting`, or to `left_for_handler` after its second attempt.

### The claim graph

The state, `ClaimState`:

- `messages`, with `add_messages`
- `model_calls`: how many times the agent node has called the model. It is saved with the rest, so the limit of 30 holds across a restart.
- `decision` and `status`: the decision and the claim's status as the backend returned them from `record_decision`. The `record_decision` tool returns a `Command` that adds its tool message and sets these two, which is LangGraph's way for a tool to update the state.

The claim id stays in `ClaimContext`, passed with `context=` on every invoke, so the tools still act only on their own claim.

The nodes:

- `agent`: calls the model with the claim instructions as the system message and the messages so far. It records the reply's text as a `message` step and each tool call as a `tool_call` step, and adds one to `model_calls`. Before calling the model it raises `TooManyModelCalls` if the claim agent has already made 30 calls.
- `tools`: `ToolNode(CLAIM_TOOLS)`. `handle_tool_errors` sends the backend's refusals, a `ToolException` and calls with bad arguments back to the model, and lets any other error stop the graph. `wrap_tool_call` records each `tool_result` step and any step a tool gives as its artifact, such as a section it read.
- `wait_for_sign_off`: pauses with `interrupt()`. When the graph is resumed it returns, and nothing before the interrupt has side effects, so running it twice is harmless.
- `pay`: pays the decision's payout with `pay_claim` and sets `status` from the backend's reply.

The edges:

| From | To | When |
| --- | --- | --- |
| START | `agent` | always |
| `agent` | `tools` | the reply calls tools |
| `agent` | END | the reply calls no tools: the agent finished without a decision |
| `tools` | `agent` | no decision has been recorded yet |
| `tools` | `wait_for_sign_off` | the backend holds the approval for a sign-off (`status` is `waiting_for_sign_off`) |
| `tools` | `pay` | an approval the backend can pay now (`status` is `in_progress`) |
| `tools` | END | a decline, a referral, or an approval already paid |
| `wait_for_sign_off` | `pay` | always |
| `pay` | END | always |

LangGraph's recursion limit stays at its default of 10,007 steps (`DEFAULT_RECURSION_LIMIT` in `langgraph/_internal/_config.py`), so `model_calls` is the real limit.

The harness invokes the claim graph in a fresh `contextvars.Context`, so its run is a root run even when the queue agent's `work_claim` tool calls it. Langfuse sets a session only on a root run (`parent_run_id is None` in its `CallbackHandler`), so without this a claim worked in a queue run would have no session. The checkpointer needs nothing extra: because the claim graph's config gives its own thread id, LangGraph's `ensure_config` drops the queue agent's internal keys, and the claim graph keeps its own checkpointer.

### Saving progress

- `harness.checkpointer()` is a context manager that opens a `psycopg_pool.ConnectionPool` on `DATABASE_URL` with at least 1 and at most 4 connections, each with `autocommit=True`, `prepare_threshold=0`, `row_factory=dict_row` and `search_path` set to `undercover`. It creates the schema if it's missing, runs the saver's `setup()` and yields a `PostgresSaver`.
- The agent is synchronous throughout, with the synchronous saver, because async Postgres connections don't work with Windows' default event loop.
- Every invoke of the claim graph passes `durability="sync"`, so each step's checkpoint is saved before the next step starts.
- `uv run -m agent` and the agent's service each open one checkpointer. The tests give the graph an `InMemorySaver` and never open Postgres.

### Carrying on

`carry_on(claim_id, graph)` carries an in-progress claim on from its saved progress, on the claim's thread, without a new attempt:

- If the thread is at `wait_for_sign_off`, the claim has been signed off, and it resumes past the pause with `Command(resume=True)`. The backend holds who signed off and when.
- If the thread has nothing saved (its snapshot has no `created_at`), because the agent was stopped before its first step was saved, and the claim has no decision, it starts the graph from the beginning on the same thread.
- Otherwise it invokes the graph with no input, which carries on from the last saved step, finishing a step whose writes were saved before its checkpoint. A graph that had already finished without a decision does nothing more, and the claim is failed as below.

`work_claim` and `carry_on` share one function that invokes the graph and settles the claim afterwards, as `work_claim` does today:

- Any exception is caught, so one bad claim never stops the run.
- A claim still in progress with no decision is failed with `fail_claim`, which puts it back in the queue or leaves it for a handler. It starts afresh next time, with a new thread.
- A claim with a decision is never failed. An approval whose payment failed stays in progress and the next run carries it on to the payment.
- The report is built from the backend's record, as today, with one new line: `CLM-1001  approve  $420.00, not paid yet` for an approval still waiting for its payment.

A queue run, `run_queue(cap, llm, graph)`:

1. If the latest run is still running, because it was stopped, the harness finishes it with the summary "The run stopped before it finished."
2. It carries on every claim in progress and prints each report. This replaces `recover()`. These claims don't count toward the new run's cap.
3. Then it works the queue as today. With no claim waiting it prints "No claims are waiting" and starts no run.

As today, the harness can't tell a stopped claim from one that another process is working at that moment, so don't start a run while a single claim is being worked. The same holds for a claim the agent's service is paying, which takes about a second. If both pick it up, the backend still pays it once.

### Nothing happens twice

A step can run again after a restart, so the backend treats a repeat as done:

- `record_decision` on a claim that already has a decision returns the claim when the decision and payout are the same, and refuses anything else with a 409.
- `pay_claim` on a claim already paid returns the claim when the amount is the same, and refuses a different amount with a 409.

A restart can also record a step twice on the dashboard, when the agent was stopped between recording a step and saving the checkpoint. That is the only thing that can repeat.

### The payout rules

- `backend/payout.py` holds the rules from `labs/week2day1_payout.py`: the per-item limit by quantity, electronics with and without Electronics Plus, cash up to $100 in all, hotel nights by rooms, meals without receipts per traveler per day, what others have paid, the deductible for baggage and emergency medical, the benefit maximum (capped at the trip cost for cancellation and interruption), and nothing below zero. The lab's constants for cash, hotel nights and meals stay named constants there.
- It reads nothing from `data/`. Seeding stores `plans.json` in `settings`, and the operation passes the claim's policy, the plans and the approval limit from `settings` to the rules. `needs_sign_off` follows that limit.
- The lab's file stays in `labs/` as it is.

### Tracing

- Every invoke of the claim graph passes Langfuse's `CallbackHandler` in its config, with `langfuse_session_id` set to the claim and its thread, such as `CLM-1008:6f1c…`, and `langfuse_trace_name` set to "Work claim" or "Carry on". The first run, a carry-on after a restart and a carry-on after a sign-off all land in the claim's session.
- The keys come from the environment. The tests have no keys, and Langfuse's client then sends nothing.
- The queue agent isn't traced.

### The database

- The backend uses Postgres only when `DATABASE_URL` is in its environment, and SQLite at `UNDERCOVER_DB` or `undercover.db` otherwise. `npm run dev` passes `.env` with `uv run --env-file .env`. The tests, the end-to-end tests and `uv run -m backend.seed` never read `.env`.
- SQLAlchemy Core: the tables are `Table` objects in one `MetaData`, and every query is a Core expression, written once for both databases. `claim_view` becomes a `select()` in `database.py`. Records are stored with SQLAlchemy's `JSON` type.
- Postgres: the driver is psycopg (`postgresql+psycopg`), with `search_path` set to `undercover` on every connection, so the same queries work on both. The pool has 4 connections and no overflow, with `pool_pre_ping`. SQLite opens a connection per request, as today (`NullPool`), so the tests don't hold files open.
- Postgres has no `rowid`, so `runs` gains an integer key that counts up, which `get_latest_run` orders by, and `documents` gains a `position` that keeps the wording first. `run_id` stays the UUID the agent uses.
- Each request's work commits in one transaction. The database dependency has `scope="function"`, so the commit happens before the response is sent and before any background task runs.
- Seeding: on Postgres it creates the `undercover` schema if needed. On both, it drops and creates the backend's tables and loads `data/`. It leaves the checkpointer's tables alone, since a reseeded claim always gets a new thread. The backend seeds on startup when the `claims` table is missing.
- `npm run seed` reseeds the database `npm run dev` uses (`uv run --env-file .env -m backend.seed`). `uv run -m backend.seed` alone seeds SQLite, as the end-to-end tests do.
- Connections: Supabase's free plan allows 15 through the session pooler. The backend, the agent's service and a queue run use at most 4 each, so at most 12, plus one that Supabase's `pg_net` keeps open.

### API

New and changed operations. The others are as in `docs/PLAN_HARNESS.md`. Every operation keeps an `operation_id`, a one-line docstring and no optional inputs, now including the fields of the models inside a request body.

| Operation | Route | What it does |
| --- | --- | --- |
| `calculate_payout` | `POST /api/claims/{claim_id}/payout` | Body `{benefit, lines, paid_by_others}`. Works out the payout on the claim's policy with the payout rules and records nothing. Returns `{calculation: [{step, amount}], payout, needs_sign_off}` |
| `record_decision` | `POST /api/claims/{claim_id}/decision` | An approval within the limit stays in progress until it is paid. A repeat returns the claim |
| `pay_claim` | `POST /api/claims/{claim_id}/payment` | Returns the claim. Records the payment with the sign-off, if there was one, and decides the claim. A repeat returns the claim |
| `sign_off_claim` | `POST /api/claims/{claim_id}/sign-off` | Records who signed off and when, moves the claim to in progress and pays nothing. Once that's saved, tells the agent's service |
| `fail_claim` | `POST /api/claims/{claim_id}/failure` | Also refuses a claim that has a decision |
| `get_claim` | `GET /api/claims/{claim_id}` | The decision gains `signed_off_by` and `signed_off_at`, and the payment gains `signed_off_at` |

A line of a payout request has `description`, `amount`, `quantity`, `kind` (`item`, `electronics`, `cash`, `expense`, `hotel` or `meals_without_receipts`), `nights` and `hours`, all required. `benefit` is one of `trip_cancellation`, `trip_interruption`, `trip_delay`, `baggage_delay`, `baggage`, `passport` and `emergency_medical`. The calculation step is named `CalculationStep` in `models.py`, since `Step` is already the agent's step.

Rules the backend enforces:

- `calculate_payout` returns 404 for an unknown claim and 422 for an unknown benefit or kind, a quantity below 1 or a missing field.
- `record_decision`: a claim with a decision returns the claim for the same decision and payout, and 409 for anything else. Otherwise it needs a claim in progress (409). An approval over the limit moves the claim to `waiting_for_sign_off`, an approval within it stays `in_progress`, and a decline or a referral moves it to `decided`.
- `pay_claim` needs an approved claim (409). A claim already paid returns the claim for the same amount and 409 for a different one. A payout over the limit with no sign-off returns 403 with "A payout over $1,000.00 needs a handler's sign-off" and records nothing. The amount must equal the approved payout (422). The payment records the sign-off's handler and time, and the claim moves to `decided`.
- `sign_off_claim` needs a claim waiting for sign-off (409) and a known handler (404) who can approve over the limit (403). It records the handler's name and the time on the decision and moves the claim to `in_progress`. A FastAPI background task then calls `resume_claim` on the agent's service, after the sign-off is committed and the response is sent. If the service can't be reached, the backend logs a warning and the sign-off stands.
- `fail_claim` needs a claim in progress with no decision (409).

### The agent's service

- `agent/service.py`, a FastAPI app on port 8002, which `npm run dev` starts beside the backend and the dashboard with `uv run --env-file .env uvicorn agent.service:app --port 8002 --reload --reload-dir agent`. In the cloud the agent will run as a service like this.
- Its lifespan opens the checkpointer. A FastAPI dependency builds the claim graph for each request, with the model and that checkpointer, so the service doesn't need the backend at startup and picks up any change to the instructions.
- `health`, `GET /api/health`.
- `resume_claim`, `POST /api/claims/{claim_id}/resume`, no body: "Pick a claim back up after a handler's sign-off." It returns 409 for a claim that isn't in progress. Otherwise it returns 202 straight away and carries the claim on in a background task, logging the report line.
- It follows the same API rules as the backend, checked by the same test.
- It never looks for other claims to carry on. Only a queue run does that, so the service and a run never sweep the same claims.
- The tests use the app without its lifespan and give it a claim graph on a stub model through `dependency_overrides`.

### Instructions

- **Working a claim**, changed as goals: an approval's payout is worked out with `calculate_payout`, which applies UnderCover's payout rules, and the decision records the payout it returns. Which lines are covered, and what counts as one item, are the agent's judgment. Recording the decision is the last thing the agent does, so the decision's reason carries the explanation. The system pays an approved claim, after a handler's sign-off when the payout is over the approval limit. `pay_claim` and the closing reply are no longer mentioned.
- **Running the queue** is unchanged.

### Dashboard

- **The decision panel.** An approval in progress without a payment says "Waiting for the agent to pay it." After a sign-off it first says "Signed off by Dana Whitfield at 2:05 PM." A payment after a sign-off reads "Paid $1,350.00, signed off by Dana Whitfield at 2:05 PM". The sign-off form is as today.
- `api.ts` gains the new fields. Nothing else changes: the queue and a claim page already refresh every two seconds.

### End-to-end tests

- Playwright starts a stand-in for the agent's service, `e2e/agent_stand_in.ts`, run by Node's own TypeScript support, on port 8003. It answers `GET /api/health` and `POST /api/claims/{claim_id}/resume` with 202, and lists the claims it was asked to resume at `GET /api/resumed`. The end-to-end backend gets `UNDERCOVER_AGENT=http://127.0.0.1:8003`, so the tests never reach the service `npm run dev` starts.
- `e2e/api.ts` names the stand-in's address once.
- The sign-off test signs off `CLM-1020` on the dashboard, checks the claim is In progress and that the stand-in was asked to resume it, then plays the agent by paying through the API.

### Checked against the code standards

- One way to call each service, with each address written once: the agent to the backend through `api.py`, the dashboard through `api.ts`, the backend to the agent's service through `agent_service.py`, and the end-to-end tests to the stand-in through `e2e/api.ts`. The backend and the agent each name `DATABASE_URL` and the `undercover` schema once, in `database.py` and `harness.py`, since neither imports the other.
- Modules keep to their jobs: the payout rules are apart from the routes, the service only receives the backend's call and hands it to the harness, and the graph's nodes take the place of the middleware in the harness.
- The framework's own way: `StateGraph`, `ToolNode` with `handle_tool_errors` and `wrap_tool_call`, `Command` from a tool, `interrupt()` and `Command(resume=...)`, `PostgresSaver` on a `ConnectionPool`, `durability="sync"`, FastAPI's `BackgroundTasks` and dependency `scope`, SQLAlchemy Core's `Table` and `select()`, and Langfuse's `CallbackHandler` with `langfuse_session_id`.
- Functions do one job: `work_claim` starts an attempt, `carry_on` picks one up, and one shared function invokes the graph and settles the claim.
- No defensive code beyond what the brief asks: the harness keeps its one catch around a claim, and the backend catches only a failure to reach the agent's service, because the sign-off must stand.
- The instructions stay goals. What must always happen in order, paying after the decision and after the sign-off, is done by the graph.

### How the criteria are checked

API calls run against `npm run dev` on a freshly seeded database: SQLite with `uv run -m backend.seed` in phase 1, and Supabase with `npm run seed` from phase 2. Tables and connections are checked through the Supabase MCP server, which is read-only. Langfuse is checked through its API with a short `uv run python -c` that loads `.env` and calls `get_client().api.trace.list(session_id=...)`. Pages are checked in the browser with the Playwright MCP server at `http://localhost:5173`. Tests never call a model and need no network. Only the criteria marked "Live" use the real model, on the default model through OpenRouter. Every live run comes straight after a reseed and works at most five claims.

## Phase 1: The payout rules and tracing

Bring in the payout rules as `backend/payout.py` and the `calculate_payout` operation, seed `plans.json` into `settings`, and give the claim agent the `calculate_payout` tool. Rewrite the claim instructions for it. Trace each claim agent run in Langfuse, invoked in a fresh `contextvars.Context` so it is a root run in the claim's session. Move the OpenAPI rules check into a shared test helper, `api_rules.py` beside the root `conftest.py`, and extend it to the models inside a request body.

- [x] `curl -s -X POST localhost:8000/api/claims/CLM-1007/payout` with a smartphone line of 1,099.00 (`kind` `electronics`, quantity 1, nights and hours 0), benefit `baggage` and 0 paid by others returns payout 50.0, the steps "Smartphone, limited to $150.00" (150.0) and "Less the deductible" (-100.0), and `needs_sign_off` false
- [x] The same for `CLM-1003` with one `expense` line of 3,800.00 under `emergency_medical` returns 3,750.0 with `needs_sign_off` true
- [x] `CLM-1002` with a suitcase of 280.00, a wool suit of 420.00 and four shirts of 120.00 (quantity 4), all `item`, under `baggage` with 100.00 paid by others, returns 550.0, including the step "Wool suit, limited to $300.00"
- [x] `CLM-1001` with a hotel of 245.00 for one night and two `expense` lines of 95.00 and 80.00 under `trip_delay` returns 420.0 with no deductible
- [x] A line without `nights` returns 422, a benefit of `pets` returns 422, and `CLM-9999` returns 404
- [x] pytest covers every rule in the design, with a test for each kind of line, the deductible applying only to baggage and emergency medical, the cap at the trip cost, and a payout that would fall below zero. With the limit in `settings` changed to 500, a payout of 550.00 needs sign-off
- [x] `grep -rn "data" backend/payout.py` finds nothing, and `grep -rn 1000 backend --include=*.py` finds nothing outside `backend/tests/`
- [x] The shared OpenAPI test passes, and fails on a request model with an optional field nested in its body (checked with a model defined in the test)
- [x] A pytest test checks that the claim agent's tools are exactly `get_claim`, `get_policy`, `get_claim_history`, `search_documents`, `read_section`, `calculate_payout`, `record_decision` and `pay_claim`, each named after a backend operation, and none takes a claim id
- [x] Stub model test: the stub calls `calculate_payout` for `CLM-1001` with the lines above, and the tool result recorded on the claim holds payout 420.0
- [x] `curl -s localhost:8000/api/instructions` shows the claim instructions naming `calculate_payout`
- [x] Stub model test, with a recording callback handler in place of Langfuse's: working `CLM-1001` starts one root run named "Work claim" with the session id `CLM-1001:` followed by the claim's thread id
- [x] The same inside a queue run with two claims: each claim agent's run is a root run with its own claim's session, not a child of the queue agent's run
- [x] Live: after reseeding and with `npm run dev` running, `uv run -m agent CLM-1001` decides the claim. Its steps include a `calculate_payout(...)` call, and the decision's payout equals the payout the tool returned
- [x] Live: through Langfuse's API, the session `CLM-1001:<thread id>` has a trace named "Work claim" with at least two model calls and the tool calls between them
- [x] `npm run check` passes

## Phase 2: Our records on Supabase

Add SQLAlchemy with `uv add sqlalchemy`. Rewrite `backend/database.py` and every query with SQLAlchemy Core, as the design says, and point the backend at Supabase when `DATABASE_URL` is set. Add `npm run seed`, and make `npm run dev` pass `.env` to the backend. Test helpers that change the database go through the backend's engine.

- [x] `grep -rn "sqlite3\|rowid" backend agent` finds nothing
- [x] pytest, without connecting: with `DATABASE_URL` set to a Postgres address, the engine uses `postgresql+psycopg`, a pool of 4 with no overflow, and `search_path` set to `undercover`. Without it, the engine is SQLite at `UNDERCOVER_DB`
- [x] `DATABASE_URL=postgresql://nobody:x@127.0.0.1:1/none uv run pytest -q` passes: the tests remove it and never connect
- [x] pytest: the backend seeds an empty SQLite file on startup, and two runs started in the same second come back from `get_latest_run` in the order they started
- [x] `uv run -m backend.seed` still prints `Seeded 25 claims, 50 policies, 49 customers and 3 handlers into undercover.db`
- [x] `npm run seed` prints `Seeded 25 claims, 50 policies, 49 customers and 3 handlers into the undercover schema on Postgres`, and a second run prints the same
- [x] Supabase MCP: `list_tables` for `undercover` shows `settings`, `documents`, `handlers`, `customers`, `policies`, `claims`, `decisions`, `payments`, `steps`, `runs` and `todos`, and none of them is in `public`. `select status, count(*) from undercover.claims group by status` gives 25 `waiting`
- [x] With `npm run dev` running, the pilot's read criteria hold against Supabase: `curl -s localhost:8000/api/claims` returns 25 claims, the first `CLM-1001` for Maya Patel, and `curl -s localhost:8000/api/claims/CLM-1001` returns its story, 3 items and 4 documents
- [x] Walked through with curl on Supabase: starting `CLM-1004` and declining it gives `decided`. Supabase MCP shows its row in `undercover.decisions`. `npm run seed` puts it back to `waiting`
- [x] Supabase MCP, with `npm run dev` running and the queue page open for 30 seconds: `select count(*) from pg_stat_activity where usename = 'postgres'` is at most 5, the backend's 4 and `pg_net`'s 1
- [x] Supabase MCP: `get_advisors` for security lists nothing about the `undercover` schema
- [x] Browser: the queue shows 25 claims and `/claims/CLM-1002` shows its items and policy, with no errors in `browser_console_messages`
- [x] Live: after `npm run seed`, `uv run -m agent CLM-1001` decides the claim, and Supabase MCP shows its decision and steps in `undercover`
- [x] `npm run check` passes, both with `.env` in place and with it moved out of the way

## Phase 3: The claim agent as a graph that saves its progress

Add `uv add psycopg-pool`. Replace the claim agent's `create_agent` and middleware with the graph in the design, and save its progress with the Postgres checkpointer. Remove the `pay_claim` tool and update the claim instructions. In the backend, keep an approval within the limit in progress until it is paid, treat a repeated decision or payment as done, have `pay_claim` return the claim, and have `fail_claim` refuse a claim with a decision. The sign-off itself still pays until phase 4, which leaves a paused thread behind. Nothing picks it up yet.

- [x] A pytest test checks the graph's nodes, `agent`, `tools`, `wait_for_sign_off` and `pay`, and its edges, against the table in the design
- [x] A pytest test checks that the claim agent's tools are exactly `get_claim`, `get_policy`, `get_claim_history`, `search_documents`, `read_section`, `calculate_payout` and `record_decision`
- [x] pytest, backend: approving `CLM-1001` for 420.00 leaves it `in_progress`, and paying it returns the claim `decided` with the payment. The same decision again returns the claim with one decision, and a payout of 400.00 returns 409. Paying 420.00 again returns the claim with one payment, and 400.00 returns 409
- [x] pytest, backend: `fail_claim` on an approval in progress returns 409 and changes nothing
- [x] Stub model test, within the limit: the stub reads the claim, works out the payout and approves 420.00. The graph pays it, with no `pay_claim` tool call in the steps, the model is called no more after the decision, and the report is `CLM-1001  approve  $420.00`
- [x] Stub model test, over the limit: the stub approves `CLM-1002` for 1,350.00. The report is `CLM-1002  approve  $1,350.00, waiting for sign-off`, `get_state` shows `next` as `("wait_for_sign_off",)` with one interrupt, and there is no payment
- [x] Stub model test: with the limit in `settings` raised to 2,000, the same approval is paid straight away, since the graph follows the backend
- [x] Stub model tests for a decline and a referral: both are `decided`, with no payment and no `pay` step in the state history
- [x] Stub model test: an approval with payout 0 goes back to the model as a refusal, the graph returns to the agent, and the stub's next, valid decision is paid
- [x] The harness's tests of steps and refusals pass on the graph: the steps in order, the reading step, a read of section 15 and a read of a `handbook` going back to the model
- [x] Stub model test: a stub that calls `get_claim` over and over stops after 30 model calls with `failed: TooManyModelCalls: ...`, and the claim is back in the queue
- [x] Stub model test: a provider error puts the claim back in the queue, and working it again starts a new attempt on a new thread, whose first prompt holds only the claim instructions and the message naming the claim. After a second failure it is left for a handler
- [x] Stub model test: when paying raises `RuntimeError`, the claim stays `in_progress` with its decision and no `error` step, and the report ends `, not paid yet`
- [x] Stub model test, a queue run with two claims: each claim's checkpoints are in the claim graph's saver under its own thread id, at the top level, and the queue agent's saver holds only the run's thread
- [x] A test checks that every invoke of the claim graph passes `durability="sync"` and the Langfuse handler
- [x] `curl -s localhost:8000/api/instructions | grep -c pay_claim` prints 0
- [x] e2e: in the agent-at-work test, `CLM-1003` stays In progress after its approval, and shows Decided and "Paid $500.00" after its payment
- [x] Live: with `npm run dev` running, `uv run -m agent CLM-1001` after `npm run seed` approves and pays the claim, with no `pay_claim` call in its steps. Supabase MCP shows `checkpoints`, `checkpoint_blobs`, `checkpoint_writes` and `checkpoint_migrations` in `undercover`, and rows in `undercover.checkpoints` for the claim's thread id
- [x] Live: after `npm run seed`, `uv run -m agent CLM-1003` prints a report that ends `, waiting for sign-off`. Supabase MCP shows a write on the channel `__interrupt__` in `undercover.checkpoint_writes` for its thread
- [x] `npm run check` passes

## Phase 4: A sign-off picks the claim back up

Change `sign_off_claim` to record who signed off and when, move the claim to in progress and tell the agent's service. Add `carry_on` for a thread paused at `wait_for_sign_off`, `backend/agent_service.py`, the agent's service in `agent/service.py`, the service in `npm run dev`, the new decision panel, and the stand-in for the end-to-end tests.

- [x] pytest, backend: signing off `CLM-1002`'s held 1,350.00 as `HND-01` returns the claim `in_progress` with the decision signed off by Dana Whitfield at a time, and no payment. Paying 1,350.00 then returns the claim `decided`, with a payment that records Dana Whitfield and the time of the sign-off. The 404, 403 and 409 rules of `sign_off_claim` still hold
- [x] pytest, backend: the agent's service is told once, for `CLM-1002`, and only once the sign-off is saved: the recorder put in place of the service reads the claim from the database at that moment and finds the sign-off
- [x] pytest, backend: when the agent's service can't be reached, the sign-off returns 200 and stands, and a warning is logged
- [x] pytest, backend: `pay_claim` on a held claim still returns 403 and records nothing
- [x] The shared OpenAPI test passes for the backend and for the agent's service
- [x] Stub model test, the whole sign-off: the stub approves `CLM-1002` for 1,350.00 and the graph pauses. After the sign-off through the backend, `resume_claim` on the agent's service returns 202, and the claim is `decided` with one payment of 1,350.00 signed off by Dana Whitfield. The model isn't called again, and the carry-on is a root run named "Carry on" in the claim's session. A second `resume_claim` returns 409 and the claim still has one payment
- [x] `resume_claim` on a claim waiting for sign-off returns 409 and changes nothing
- [x] With `npm run dev` running, `curl -s localhost:8002/api/health` returns `{"status":"ok"}`, beside the backend on 8000 and the dashboard on 5173
- [x] `grep -rn "UNDERCOVER_AGENT\|8002" backend --include=*.py` finds them only in `backend/agent_service.py`
- [x] vitest covers the decision panel for an approval waiting for its payment, a signed-off claim waiting for its payment, and a payment with its sign-off
- [x] e2e, sign-off: the test approves `CLM-1020` for 1,350.00 through the API, and a payment attempt returns 403. On the dashboard, choosing Dana Whitfield and pressing "Sign off" shows In progress and "Signed off by Dana Whitfield", and the stand-in lists `CLM-1020`. After the test pays 1,350.00 through the API, the page shows Decided and "Paid $1,350.00, signed off by Dana Whitfield at" a time, without a reload
- [x] Browser: screenshots of a signed-off claim waiting for its payment, in light and dark mode, show rounded panels with no outlines, no one-edge borders and no gradients, and `browser_console_messages` shows no errors
- [x] Live: after `npm run seed` and with `npm run dev` running, `uv run -m agent CLM-1003` leaves the claim waiting for sign-off. In the browser, signing off on `/claims/CLM-1003` as Dana Whitfield shows Decided and "Paid", with Dana Whitfield and the time, within five seconds (`browser_wait_for`), and the agent's service logs the report line
- [x] Live: through Langfuse's API, `CLM-1003`'s session has a "Work claim" trace from before the sign-off and a "Carry on" trace from after it
- [x] `npm run check` passes

## Phase 5: Work survives a restart

Complete `carry_on` for a claim stopped partway, and make a queue run first finish a stopped run and carry on every claim in progress. The tests stop the agent with `KeyboardInterrupt`, which the harness doesn't catch, so the claim is left as a crash leaves it.

- [x] Stub model test: the stub reads the claim and its policy, then raises `KeyboardInterrupt`. The claim is `in_progress` with attempts 1. With a new graph on the same saver and a new stub, `carry_on` decides it. The thread id and attempts are unchanged, the new stub's first prompt holds the two earlier tool results, the steps carry on under the same thread with no `error` step, and the claim has one decision
- [x] Stub model test: stopped just after the backend records the decision, the claim carries on with the same decision, which the backend treats as done, and is paid once
- [x] Stub model test: stopped just after the backend records the payment, the claim carries on, the `pay` step runs again, and there is still one payment
- [x] Stub model test: a claim in progress with no checkpoint starts from the beginning on its own thread, with attempts unchanged
- [x] Stub model test: 20 model calls before the stop and an endless `get_claim` after it stop at 30 calls in all
- [x] Stub model test: a claim that fails with an error while carried on goes back in the queue, and the next `work_claim` is attempt 2 on a new thread
- [x] Stub model test, a queue run: with one claim stopped partway and one signed off while the agent was away, `run_queue` carries both on and prints their reports before the queue agent starts, and neither counts toward the cap
- [x] Stub model test: when the latest run is still running, `run_queue` finishes it with "The run stopped before it finished." and starts a new run, which becomes the latest
- [x] With nothing waiting, `run_queue` still carries on a claim in progress, then prints "No claims are waiting"
- [x] Command line: `uv run -m agent` opens the checkpointer, builds the claim graph and runs the queue, and `CLM-1001` works one claim (tested with the checkpointer and the run stubbed out)
- [x] Live: after `npm run seed` and with `npm run dev` running, start `uv run -m agent --cap 1`. Once the claim in progress shows at least four steps, kill the agent's Python process with `kill -9`. Running `uv run -m agent --cap 1` again prints that claim's report first. The claim has the same thread id, attempts 1, one decision, and steps from both runs under that thread with no `error` step. The stopped run shows "The run stopped before it finished."
- [x] Live: after `npm run seed`, with `npm run dev:backend` and `npm run dev:dashboard` running but not the agent's service, `uv run -m agent CLM-1003` waits for sign-off. Signing off on the dashboard leaves it In progress and the backend logs a warning. `uv run -m agent --cap 1` then pays it first, with the sign-off on the payment
- [x] `npm run check` passes

## Phase 6: A trial on five claims

Run the trial the brief describes, then bring `docs/SPEC.md`, `docs/TECH_STACK.md`, `docs/PROCESS.md`, `docs/CODE_STANDARDS.md` and `docs/STATUS.md` up to date.

- [x] Live: after `npm run seed` and with `npm run dev` running, `uv run -m agent --cap 5` works five claims and finishes the run with its summary. At least one waits for sign-off (on September 30, `CLM-1008` and `CLM-1011` did)
- [x] Live, in the browser: signing off a held claim as Dana Whitfield shows it Decided and paid, with the handler and the time, within five seconds
- [x] Live: Supabase MCP, checked several times during the run and the sign-off: `select count(*) from pg_stat_activity where usename = 'postgres'` never shows more than 12
- [x] Live: through Langfuse's API, the held claim's session has traces from before and after the sign-off
- [x] Live: afterwards the queue shows Waiting 20 and In progress 0
- [x] `docs/SPEC.md`: its section on working the queue describes the pause for a sign-off, the agent picking the claim up after it, carrying on after a restart without a new attempt, and nothing decided or paid twice. Its Rules are unchanged
- [x] `docs/TECH_STACK.md` names SQLAlchemy Core with Supabase and SQLite in the tests, the claim graph with the Postgres checkpointer and `durability="sync"`, Langfuse, the agent's service and `UNDERCOVER_AGENT`, and the entry points `run_queue(cap, llm, graph)`, `work_claim(claim_id, graph)` and `carry_on(claim_id, graph)`
- [x] `docs/PROCESS.md`: `npm run dev` starts the backend, the agent's service and the dashboard; `npm run seed` reseeds Supabase; the tests need no network
- [x] `docs/CODE_STANDARDS.md`: the agent has four parts, and the backend reaches the agent's service only through `backend/agent_service.py`
- [x] `docs/STATUS.md` describes what's built, how to seed, run and sign off, and the time and decisions of the live run
- [x] `npm run check` passes, both with `.env` in place and with it moved out of the way

## Not in this plan

- Rejecting a held payout, which comes later. The graph keeps the agent's whole conversation at the pause, so a handler's note can go back to it then.
- Saving the queue agent's progress. A stopped run is finished by the next run, and its claims are carried on, but its conversation and to-do list aren't resumed.
- Clearing old checkpoints. Reseeding rebuilds the backend's tables and leaves the checkpointer's, and a reseeded claim always gets a new thread.
- Tracing the queue agent.
- Telling a run which claims another process is working, as above.
- Running the agent's service in the cloud.
- Scoring the agent against the handlers' decisions in `data/evals/`.
- Sign-in, real payments and messages to customers, as `SPEC.md` says.
