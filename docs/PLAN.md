# Plan: the claims pilot

This plan builds the pilot in `SPEC.md` on top of the hello-world skeleton, in six phases. Each phase leaves `npm run check` green and is committed before the next one starts.

When it's done, the backend holds the claims queue in SQLite and enforces the $1,000 sign-off rule. The UnderCover Agent works claims through the backend's API and records each step as it goes. The dashboard shows the queue, each claim in full, the agent's steps while it works, and the agent's instructions, and it lets a handler sign off large payouts.

## Design

### Claim states

| State | Meaning | Label on screen |
| --- | --- | --- |
| `waiting` | In the queue, not started | Waiting |
| `in_progress` | The agent is working on it | In progress |
| `waiting_for_sign_off` | Approved with a payout over $1,000, and the payment is held | Waiting for sign-off |
| `decided` | Approved and within the limit, declined, referred, or signed off | Decided |

The seed data marks every claim `open`, which loads as `waiting`. A claim moves `waiting` → `in_progress` → `decided` or `waiting_for_sign_off` → `decided`.

### Database

- SQLite through Python's built-in `sqlite3`, with no ORM. The file path comes from the environment variable `UNDERCOVER_DB`, and defaults to `undercover.db` at the repo root, which git already ignores.
- Tables: claims, policies, customers, handlers, settings, decisions, payments and steps. Claim items and documents are stored as JSON text.
- The backend creates and seeds the database from `data/` when it starts and the file is missing. `uv run -m backend.seed` rebuilds it from scratch.
- Seeding reads `company.json`, `policies.json`, `customers.json`, `handlers.json`, `claims.json` and `policy_wording.md`. It never reads `data/evals/`.
- The $1,000 limit is read from `payout_approval_limit` in `company.json`, not written into the code.

### API

Every operation has an `operation_id`, a one-line docstring and no optional inputs. The agent's tools are named after the operations they call.

| Operation | Route | What it does |
| --- | --- | --- |
| `health` | `GET /api/health` | Already built |
| `list_claims` | `GET /api/claims` | The queue: id, customer name, type, summary, amount claimed, submitted date, status, decision, payout |
| `get_claim` | `GET /api/claims/{claim_id}` | The claim in full, with its decision, payment and sign-off |
| `get_policy` | `GET /api/policies/{policy_id}` | The policy record |
| `get_claim_history` | `GET /api/customers/{customer_id}/claims` | The customer's earlier claims, without contact details or date of birth |
| `get_instructions` | `GET /api/instructions` | The agent's instructions followed by the policy wording |
| `list_handlers` | `GET /api/handlers` | The claims handlers |
| `start_claim` | `POST /api/claims/{claim_id}/start` | Body `{thread_id}`. Moves a waiting claim to in progress |
| `record_step` | `POST /api/claims/{claim_id}/steps` | Body `{kind, content}`. Adds one step of the agent's work |
| `list_steps` | `GET /api/claims/{claim_id}/steps` | The steps in order, with times |
| `record_decision` | `POST /api/claims/{claim_id}/decision` | Body `{decision, payout, section, reason}` |
| `pay_claim` | `POST /api/claims/{claim_id}/payment` | Body `{amount}`. Pays an approved claim |
| `sign_off_claim` | `POST /api/claims/{claim_id}/sign-off` | Body `{handler_id}`. A handler signs off a held payment, which releases it |

Rules the backend enforces:

- `record_decision` needs a claim in progress (409 otherwise). `decision` is `approve`, `decline` or `refer`. An approval needs a payout above zero. A decline or referral needs a payout of zero. `section` and `reason` can't be empty (422 for each of these). An approval over the limit moves the claim to `waiting_for_sign_off`. Every other decision moves it to `decided`.
- `pay_claim` needs an approved claim (409), an amount equal to the approved payout (422), and no earlier payment (409). If the payout is over the limit and no handler has signed off, it returns 403 with "A payout over $1,000.00 needs a handler's sign-off" and records nothing. The agent can try to pay, but the backend refuses.
- `sign_off_claim` needs a claim waiting for sign-off (409) and a known handler (404) who `can_approve_over_limit` (403). It records the handler's name, pays the approved payout, and moves the claim to `decided`.
- Unknown ids return 404.

### Agent

- Tools: `get_claim`, `get_policy`, `get_claim_history`, `record_decision` and `pay_claim`. The agent has no tool for signing off or for recording steps. Each tool returns the backend's JSON. A refused request goes back to the model as the backend's error message, so the run carries on.
- `run(claim_id, thread_id)` calls `start_claim`, fetches its system prompt from `get_instructions`, then streams the agent with an in-memory checkpointer keyed by the thread id. It records every message as a step as it arrives: each tool call (`tool_call`), each tool result (`tool_result`) and the model's text (`message`).
- The instructions live in `backend/instructions.md`, and the backend serves them together with the policy wording. They tell the agent to read the claim, the policy and the claim history. It then decides using the policy wording alone and works out any payout with section 10. It records one decision with the section it relied on and a reason of two or three sentences. Finally it pays an approved payout, knowing that payouts over $1,000 are held for a handler's sign-off.
- `uv run -m agent CLM-1001` works one claim. `uv run -m agent` works every waiting claim in the queue (phase 6). Each run gets a new thread id.

### Dashboard

- React Router with three pages: the queue (`/`), a claim (`/claims/:claimId`) and the instructions (`/instructions`), plus a header linking to the queue and the instructions.
- It fetches through a typed client in `dashboard/src/api.ts`. The queue and a claim page refresh every two seconds, so a page opened before the agent starts still shows its work. Refreshing stops if the claim doesn't exist.
- Brand from `BRAND.md`: Instrument Sans, Instrument Serif for the tagline, and JetBrains Mono for ids and amounts. Light and dark mode follow the system setting. Panels are rounded with no outline. Money is shown like $1,250.00.
- State colors: Decided in Sea Green, In progress in Marigold, Waiting for sign-off in Coral, Waiting in Cerulean. Decision colors: Approved in Sea Green, Referred in Marigold, Declined in Coral.

### End-to-end tests

Playwright runs its own backend on port 8001, with a fresh database at `e2e/undercover.db`, and its own dashboard on port 5174. The dashboard reads its proxy target from `UNDERCOVER_API`. Neither server is reused, so `npm run e2e` works while `npm run dev` is running. The tests stand in for the agent by calling the API through the dashboard's proxy. Each test works on its own claim, so the tests can run in any order.

### How the criteria are checked

API calls run against `npm run dev` on a freshly seeded database (`uv run -m backend.seed`). Pages are checked in the browser with the Playwright MCP server at `http://localhost:5173`. Tests never call a model. Only the criteria marked "Live" use the real model through OpenRouter.

## Phase 1: The claims database and the read API

Build the database, the seeding, and the read operations `list_claims`, `get_claim`, `get_policy` and `get_claim_history`. Add a pytest check that the OpenAPI schema follows the API rules. Set up the separate end-to-end servers.

- [x] `uv run -m backend.seed` prints `Seeded 25 claims, 50 policies, 49 customers and 3 handlers into undercover.db`
- [x] `curl -s localhost:8000/api/claims` returns 25 claims in id order, all `waiting`. The first is `CLM-1001` for Maya Patel, `trip_delay`, with an amount claimed of 420.0
- [x] `curl -s localhost:8000/api/claims/CLM-1001` returns the story, 3 items, 4 documents, status `waiting` and no decision
- [x] `curl -s localhost:8000/api/policies/POL-2001` returns plan `premium`, no add-ons, and a trip to Rome returning on 2026-06-18
- [x] `curl -s localhost:8000/api/customers/CUS-3001/claims` returns one earlier claim, `CLM-0412`, and no `email`, `phone`, `address` or `date_of_birth`
- [x] `curl -s -o /dev/null -w '%{http_code}' localhost:8000/api/claims/CLM-9999` prints `404`, and the same holds for an unknown policy and customer
- [x] A pytest test reads `/openapi.json` and passes: every operation has an `operation_id` and a one-line description, every parameter is required, and every request body property is required
- [x] After deleting `undercover.db` and starting the backend, `curl -s localhost:8000/api/claims` again returns 25 claims
- [x] pytest uses a temporary database: the modified time of `undercover.db` is the same before and after `uv run pytest`
- [x] `grep -rn evals backend agent dashboard/src` finds nothing
- [x] `npm run e2e` passes while `npm run dev` is running
- [x] `npm run check` passes

## Phase 2: Deciding, paying and signing off

Add `start_claim`, `record_step`, `list_steps`, `record_decision`, `pay_claim`, `list_handlers` and `sign_off_claim`, with the rules above. `get_claim` now includes the thread id, decision, payment and sign-off.

- [x] pytest covers every rule in the design, including each 403, 404, 409 and 422
- [x] `start_claim` on `CLM-1001` returns status `in_progress`, and a second call returns 409
- [x] `record_decision` on a waiting claim returns 409
- [x] `record_step` twice, then `list_steps`, returns both steps in order with times
- [x] An approval with payout 0, a decline with payout 50, a decision of `maybe` and an empty section each return 422
- [x] Approving `CLM-1001` for 420.00 gives status `decided`. `pay_claim` with 420.00 returns 200 and `get_claim` shows the payment. Paying again returns 409
- [x] `pay_claim` with an amount different from the approved payout returns 422 and records nothing
- [x] An approval of exactly 1,000.00 gives `decided` and can be paid without sign-off
- [x] Walked through with curl: an approval of 1,350.00 gives `waiting_for_sign_off`. `pay_claim` with 1,350.00 returns 403 with "A payout over $1,000.00 needs a handler's sign-off", and `get_claim` shows no payment
- [x] `sign_off_claim` with `HND-99` returns 404. On a claim that isn't waiting for sign-off it returns 409. With `HND-01` it returns status `decided` and a payment of 1,350.00 signed off by Dana Whitfield, and `pay_claim` afterwards returns 409
- [x] Declined and referred claims are `decided`, and `pay_claim` on them returns 409
- [x] `curl -s localhost:8000/api/handlers` returns the 3 handlers
- [x] `grep -rn 1000 backend --include=*.py` finds nothing outside `backend/tests/`
- [x] The OpenAPI test from phase 1 passes with the new operations
- [x] `npm run check` passes

## Phase 3: The UnderCover Agent

Write `backend/instructions.md` and add `get_instructions`. Replace the hello-world tool with the five claim tools. Build `run()` so it records steps as they happen. Add `uv run -m agent <claim_id>`.

- [x] `curl -s localhost:8000/api/instructions` returns the instructions followed by the policy wording, including `## 10. How we work out your payment`
- [x] A pytest test checks that the agent's tools are exactly `get_claim`, `get_policy`, `get_claim_history`, `record_decision` and `pay_claim`, each named after a backend operation
- [x] A stub model test checks that the system prompt the model receives is the text from `get_instructions`
- [x] Stub model test, within the limit: the stub calls `get_claim`, `get_policy`, `get_claim_history`, `record_decision` (approve, 420.00) and `pay_claim` (420.00), then replies. The claim is `decided`, paid 420.00, carries the thread id, and has its steps recorded in order: tool calls, tool results and the final message
- [x] Stub model test, over the limit: the stub approves 1,350.00 and calls `pay_claim`. The refusal reaches the model as a tool message that mentions sign-off, the run finishes, and the claim is `waiting_for_sign_off` with no payment
- [x] Stub model tests for a decline and a referral: both claims are `decided` with no payment
- [x] `grep -rn "data/" agent` finds nothing: the agent reads nothing from disk
- [x] Live: on a fresh database with `npm run dev` running, `uv run -m agent CLM-1001` prints a reply of two or three sentences
- [x] Live: `curl -s localhost:8000/api/claims/CLM-1001` then shows `approve`, payout 420.0, a section naming section 3 (Trip Delay), a reason of two or three sentences, and a payment of 420.0
- [x] Live: `curl -s localhost:8000/api/claims/CLM-1001/steps` lists the calls to `get_claim`, `get_policy`, `get_claim_history`, `record_decision` and `pay_claim`, with their results
- [x] `npm run check` passes

## Phase 4: Dashboard: the queue, a claim and the instructions

Replace the health page with the three pages, the header and the brand styling. `e2e/health.spec.ts` gives way to tests of the new pages.

- [x] vitest covers the queue, the claim page, the instructions page and money formatting (`1150` shows as `$1,150.00`) against a stubbed `fetch`
- [x] e2e: the queue lists 25 claims. Clicking `CLM-1001` opens `/claims/CLM-1001` with its story. The header link opens the instructions
- [x] Browser, `/`: 25 rows with id, customer, type, summary, amount claimed, submitted date and status. Status counts show Waiting 25. Rows are in id order
- [x] Browser, `/claims/CLM-1002`: the story, 6 items totalling $1,150.00, 3 documents with their text, the policy (plan, add-ons, purchase date, trip dates, trip cost, travelers) and the customer's earlier claims
- [x] Browser, `/instructions`: the instructions and the policy wording, with no text box, input or edit button in the snapshot
- [x] Browser, `/claims/CLM-9999` shows "Claim not found"
- [x] Browser, with `browser_evaluate`: body text uses Instrument Sans, ids and amounts use JetBrains Mono, and the page background is `#F0F4F5` in light mode and `#04232E` after `browser_emulate_media` switches to dark
- [x] Browser: screenshots of the queue and a claim in light and dark mode show rounded panels with no outlines, no one-edge borders and no gradients
- [x] Browser: `browser_console_messages` shows no errors on any page, apart from the 404 for the missing claim on the not-found page
- [x] `npm run check` passes

## Phase 5: Dashboard: the agent at work, and sign-off

Add the agent's steps to the claim page, the decision panel with payment status, the sign-off form, and the two-second refresh.

- [x] vitest covers the step list, the refresh while a claim is in progress (with fake timers), the decision panel in each state, and the sign-off form, including an error from the backend
- [x] e2e, agent at work: the test starts `CLM-1003` and records steps through the API. Without a reload, the page shows In progress and each step. After the test records an approval and a payment, the page shows Decided, Approved and "Paid $X", again without a reload
- [x] e2e, sign-off: the test starts `CLM-1020` and approves it for 1,350.00 through the API, and a payment attempt returns 403. The page shows Waiting for sign-off. Choosing Dana Whitfield and pressing "Sign off" shows Decided and "Paid $1,350.00, signed off by Dana Whitfield"
- [x] Browser: tool calls show the tool name and its inputs, tool results are folded and open on click, and the agent's messages show in full
- [x] Browser, with `browser_evaluate`: each state and decision label has the background color from the design
- [x] Live, in the browser: on a fresh database, open `/claims/CLM-1001` and run `uv run -m agent CLM-1001`. Snapshots taken during the run show steps appearing while the claim is In progress, and the page ends on Decided with the decision, payout, section and reason
- [x] `npm run check` passes

## Phase 6: Working the queue

Make `uv run -m agent` work every waiting claim in queue order. It prints one line per claim, then a count of each decision. If one claim fails, it reports the error and moves on to the next. Update `docs/STATUS.md` to describe the pilot and how to run it.

- [x] Stub model test: the queue run works each waiting claim once, skips claims that aren't waiting, and prints one line per claim, like `CLM-1001  approve  $420.00`
- [x] Live: on a fresh database with `npm run dev` running, `uv run -m agent` works all 25 claims and prints 25 lines and the counts
- [x] Live: afterwards, `curl -s localhost:8000/api/claims` shows no claim `waiting` or `in_progress`
- [x] Live: every decision has a section and a reason of two or three sentences
- [x] Live: every approval over $1,000 is `waiting_for_sign_off` with no payment. Every other approval is paid exactly its payout. Declines and referrals have a payout of 0 and no payment
- [x] Live, in the browser: the queue shows the counts by state after the run. Signing off one held claim as Priya Raman moves it to Decided and paid
- [x] `docs/STATUS.md` describes what's built, how to seed, run and work the queue, and the decision counts from the live run
- [x] `npm run check` passes

## Not in this plan

- Scoring the agent against the handlers' decisions in `data/evals/`. That comes as its own step, since the process says not to open `data/evals/` unless asked.
- The claims manual, sign-in, real payments and messages to customers, as `SPEC.md` says.
- Starting the agent from the dashboard. The queue is worked from the command line, and the dashboard shows the work as it happens.
