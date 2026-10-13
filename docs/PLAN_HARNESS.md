# Plan: the harness

This plan builds what `docs/HARNESS.md` asks for on top of the finished pilot, in six phases. Each phase leaves `npm run check` green and is committed before the next one starts.

When it's done, one command works the queue. A queue agent plans the run as a to-do list the team can watch on the dashboard, and hands each claim to a fresh claim agent that looks up the sections of the policy wording and the claims manual it needs. The harness catches every failure on a claim, puts the claim back in the queue once, and leaves it for a handler after a second failure. The backend keeps the runs, the to-do lists and the attempts, and it still enforces every rule in `SPEC.md`.

## Design

### How a run works

1. `uv run -m agent --cap 5` first puts back in the queue any claim left in progress by an earlier run that stopped. It then starts a run capped at five claims, or at every waiting claim when no cap is given.
2. The queue agent lists the claims, chooses which to work and in what order, and writes its to-do list.
3. For each claim it calls `work_claim`. The harness starts a claim agent with a new thread and only the claim instructions. The claim agent works the claim and records every step on it. The harness then sends back one line built from the backend's record of the claim: the decision and payout, or what went wrong.
4. The queue agent keeps its to-do list up to date as the reports come back, and tries again any claim that went back in the queue.
5. When the queue agent replies without calling a tool, the harness checks for waiting claims it has missed within the cap: claims it started that went back in the queue, and any waiting claim while the run is under its cap. If there are any, the harness names them and lets the agent carry on. It does this at most twice.
6. The agent's last reply is the summary for the handlers. The harness records it on the run with `finish_run` and prints it.

We build each piece into our own agent with `create_agent`. The to-do list is our own `write_todos` tool, stored in the backend so the dashboard can show it, and the subagent is our own `work_claim` tool. Neither Deep Agents nor the Claude Agent SDK is used in `agent/` or `backend/`.

### Claim states

| State | Meaning | Label on screen | Color |
| --- | --- | --- | --- |
| `waiting` | In the queue: not started, or back after a failed attempt | Waiting | Cerulean |
| `in_progress` | A claim agent is working on it | In progress | Marigold |
| `waiting_for_sign_off` | Approved with a payout over $1,000, and the payment is held | Waiting for sign-off | Coral |
| `decided` | Approved and within the limit, declined, referred, or signed off | Decided | Sea Green |
| `left_for_handler` | The agent failed on it twice, so a handler works it by hand | Left for a handler | Raspberry |

Each claim counts its `attempts`, and `start_claim` adds one. A failed attempt moves a claim from `in_progress` back to `waiting`, or to `left_for_handler` when it was the second attempt. The limit of two attempts is a named constant in the backend.

No claim is decided or paid twice. `record_decision` still needs a claim in progress, a claim with a decision never goes back in the queue, and `pay_claim` still refuses a second payment.

### Runs and the to-do list

- A run has an id, a cap, a status (`running` or `finished`), start and finish times, and the summary. One run works at a time.
- A run's to-do list is a list of items in order, each with its text and a status: `to_do`, `in_progress`, `done` or `left_for_handler`. On screen they are To do (Cerulean), In progress (Marigold), Done (Sea Green) and Left for a handler (Raspberry).
- `write_todos` replaces the whole list each time, as LangChain's to-do middleware does. The queue page shows the list of the latest run.

### The documents

- Seeding stores `data/claims_manual.md` beside the policy wording.
- The backend splits both documents into sections at their numbered headings, such as `## 9. Repeat claims`: 12 sections in the wording and 14 in the manual. A section is named by its document (`policy_wording` or `claims_manual`) and its number.
- The claim instructions end with the contents of both documents: the numbers and titles of the sections, without their text. The claim agent reads a section with `read_section`. It finds one with `search_documents`, which returns each section whose title or text contains a word or phrase, ignoring case, with the paragraphs that contain it.
- After each section it reads, the harness records a `reading` step such as `Claims manual, section 9: Repeat claims`, so the claim page can show what the agent read.

### Database

- `settings` gains `claims_manual`.
- `claims` gains `attempts`, starting at 0.
- New tables: `runs`, and `todos` with the run id, the position, the text and the status.
- Steps gain two kinds: `reading`, and `error` for a failed attempt.

### API

New and changed operations. The others are as in `docs/PLAN.md`. Every operation keeps an `operation_id`, a one-line docstring and no optional inputs.

| Operation | Route | What it does |
| --- | --- | --- |
| `get_claim` | `GET /api/claims/{claim_id}` | Now includes `attempts` |
| `start_claim` | `POST /api/claims/{claim_id}/start` | Also adds one to `attempts` |
| `fail_claim` | `POST /api/claims/{claim_id}/failure` | Body `{reason}`. Records the reason as an `error` step, then puts the claim back in the queue, or leaves it for a handler after its second attempt |
| `search_documents` | `GET /api/documents/search?query=` | The sections of the wording and the manual that contain the query, with the paragraphs that contain it |
| `read_section` | `GET /api/documents/{document}/sections/{number}` | One section in full: document, number, title and text |
| `get_instructions` | `GET /api/instructions` | `{queue, claim}`: the queue agent's instructions, and the claim agent's followed by the contents of both documents |
| `start_run` | `POST /api/runs` | Body `{cap}`. Starts a run with an empty to-do list |
| `get_latest_run` | `GET /api/runs/latest` | The newest run with its to-do list, or `null` before the first run |
| `write_todos` | `PUT /api/runs/{run_id}/todos` | Body `{todos: [{content, status}]}`. Replaces the run's to-do list |
| `finish_run` | `POST /api/runs/{run_id}/finish` | Body `{summary}`. Finishes the run |

Rules the backend enforces:

- `fail_claim` needs a claim in progress (409) and a reason (422).
- `read_section` returns 404 for a number the document doesn't have and 422 for any other document.
- `search_documents` needs a query (422) and returns an empty list when nothing matches.
- `start_run` needs a cap of at least 1 (422).
- `write_todos` and `finish_run` need a running run (409). Each item needs text and one of the four statuses, and a summary can't be empty (422).
- Unknown ids return 404.

### Agent

- **Model.** `deepseek/deepseek-v4.1-flash` with low reasoning effort by default, or the model in `MODEL_NAME`. Every model call has a 120 second timeout and up to 5 retries, which deal with most timeouts and provider errors before they reach a claim.
- **The claim agent.** `work_claim(claim_id)` starts the claim with a new thread id, fetches the `claim` instructions and runs `create_agent` with seven tools: `get_claim`, `get_policy`, `get_claim_history`, `search_documents`, `read_section`, `record_decision` and `pay_claim`. It records the steps as the pilot does, plus the reading steps. A limit of 60 steps (LangGraph's recursion limit) makes a claim agent that goes round in circles fail instead of running on.
- **Failures.** `work_claim` is the one place that catches every exception, whether it comes from the model provider, a tool or the step limit. When the work fails, or the agent finishes without recording a decision, and the claim is still in progress, the harness calls `fail_claim` with the error. A claim decided before the failure keeps its decision and isn't tried again. If `start_claim` refuses, nothing is recorded.
- **The report.** Built from the backend's record of the claim after the work, never from the model:
  - `CLM-1001  approve  $420.00`
  - `CLM-1002  approve  $1,350.00, waiting for sign-off`
  - `CLM-1004  failed: 503: The model is unavailable, back in the queue`
  - `CLM-1004  failed: The agent finished without recording a decision, left for a handler`
  - `CLM-1001  not started: 409: Claim CLM-1001 is not waiting`
  - An approval within the limit that the agent didn't pay ends `, not paid`.
- **The queue agent.** `run_queue(cap)` runs `create_agent` with three tools: `list_claims`, `write_todos` and `work_claim`. The `work_claim` tool hands the claim to a new claim agent, prints the report and returns it. It refuses a new claim once the run has started as many claims as its cap, and says so, naming the cap and the claims started; trying a claim again doesn't count against the cap. The run id is the queue agent's thread id, and its first message says how many claims the run can work. If the queue agent itself fails, the harness finishes the run with "The run stopped: " and the error as its summary, then raises the error.
- **Command line.** `uv run -m agent` works the whole queue and `uv run -m agent --cap 5` caps the run at five claims. `uv run -m agent CLM-1001` works one claim with the claim agent alone, with no run, and prints its report. When no claim is waiting, a queue run prints "No claims are waiting" and starts no run.
- Tests give the queue agent and the claim agent their own stub models.

### Instructions

Both are written from the policy wording and the claims manual, never from `data/evals/`. They replace `backend/instructions.md` with `backend/instructions/queue.md` and `backend/instructions/claim.md`.

- **Running the queue.** You run the queue and never decide a claim yourself. List the claims and choose the waiting ones to work, up to the cap, oldest submitted first. Write a to-do list with one item per claim, naming its id, plus an item to check for missed claims and one for the summary. Mark an item in progress before you hand its claim over, and done or left for a handler when the report comes back. Try again later any claim whose report says it's back in the queue. Before you finish, list the claims again and work any you missed within the cap. Finish with a short summary for the handlers: how many claims of each decision, the payouts waiting for sign-off, and the claims left for a handler with what went wrong.
- **Working a claim.** The pilot's instructions, reworked. The wording comes first and the manual says how to read it. Work the claim in the order of section 4 of the manual. Always read the plan table (section 1 of the wording), the benefit's section, the general exclusions (9) and how the payment is worked out (10), and in the manual the required documents (5), working out the payout (6) and repeat claims (9). Search for anything particular to the claim, such as an animal, a missing receipt, an add-on or a sport, and read what the search finds. The reasons to refer now include the manual's, such as a third claim within 12 months or documents that contradict the story. The `section` of a decision names the sections relied on, from the wording and the manual.

### Dashboard

- **The queue** gains a tile for Left for a handler. Above the claims, a panel shows the latest run: when it started, its cap, Running or Finished, the to-do list with each item's status, and the summary once the run is finished. A claim id in an item links to the claim. Before the first run it says "No run yet". It refreshes every two seconds with the rest of the page.
- **A claim.** The decision panel says when a claim is back in the queue after a failed attempt, and when it has been left for a handler after two. The Agent at work panel starts with the sections the agent read, each listed once, and then the steps. A reading step shows "Read" and the section, and an error step shows "Failed" and the reason in Raspberry.
- **The instructions** show two panels, "Running the queue" and "Working a claim", read only.

### End-to-end tests

As in the pilot. `e2e/run.spec.ts` stands in for the agent through the API: it starts a run, writes and updates the to-do list, and fails a claim twice, while the tests watch the pages update without a reload. It uses claims no other test touches.

### How the criteria are checked

As in `docs/PLAN.md`: API calls run against `npm run dev` on a freshly seeded database, and pages are checked in the browser with the Playwright MCP server at `http://localhost:5173`. Tests never call a model. Only the criteria marked "Live" use the real model, on the default model through OpenRouter. Every live run comes straight after `uv run -m backend.seed` and works at most five claims.

## Phase 1: Looking up the wording and the manual

Seed the manual, add `search_documents` and `read_section`, and write the two sets of instructions. `get_instructions` returns both, and the claim instructions carry the contents of the documents in place of the whole wording. Give the agent the two lookup tools and the reading step, and switch the default model. The instructions page shows both sets. Update `docs/SPEC.md` so the manual is in scope.

- [x] `curl -s localhost:8000/api/documents/claims_manual/sections/9` returns number 9, title "Repeat claims", and text that starts "Before deciding any claim, check the customer's claim history"
- [x] `curl -s localhost:8000/api/documents/policy_wording/sections/3` returns "Trip Delay" with its two paragraphs and nothing from section 4
- [x] `read_section` returns 404 for section 13 of the wording and section 15 of the manual, and 422 for a document called `handbook`
- [x] `curl -s "localhost:8000/api/documents/search?query=wild%20animal"` returns one section, section 7 of the manual, "Interpretation notes", with the paragraph that begins "**Wild animals.**"
- [x] A search for `GIRAFFE` also finds section 7 of the manual. A search for `zeppelin` returns `[]`, and an empty query returns 422
- [x] pytest covers splitting the documents (12 sections in the wording and 14 in the manual, with their numbers and titles), reading, searching, and each 404 and 422
- [x] `curl -s localhost:8000/api/instructions` returns `queue` and `claim`. `claim` ends with the contents of both documents, including "3. Trip Delay" and "9. Repeat claims", and holds none of their text: no "Unattended means out of your sight" and no "Monkeys, gulls, bears, giraffes"
- [x] A pytest test checks that the claim agent's tools are exactly `get_claim`, `get_policy`, `get_claim_history`, `search_documents`, `read_section`, `record_decision` and `pay_claim`, each named after a backend operation
- [x] Stub model test: the system prompt is the `claim` text. The stub reads section 9 of the manual, and the steps show its `tool_call`, its `tool_result`, then a `reading` step "Claims manual, section 9: Repeat claims". A read of section 15 goes back to the model as a refusal and records no reading step
- [x] `test_model_name`: the default is `deepseek/deepseek-v4.1-flash` with low reasoning effort, a 120 second timeout and 5 retries, and `MODEL_NAME=openrouter/free` overrides it
- [x] Browser, `/instructions`: panels headed "Running the queue" and "Working a claim", with the contents at the end of the second, and no text box, input or edit button in the snapshot
- [x] `docs/SPEC.md`: decisions follow the wording and the manual, and the manual is no longer under "Not for now"
- [x] `grep -rn evals backend agent dashboard/src` finds nothing, and `grep -rlnE "deepagents|claude_agent_sdk" agent backend` finds nothing
- [x] Live: after reseeding and with `npm run dev` running, `uv run -m agent CLM-1001` decides the claim. Its steps show `read_section` for section 3 of the wording and for at least one section of the manual, each followed by its reading step
- [x] `npm run check` passes

## Phase 2: Runs, to-do lists and attempts in the backend

Add `attempts`, the `left_for_handler` state and `fail_claim`, then the runs and their to-do lists: `start_run`, `get_latest_run`, `write_todos` and `finish_run`. The dashboard learns the new state.

- [x] pytest covers every new rule in the design, including each 404, 409 and 422
- [x] Walked through with curl: `start_claim` on `CLM-1004` gives attempts 1. `fail_claim` with "The model timed out" puts it back to `waiting` with attempts 1, and its last step is an `error` step with that reason
- [x] Starting and failing it again leaves it `left_for_handler` with attempts 2. `start_claim` then returns 409, and `list_claims` shows it as `left_for_handler`
- [x] `fail_claim` on a waiting claim, a decided claim and a claim waiting for sign-off each return 409 and change nothing
- [x] On a fresh database, `curl -s localhost:8000/api/runs/latest` prints `null`
- [x] `start_run` with cap 5 returns a running run with cap 5, a start time, no summary and an empty to-do list, and `get_latest_run` then returns it. A cap of 0 returns 422
- [x] `write_todos` with two items, then with three, leaves exactly the three, in order. A status of `blocked` returns 422, an item with empty text returns 422, and an unknown run returns 404
- [x] `finish_run` with a summary gives `finished`, a finish time and the summary. `write_todos` and `finish_run` on it then return 409. A second `start_run` becomes the latest run
- [x] The OpenAPI test from the pilot passes with the new operations
- [x] vitest: the queue shows a Left for a handler tile and chip
- [x] `npm run check` passes

## Phase 3: A fresh claim agent for each claim

Turn `run()` into `work_claim(claim_id)`: a new thread for every attempt, the step limit, the failure handling and the one-line report. `uv run -m agent CLM-1001` prints the report.

- [x] Stub model test, within the limit: `work_claim("CLM-1001")` returns `CLM-1001  approve  $420.00`, and the claim is decided and paid, with its steps under a new thread id
- [x] Stub model test, over the limit: `CLM-1002  approve  $1,350.00, waiting for sign-off`, with no payment
- [x] A stub that raises a provider error on its second call: the report ends `back in the queue`, and the claim is `waiting` with attempts 1 and the error as its last step
- [x] The same failure a second time: the report ends `left for a handler`, and the claim is `left_for_handler`
- [x] A stub that finishes without recording a decision: `failed: The agent finished without recording a decision, back in the queue`
- [x] A stub that calls `get_claim` over and over stops at the step limit, and the claim goes back in the queue
- [x] A stub that raises after `record_decision`: the report gives the decision, and the claim keeps it with no `error` step and isn't put back in the queue
- [x] `work_claim` on a decided claim returns `not started: 409: ...` and changes nothing: no step and no attempt
- [x] A clean start for each claim: working two claims in a row, the claim model's first prompt each time holds only the claim instructions and one message naming the claim
- [x] `uv run -m agent CLM-1001` prints the report (tested with `work_claim` stubbed out)
- [x] Live: after reseeding, `uv run -m agent CLM-1001` prints one report line, and `curl -s localhost:8000/api/claims/CLM-1001` shows the same decision and payout, with a section and a reason of two or three sentences
- [x] `npm run check` passes

## Phase 4: The queue agent

Replace `work_queue()` with `run_queue(cap)`: the recovery at the start, the run, the three tools, the cap, the check for missed claims and the summary. Add `--cap` to the command line.

- [x] A pytest test checks that the queue agent's tools are exactly `list_claims`, `write_todos` and `work_claim`, and that the first two are named after backend operations
- [x] Stub model test, a whole run: with three claims waiting, the queue stub lists the claims, writes three items, marks each in progress and then done around its `work_claim`, and finishes with a summary. All three claims are decided, and the latest run is `finished` with that summary and every item `done`. The queue agent's system prompt is the `queue` text, and its first message says the run can work 3 claims
- [x] Cap: with four claims waiting and a cap of 2, the stub's `work_claim` on a third claim is refused with a message that names the cap. Two claims are worked, and two stay `waiting` with 0 attempts
- [x] A failed claim doesn't stop the run: when the claim model raises on the first of three claims, the other two are still decided and the run finishes
- [x] Tried again: a claim that fails once goes back in the queue. The stub calls `work_claim` on it again, which the cap allows, and it's decided. Its steps show both attempts with the error between them
- [x] Left for a handler: a claim that fails on both attempts is `left_for_handler`, its report says so, and the run finishes with the other claims decided
- [x] Missed claims: when the stub tries to finish while a claim it started is back in the queue, the harness replies naming that claim. The stub works it, and then the run finishes. A stub that ignores the reminders gets two, and then the run finishes
- [x] Recovery: a claim left `in_progress` before the run starts is put back in the queue with the error "The run stopped before this claim was finished", and the run can work it
- [x] When the queue model raises, the run finishes with a summary that starts "The run stopped:", and no claim is left in progress
- [x] With no claim waiting, `run_queue` prints "No claims are waiting" and starts no run
- [x] Command line: `uv run -m agent` caps the run at every waiting claim, `--cap 5` caps it at five, and `CLM-1001` works one claim (tested with the run stubbed out)
- [x] Live: after reseeding and with `npm run dev` running, `uv run -m agent --cap 5` prints a report line for each claim it works, then the summary
- [x] Live: afterwards, `curl -s localhost:8000/api/claims` shows exactly 5 claims that aren't `waiting`, and none `in_progress`. `curl -s localhost:8000/api/runs/latest` shows the run `finished`, with the summary and every claim item `done` or `left_for_handler`
- [x] Live: every approval over $1,000 is `waiting_for_sign_off` with no payment, every other approval is paid exactly its payout, and each claim worked has at least one reading step
- [x] `npm run check` passes

## Phase 5: The dashboard: the to-do list and what the agent read

Add the run panel to the queue page, the new messages to the decision panel, and the sections read, reading steps and failed steps to the claim page.

- [x] vitest covers the run panel before the first run, while running (each item's status label) and finished (with the summary); a claim id in an item linking to the claim; the run panel refreshing, with fake timers; the decision panel for a claim back in the queue and for one left for a handler; reading and failed steps; and the sections read, each listed once
- [x] e2e, the to-do list: the test starts a run capped at 2 and writes two items To do, naming `CLM-1013` and `CLM-1014`. Without a reload, the queue page shows both To do. The test marks the first In progress, then marks it Done and the second In progress, and the page follows each change. After the test finishes the run with a summary, the page shows Finished and the summary, and the `CLM-1013` link in the first item opens that claim
- [x] e2e, a claim left for a handler: the test starts `CLM-1016`, records a reading step and fails the claim, and the claim page says it's back in the queue. After the test starts and fails it again, the page shows Left for a handler, the section under the sections read, and two Failed steps with their reasons, all without a reload
- [x] Browser, with a run driven by curl, and `browser_evaluate`: each to-do status and the Left for a handler state have the background color from the design
- [x] Browser: screenshots of the queue with a run and of a claim left for a handler, in light and dark mode, show rounded panels with no outlines, no one-edge borders and no gradients
- [x] Browser, on a claim with steps recorded by curl: a reading step shows "Read" and the section, and a failed step shows "Failed" and its reason in Raspberry
- [x] Browser: `browser_console_messages` shows no errors on any page
- [x] `npm run check` passes

## Phase 6: A trial on five claims

Watch a capped run on the dashboard from start to finish, and bring `docs/SPEC.md`, `docs/TECH_STACK.md` and `docs/STATUS.md` up to date.

- [x] Live, in the browser: after reseeding, with `/` open, start `uv run -m agent --cap 5`. Snapshots taken during the run show the to-do list appearing, items moving from To do to In progress to Done, and claims moving from In progress to Decided or Waiting for sign-off, all without a reload. The page ends with the run Finished and its summary
- [x] Live, in the browser: a claim page opened during the run shows its steps appearing and its sections read, including at least one section of the manual
- [x] Live: afterwards the queue shows Waiting 20 and In progress 0
- [x] `docs/SPEC.md` describes the run, the to-do list, a fresh claim agent for each claim, the retries, claims left for a handler, and the sections read
- [x] `docs/TECH_STACK.md` names the new default model and the agent's two entry points, `run_queue(cap)` and `work_claim(claim_id)`
- [x] `docs/STATUS.md` describes what's built, how to work the whole queue, a capped run and one claim, and the time and decisions of the live run
- [x] `npm run check` passes

## Not in this plan

- Scoring the agent against the handlers' decisions in `data/evals/`, which comes as its own step.
- A way for a handler to decide a claim left for a handler, or put it back in the queue, from the dashboard. Reseeding puts every claim back.
- Starting a run from the dashboard.
- Working claims in parallel, or more than one run at a time.
- Summarizing the queue agent's conversation as it grows. Each claim adds a one-line report and an update to the to-do list, so a run of 25 claims stays well within the model's context.
- Sign-in, real payments and messages to customers, as `SPEC.md` says.
