# Plan: the swarm and the scoreboard

This plan builds what `docs/SWARM.md` asks for on top of durable state, in six phases. Each phase leaves `npm run check` green and is committed before the next one starts.

SIDENOTE: For consistency with the course, please read `labs/week2day4.ipynb` and build the dispatcher in the same style as the lab. Where the lab and this brief differ, follow the brief. Include this sidenote in your plan too.

When it's done, a handler starts a dispatch from the queue page with up to 25 claim agents at once. A dispatcher with no model, a LangGraph graph like the lab's, carries on every claim left in progress and works every waiting claim, oldest submitted first. Each claim keeps its own thread, its saved progress, its pause for a sign-off and its recovery after a restart. A rate limit or a timeout waits and carries on, any other failure gets one more try in the same dispatch, and the dispatch's summary is built from the backend's records. The tokens and cost of every model call, and the time the agent spends on every claim, are recorded with their run. A new Scoreboard page starts evaluations on copies of the labelled claims and scores them with the lab's measures. The queue agent and its to-do list are gone, and the agent runs on GPT-6 Luna by default.

## Design

### Modules

The backend:

- `database.py`: the tables, the engine and seeding. It gains `model_calls`, `work_times`, `run_claims`, `held_out_claims` and `handler_decisions`. `runs` is reworked for dispatches and evaluations, `claims` gains `evaluation_id` and `copy_of`, and `todos` goes. Seeding now reads `data/evals/` too, the only module that does.
- `scoring.py` (new): the lab's measures as plain functions of the agent's answers and the handlers' decisions: whether an answer is right, what a mistake costs, and an evaluation's measures. It uses `models.py` and nothing else, like `payout.py`.
- `agent_service.py`: the backend's three calls to the agent's service, `resume_claim`, `start_dispatch` and `start_evaluation`, with the service's address written once.
- `main.py`: the app, its lifespan, and the claim, document, handler and instructions operations, including the new `record_model_call` and `record_work_time`, which belong to a claim. It includes the runs router with `include_router`. It keeps its own helpers, such as `find_claim`, `dollars` and `add_step`. The recording operations check that a run exists with a query of their own, since they need nothing else about it.
- `runs.py` (new): a FastAPI `APIRouter` holding every operation on runs, dispatches and evaluations: the operations under `/api/runs`, `/api/dispatches` and `/api/evaluations` in the API table below, with their own helpers, such as finding a run, building a dispatch's summary and making an evaluation's copies. It uses `scoring` for the scoreboard and `agent_service` to start runs. It imports nothing from `main.py`.
- `dependencies.py` (new): the `Database` dependency both routers share, one transaction per request, committed before the response is sent. It moves from `main.py` unchanged, following the layout in FastAPI's guide to bigger applications.
- `views.py` (new): `to_claim()` and `to_summary()`, which build a claim in full and its line in the queue from a `claim_view` row. They move from `main.py`, since a run's claims show the queue's line too.
- `database.py` also takes `now()` from `main.py`, the time stamp every record carries, since both routers write records.
- `lookups.py` (new, added in the review of the whole change): finding a run, and the messages for a run or a claim not found, which both routers need. The claim and run statuses, decisions, run kinds and sets are `StrEnum`s in `models.py`, as the agent's `Status` is.
- `instructions/queue.md` goes. `get_instructions` serves the claim instructions alone.

Inside the backend, `main` uses `runs`, `dependencies`, `views`, `database`, `documents`, `payout`, `agent_service` and `models`, and `runs` uses `dependencies`, `views`, `database`, `scoring`, `agent_service` and `models`. Neither uses the other's helpers.

The agent, in five parts:

- `api.py`: the backend's API, one function per operation the agent uses. It gains `record_model_call`, `record_work_time`, `create_dispatch`, `create_evaluation`, `record_run_claims` and `stop_runs`, and `finish_run` loses its summary. It loses `start_run`, `write_todos`, `get_latest_run` and the `Todo` type. It has no function for the scoreboard's operations, so the agent never reads the handlers' decisions. Its client retries a refused connection a few times (httpx's `HTTPTransport(retries=5)`, about 7 seconds in all), because the service now calls the backend as it starts, and `npm run dev` starts both at once.
- `tools.py`: the claim agent's seven tools, unchanged, with `ClaimContext`, which gains `run_id`, and `ClaimState`. It loses `list_claims`, `write_todos`, `work_claim`, `QUEUE_TOOLS` and `RunContext`.
- `harness.py`: builds and runs the claim agent: `model()`, `checkpoint_pool()`, `claim_graphs()`, `claim_graph()`, `work_claim()`, `carry_on()` and the new `work_in_run()`. It loses the queue agent, its middleware, `run_queue`, `work_queue`, `missed`, `waiting`, `finish_stopped_run` and `carry_on_stopped`.
- `dispatcher.py` (new): the dispatcher graph, its state and context, and `work_run()`, which works one dispatch or evaluation. It uses `harness.work_in_run` and `harness.TRANSIENT` for the claim agent, and `api` for the run's claims and its finish.
- `service.py`: the agent's service, with `health`, `resume_claim`, and the new `start_dispatch` and `start_evaluation`. It hands runs to `dispatcher` and resumes to `harness`.
- `__main__.py`: `uv run -m agent CLM-1001` works one claim with no run. The queue run and `--cap` go.
- `console.py`: sets up the report lines, as today, and gains `describe()`, moved from the harness, which says in one line what went wrong, since the dispatcher's report lines need it too.

Inside the agent, `service` uses `dispatcher`, `harness` and `api`; `__main__` uses `harness` and `api`; `dispatcher` uses `harness` and `api`; `harness` uses `tools` and `api`; and `tools` uses `api`. There are no cycles. The dispatcher reaches the claim agent only through `harness.work_in_run`, so later it can be pointed at the agent in the cloud by changing that one function.

The dashboard gains a dispatch panel in place of the run panel, a Scoreboard page and an evaluation page, and loses the to-do list. The end-to-end stand-in for the agent's service also accepts starts.

### How a dispatch works

1. On the queue page a handler chooses N, from 1 to 25 with 3 to start with, and presses Start a dispatch. The dashboard calls the backend's `start_dispatch`, which asks the agent's service through `agent_service.py` and writes nothing.
2. The service refuses with a 409 while a dispatch or an evaluation is running. Otherwise it answers 202 at once, and in a background task creates the dispatch through the backend's `create_dispatch`, with N, the model and its reasoning effort, and hands it to `dispatcher.work_run`.
3. The dispatcher's `list_claims` node lists the queue's claims in progress and waiting, oldest submitted first, leaving out any claim the service is resuming after a sign-off. It records them with the dispatch through `record_run_claims`, and `fan_out` sends each one to `work_claim`.
4. LangGraph runs up to N `work_claim` tasks at once. Each calls `harness.work_in_run` with the claim's id and the run's id, which builds a claim graph with a checkpointer of its own, carries the claim on if it is in progress or starts it if it is waiting, and returns the claim's report line.
5. When every claim has been handed over, `finish_run` finishes the dispatch, and the backend builds its summary from its records.
6. The queue page shows the dispatch's claims and where each stands, refreshing every two seconds, then the summary, the model cost and the time.

An evaluation works the same way, on copies of a labelled set's claims, which `create_evaluation` makes.

### The dispatcher

The state, `Dispatch`, as in the lab:

- `claims`: the ids of the claims to work.
- `reports`: one report line per claim, with `operator.add` as its reducer, so the lines of claims worked at once are added together.

The context, `DispatchContext`, passed with `context=`:

- `run`: the dispatch or evaluation as the backend created it.
- `new_graph`: builds a claim graph with a checkpointer of its own.
- `resuming`: the claims the service is resuming after a sign-off, which a dispatch skips.

The nodes and edges:

| From | To | How |
| --- | --- | --- |
| START | `list_claims` | always |
| `list_claims` | `work_claim` | `fan_out` returns one `Send("work_claim", claim_id)` per claim |
| `list_claims` | `finish_run` | `fan_out` returns `finish_run` when there are no claims |
| `work_claim` | `finish_run` | always; LangGraph runs it once, after every `work_claim` task |
| `finish_run` | END | always |

- `list_claims`: for a dispatch, the queue's claims in progress or waiting, by submission date then id, less any in `resuming`, recorded with `record_run_claims`. For an evaluation, the run's copies in the same order, which the backend recorded when it made them.
- `work_claim`: has a `RetryPolicy` (below). It calls `harness.work_in_run(claim_id, run_id, new_graph)` and adds the report line. If the claim is back in the queue afterwards, because it failed with an error on its first attempt, it calls `work_in_run` once more, which starts a new attempt; a claim that fails again is left for a handler by the backend, as today.
- `finish_run`: calls `finish_run` for the run.

`work_run(run, work, resuming)` invokes the compiled graph with `max_concurrency` set to the run's N and returns the report lines. `work` is `harness.work_in_run` with its `new_graph` bound by the service, so the dispatcher sees only a function of the claim's id and the run's id. The dispatcher has no checkpointer: each claim saves its own progress, and the next dispatch finishes what a stopped one left.

### Following the lab

As in the lab: a `TypedDict` state with `operator.add` on the results; a `list_claims` node; `fan_out`, a conditional edge returning one `Send` per claim, with the nodes it can reach listed so the graph draws; a `work_claim` node with a `RetryPolicy`; `max_concurrency` in the config as the cap on claim agents at once; no model anywhere in the graph; a node after `work_claim` that LangGraph runs once after every claim agent has finished, as in the lab's challenge; the lab's measures, `WRONGFUL_DECLINE = 1500` and `NEEDLESS_REFERRAL = 50`; the cost from OpenRouter's `usage.cost` on each reply (`response_metadata["token_usage"]["cost"]`); GPT-6 Luna with low reasoning effort; and the `tiny` subsets.

Where the brief differs, we follow the brief:

- Each claim keeps its own thread and checkpointer, as on Day 3, and the dispatcher only starts claims, so an `interrupt()` pauses one claim and never the dispatch. The state holds report lines, and the records live in the backend.
- The `RetryPolicy` retries only `ModelRateLimitError` and `ModelTimeoutError`, and a retry carries the claim on from its last saved step instead of working it again from the start.
- A claim still failing after its retries stays in progress for the next dispatch instead of stopping the run, and a claim that fails with any other error gets one more try in the same dispatch.
- An evaluation works copies of the claims in the backend, in place of the lab's in-memory `recorded`.
- Langfuse keeps a session per claim and tags each claim's trace with the run's id, in place of one trace for the whole run.
- The backend scores an evaluation from its own records, in place of pandas. Scores aren't sent to Langfuse.

### Where LangGraph falls short of the brief

The brief has the worker's `error_handler` leave a claim in progress once its retries run out. In LangGraph 1.2.12, the newest release, that works for a worker running alone but not beside others. A scratch graph with three workers fanned out by `Send` showed it: the handlers ran and so did the node after the workers, and then `invoke` raised the handled error anyway. The sync `BackgroundExecutor` re-raises a failed task's error when it closes, and doesn't check the runner's `SKIP_RERAISE_SET`, which marks the errors a handler took. `ainvoke` raises the same way. With one claim the handler works, so it would pass a test with one claim and fail in a real dispatch.

So `work_claim` keeps the `RetryPolicy` for the waits and the tries, and leaves the claim itself on its last try:

- `RETRY = RetryPolicy(max_attempts=3, initial_interval=10, retry_on=harness.TRANSIENT)`, so a claim waits about 10 seconds, then about 20, on top of the model client's own 5 retries.
- `work_claim` catches any exception from `work_in_run`. A transient error before the last try (`runtime.execution_info.node_attempt < RETRY.max_attempts`) is raised again, and the `RetryPolicy` waits and runs `work_claim` again, which carries the claim on. On the last try, and for any other error, it reports `CLM-1004  left for the next dispatch: ModelRateLimitError: ...` and logs it. The claim stays as it is, which for a transient error is in progress, and no error stops the dispatch.
- The scratch graph showed this works with workers failing beside each other: three tries for a rate-limited claim, one for any other error, a timeout that clears on its second try finishing normally, and `finish_run` running once.
- A test records LangGraph's behavior with `error_handler` and two workers, so we notice when a release fixes it and can move to `error_handler` as the brief intends.

The tests run the `RetryPolicy` without its waits, so `npm run check` never sleeps through the backoff. LangGraph waits `initial_interval × backoff_factor^(n-1)` before each retry, plus up to a second more when `jitter` is on (`langgraph/pregel/_retry.py`). An autouse fixture in `agent/tests/conftest.py` replaces `dispatcher.RETRY` with `RETRY._replace(initial_interval=0, jitter=False)`, which keeps its three attempts and its `retry_on`, so every wait is zero and the tests still see three tries. The dispatcher reads `RETRY` when it builds the graph and when `work_claim` checks for its last try, never when it's imported, so the fixture reaches both. The fixture keeps the real policy for the one test that checks it.

### The claim agent in a run

The harness:

- `TRANSIENT = (ModelRateLimitError, ModelTimeoutError)` from `langchain_core.exceptions`, named once: the model errors that pass with time. `ChatOpenAI` raises its own subclasses of both.
- `work_claim(claim_id, run_id, graph)` starts a new attempt and `carry_on(claim_id, run_id, graph)` carries a claim on, as today, with the run's id, or `None` when there's no run.
- `work_in_run(claim_id, run_id, new_graph)` is the one function the dispatcher calls. It builds a claim graph with `new_graph()`, carries the claim on if it is in progress or starts it if it is waiting, and returns the report line. When the claim is an evaluation's copy held for sign-off, it deletes the claim's thread from the checkpointer with `delete_thread`.
- The shared function that invokes the claim graph passes `ClaimContext(claim_id, run_id)`. It catches any exception and settles the claim, as today, except a `TRANSIENT` error, which it raises again without settling, so the claim stays in progress with its progress saved. That also applies to `uv run -m agent CLM-1001`, where the error ends the command and the claim waits in progress for the next dispatch.
- It measures each invoke, one spell of work, with `time.monotonic()`, and records it with `record_work_time` once the invoke ends, however it ends. A claim that pauses for a sign-off ends its spell at the pause, and the carry-on after the sign-off is a spell of its own, so the wait is never counted.

The claim graph's `agent` node, after each model call, records the reply's `prompt_tokens`, `completion_tokens` and `cost` from `response_metadata["token_usage"]` with `record_model_call`, with the run's id from `ClaimContext`. Nothing else in the claim graph, its tools or its instructions changes.

### The checkpointer and connections

- `checkpoint_pool()` replaces `checkpointer()`. It opens the process's `ConnectionPool` with at most 4 connections, the same settings as today and `timeout=120`, so a claim agent waits up to two minutes for a connection where psycopg's default would fail after 30 seconds. It creates the schema and runs the saver's `setup()` once, and yields the pool.
- `claim_graphs(llm, pool)` returns a function that builds a claim graph with a `PostgresSaver` of its own on that pool. `PostgresSaver` holds a lock around every read and write (`self.lock` in its `_cursor`), so one saver shared by 25 claim agents would make them take turns.
- Each claim run gets its own graph and saver: every `work_in_run`, every `resume_claim` and `uv run -m agent CLM-1001`. Building a graph also reads the claim instructions from the backend, so a change to them reaches the next claim.
- The backend's engine also waits up to two minutes for a connection (`pool_timeout=120`), with its pool of 4 and no overflow, since 25 claim agents send it requests at once.
- At most 4 connections in each process: the backend's 4 and the service's 4, plus `pg_net`'s 1, makes 9. A `uv run -m agent CLM-1001` beside them adds 4, making 13, so it shouldn't run during a dispatch.

### Cost and time

- `model_calls`: one row per model call: the claim, its thread, the run or none, the input and output tokens, the cost in US dollars, and the time.
- `work_times`: one row per spell of work on a claim: the claim, its thread, the run or none, when it started and how many seconds it took. The backend works out the start from the time it records the spell less its seconds.
- A run's totals are the rows with its id, failed attempts and retries included. A resume after a sign-off, which makes no model call, and `uv run -m agent CLM-1001` record with no run.
- A dispatch's or an evaluation's claim shows its model cost, its seconds and the start of its first spell in that run.

### Runs

A run is a dispatch or an evaluation, kept in `runs`:

| Field | Meaning |
| --- | --- |
| `run_id` | A UUID |
| `number` | Counts up: shown as `#4`, and part of a copy's id |
| `kind` | `dispatch` or `evaluation` |
| `agents` | N, from 1 to 25 |
| `model`, `reasoning_effort` | As the service's model has them: `openai/gpt-6-luna` and `low` by default, or the `MODEL_NAME` model and `none` |
| `evaluation_set`, `tiny` | For an evaluation: `evaluation` or `held_out`, and whether it's the five `tiny` claims. Empty for a dispatch |
| `status` | `running`, `finished` or `stopped` |
| `started_at`, `finished_at` | `finished_at` is set when the run finishes, and stays empty when it stopped |
| `summary` | A dispatch's summary, built when it finishes |

`run_claims` holds each run's claims in order. A run in a response also has its `claims`, each with its line from the queue (`claim_id`, `customer_name`, `summary`, `status`, `decision` and `payout`) and its `started_at`, `seconds` and `model_cost` in this run; its `model_cost` in all; and `seconds`, from its start to its finish, or empty until it finishes.

| Status | Meaning | Label on screen | Color |
| --- | --- | --- | --- |
| `running` | The service is working it | Running | Marigold |
| `finished` | Every claim was handed over and came back | Finished | Sea Green |
| `stopped` | The service stopped partway, by a crash, a restart or a failure of the dispatcher itself | Stopped | Coral |

The summary of a dispatch is built by the backend when it finishes, from its claims as they stand then, so it says what the dispatch left even after later sign-offs: `{approved, declined, referred, waiting_for_sign_off: [{claim_id, payout}], left_for_handler: [claim_id], unfinished: [claim_id]}`. It counts each claim once: a claim in progress or back in the queue is unfinished, for the next dispatch, even when it has an approval waiting to be paid, and an approval held for sign-off counts as approved.

### Evaluations

- Seeding stores the held-out claims in `held_out_claims` (`claim_id`, `record`), out of the queue, and the handlers' decisions on both sets in `handler_decisions` (`evaluation_set`, `claim_id`, `decision`, `payout`, `tiny`), from `data/evals/decisions.json` for `evaluation` and `held_out_decisions.json` for `held_out`. The held-out claims' policies and customers are already in `policies.json` and `customers.json`. No claim operation reads these two tables.
- `create_evaluation` makes the run and a copy of each of its set's claims, all 25 or the five `tiny` ones, from `claims` for the evaluation set and `held_out_claims` for the held-out set. A copy's id is the original's with the run's number, such as `CLM-1104-E7`, written into its record too. It is a row in `claims`, waiting, with `evaluation_id` set to the run and `copy_of` to the original's id. The run's claims are its copies, oldest submitted first.
- Copies work through every claim operation, so the claim graph works them as it works any claim. `list_claims` leaves them out, so they never show in the queue and a dispatch never lists them. `get_claim` shows `evaluation_id` and `copy_of`.
- Nobody can sign off a copy: `sign_off_claim` refuses one with a 409, and its page has no sign-off form. An approval held for sign-off counts as finished: the claim graph pauses as usual, `work_in_run` deletes the thread's saved progress, and the scoreboard counts the approval and its payout.
- An evaluation that stopped partway shows as stopped. Its copies stay as they were.
- Seeding rebuilds `runs` and the copies with everything else, so `npm run seed` empties the scoreboard. Evaluations need no reseed.

### The scoreboard

The backend scores an evaluation when it's read, from its copies and the handlers' decisions, with `scoring.py`:

| Measure | How it's worked out |
| --- | --- |
| `decision_accuracy` | The share of claims where the agent's decision matches the handler's |
| `accuracy` | The share where the decision matches and the payout is within a dollar |
| `cost_of_mistakes` | In US dollars: $1,500 for a wrongful decline, the payout for a wrongful approval whether or not it was paid, $50 for a needless referral, and the difference for a wrong amount on a right approval |
| `straight_through` | The share of claims not referred |
| `model_cost_per_claim` | The run's model cost over its number of claims |
| `seconds_per_claim` | The average of its claims' seconds in the run |
| `run_seconds` | From its start to its finish, or empty when it hasn't finished |

A claim the agent didn't decide counts as a referral: one in progress, left for a handler or never started. Each claim of an evaluation also has the agent's decision, payout and reason, the handler's decision and payout, whether it's right, and its mistake cost, model cost and seconds.

### The model

`model()` returns `openai/gpt-6-luna` with `reasoning_effort="low"` by default, or the model in `MODEL_NAME` with no reasoning effort, as today. The service records the model's name and its reasoning effort on each run, or `none` when there's none.

### Langfuse

Each claim keeps its own session, named after the claim and its thread, as today. A claim graph invoked in a run also has `langfuse_tags: [run_id]` in its metadata, so `trace.list(tags=...)` on Langfuse's API finds a whole dispatch or evaluation together.

### The agent's service

- `health` and `resume_claim` as today. While it carries a claim on after a sign-off, the service keeps the claim's id in a set that a dispatch's `list_claims` skips.
- `start_dispatch`, `POST /api/dispatches`, body `{agents}`: "Start a dispatch with up to N claim agents at once." `start_evaluation`, `POST /api/evaluations`, body `{evaluation_set, tiny, agents}`: "Start an evaluation with up to N claim agents at once." Each returns 202 at once, or 409 with "A dispatch or an evaluation is already running".
- One run at a time: a `threading.Lock` that a start takes without waiting and the background task releases when the run ends, however it ends. If the dispatcher itself fails, as when the backend can't be reached, the task marks the run stopped with `stop_runs` and logs the error.
- The background task builds the model, creates the run through the backend and calls `dispatcher.work_run`.
- Its lifespan opens the checkpoint pool and marks any run still running as stopped with `stop_runs`.
- The tests use the app without its lifespan, as today, with a graph on a stub model.

### API

New and changed operations of the backend. The others are as in `docs/PLAN_DURABLE.md`. Every operation keeps an `operation_id`, a one-line docstring and no optional inputs. `run_id` in the two recording bodies is required and may be null, which the API rules allow, since it is always sent.

| Operation | Route | What it does |
| --- | --- | --- |
| `record_model_call` | `POST /api/claims/{claim_id}/model-calls` | Body `{run_id, input_tokens, output_tokens, cost}`. Records one model call on a started claim |
| `record_work_time` | `POST /api/claims/{claim_id}/work-times` | Body `{run_id, seconds}`. Records one spell of work on a started claim |
| `start_dispatch` | `POST /api/dispatches` | Body `{agents}`. Asks the agent's service to start a dispatch; returns 202 |
| `start_evaluation` | `POST /api/evaluations` | Body `{evaluation_set, tiny, agents}`. Asks the agent's service to start an evaluation; returns 202 |
| `get_latest_dispatch` | `GET /api/dispatches/latest` | The newest dispatch with its claims, cost, time and summary, or null |
| `list_evaluations` | `GET /api/evaluations` | Every evaluation, newest first, with its measures |
| `get_evaluation` | `GET /api/evaluations/{run_id}` | One evaluation with its measures and its claims beside the handlers' decisions |
| `create_dispatch` | `POST /api/runs/dispatches` | Body `{agents, model, reasoning_effort}`. Records a new dispatch, running |
| `create_evaluation` | `POST /api/runs/evaluations` | Body `{evaluation_set, tiny, agents, model, reasoning_effort}`. Records a new evaluation, running, with its copies |
| `record_run_claims` | `PUT /api/runs/{run_id}/claims` | Body `{claim_ids}`. Records a dispatch's claims in order |
| `finish_run` | `POST /api/runs/{run_id}/finish` | Finishes a run; a dispatch gets its summary |
| `stop_runs` | `POST /api/runs/stop` | Marks every running run stopped and returns their ids |
| `get_instructions` | `GET /api/instructions` | The claim instructions alone, as `{claim}` |
| `list_claims` | `GET /api/claims` | Leaves out evaluations' copies |
| `get_claim` | `GET /api/claims/{claim_id}` | Gains `evaluation_id` and `copy_of` |
| `sign_off_claim` | `POST /api/claims/{claim_id}/sign-off` | Refuses an evaluation's copy |

`start_run`, `write_todos` and `get_latest_run` go. Runs live under `/api/runs`, where only the agent's service writes; the dashboard reads them under `/api/dispatches` and `/api/evaluations`. Every operation under those three paths is in the runs router, `backend/runs.py`. `record_model_call`, `record_work_time` and the changed claim operations stay in `main.py`.

Rules the backend enforces:

- `record_model_call` and `record_work_time` need a claim that has been started (409), a known claim (404) and a known run or null (404). Tokens, cost and seconds can't be below zero (422).
- `start_dispatch` and `start_evaluation` need N from 1 to 25 (422) and a known set (422). They pass on the service's 409 with its detail, and return 503 with "The agent's service isn't running" when it can't be reached. They write nothing.
- `create_dispatch` and `create_evaluation` need N from 1 to 25 (422). `create_evaluation` needs a known set (422).
- `record_run_claims` needs a running dispatch (404, 409) and known claims (404).
- `finish_run` needs a running run (404, 409).
- `sign_off_claim` refuses an evaluation's copy with a 409, "Claim CLM-1104-E7 is a copy in an evaluation and can't be signed off", and changes nothing.
- No response the agent's service can read holds anything from `handler_decisions`.

### Dashboard

- The header links to the Queue, the Scoreboard and the Instructions.
- **The queue page**: the dispatch panel takes the run panel's place. It has a form, "Claim agents at once", a choice from 1 to 25 with 3 chosen, and a "Start a dispatch" button, which shows the backend's refusal, such as "The agent's service isn't running", in an alert. Under it, the latest dispatch: its number and status, when it started and with how many claim agents, its model cost so far, then each of its claims with a link, the customer, its state and its decision and payout. When it finishes: its time, and the summary, such as "3 approved, 1 declined and 1 referred.", "Waiting for sign-off: CLM-1008 $2,240.00, CLM-1011 $1,150.00", "Left for a handler: CLM-1016" and "Left for the next dispatch: CLM-1012", leaving out an empty line. With no dispatch yet it says "No dispatch yet."
- **The Scoreboard page** (`/scoreboard`): a form with the set (Evaluation set or Held-out set), the claims (All 25 or The five tiny claims), "Claim agents at once" from 1 to 25 with 3 chosen, and a "Start an evaluation" button, with refusals shown as on the queue page. Then a table of evaluations, newest first: the number, linked to its page, the start time, the set and its size, N, the model and reasoning effort, the status, and the seven measures.
- **An evaluation's page** (`/scoreboard/:runId`): its details and measures, then a table of its claims: the copy's id linked to its page, the original id, the handler's decision and payout, the agent's decision and payout (or "No decision", counted as a referral), a Right or Miss chip, the mistake cost, the model cost, the time and the agent's reason. Right is Sea Green and Miss is Raspberry.
- **A copy's claim page** says "A copy of CLM-1104 in an evaluation", linking to the evaluation's page. Its decision panel has no sign-off form: a held approval says "Held for sign-off. In an evaluation this counts as finished, and a copy can't be signed off."
- **The instructions page** shows the claim agent's instructions alone.
- Formats: percentages without decimals, such as 80%; model costs, often under a cent, to four decimal places, such as $0.0125; times as 41 s or 2 min 41 s; other money as today.
- `api.ts` gains `startDispatch`, `startEvaluation`, `getLatestDispatch`, `listEvaluations` and `getEvaluation`, and loses `getLatestRun` and the to-do types. The to-do chip and labels go.
- The queue, the dispatch panel and a claim page refresh every two seconds, as today, and so do the Scoreboard and an evaluation's page.

### End-to-end tests

- The stand-in for the agent's service also accepts `POST /api/dispatches` and `POST /api/evaluations` with 202, and lists what it was asked to start at `GET /api/started`.
- The to-do test gives way to a test of the dispatch panel, played out through the API: the test creates a dispatch, records two claims with it, works them through the API, records a model call and a work time on each, and finishes it, and the panel follows each step without a reload.
- New tests start a dispatch and an evaluation on the dashboard and check what the stand-in was asked, and play out an evaluation through the API and check the scoreboard and the evaluation's page.

### What goes

The queue agent, its middleware and `create_agent`; `backend/instructions/queue.md`; the to-do list (`write_todos`, the `todos` table, its types and chips, and its end-to-end test); the queue tools and `RunContext`; and `uv run -m agent` without a claim id, with `--cap`. Seeding drops the old `todos` table first when it's there, before `runs`, since on Postgres its foreign key would stop `runs` being dropped.

### Checked against the code standards

- One way to call each service, with each address written once: the agent to the backend through `api.py`, the dashboard through `api.ts`, the backend to the agent's service through `agent_service.py`, now with three calls, and the end-to-end tests to the stand-in through `e2e/api.ts`.
- Modules keep to their jobs: the dispatcher chooses the claims and keeps track of the run, and reaches the claim agent only through `harness.work_in_run`; the harness builds and runs claim agents; the service receives calls and hands them on; the backend's operations are split between `main.py` for claims and `runs.py` for runs, dispatches and evaluations, with what both need moved to `dependencies.py`, `views.py` and `database.py` rather than borrowed; `scoring.py` holds the measures apart from the routes; seeding is the only reader of `data/evals/`.
- Literals written once: `TRANSIENT` in the harness, which the dispatcher's `RetryPolicy` uses; the most claim agents at once, 25, in the backend's models, the agent's service and the dashboard's choice, since they can't share it; "The agent's service isn't running" in `agent_service.py`; the copy's id in `runs.py`; `WRONGFUL_DECLINE` and `NEEDLESS_REFERRAL` in `scoring.py`.
- The framework's own way: `StateGraph`, `Send`, `max_concurrency`, `RetryPolicy` and `Runtime` with its context and `execution_info` for the dispatcher; `PostgresSaver` on a shared `ConnectionPool`, and `delete_thread`; FastAPI's `APIRouter`, a dependencies module and `BackgroundTasks`; httpx's transport retries; Langfuse's `langfuse_tags`. The one place we don't follow the brief's choice, `error_handler`, is explained above.
- Functions do one job: `work_in_run` chooses between carrying on and starting; the shared invoke function runs and times a spell; `settle` settles; each dispatcher node does one thing.
- No defensive code beyond what the brief asks: the worker's catch, so no error stops a dispatch; the harness's catch around a claim, as today; the backend's 409 and 503 on a start; the service's stop on a failed dispatch and its lock release; and the client's retries while the backend starts.
- The instructions stay goals: the claim instructions don't change, and the queue instructions go, since code now chooses the order.

### How the criteria are checked

API calls run against `npm run dev` on Supabase after `npm run seed`. Tables and connections are checked through the Supabase MCP server, which is read-only. Pages are checked in the browser with the Playwright MCP server at `http://localhost:5173`. Tests never call a model and need no network. Before phase 6 no criterion starts a dispatch or an evaluation on the real model: a run that needs one is played out through the API with curl, or the start is checked with the agent's service stopped. Only the criteria marked "Live" use the real model, all in phase 6, after one `npm run seed`, and only the runs the brief describes.

## Phase 1: GPT-6 Luna by default, and cost and time

Make GPT-6 Luna the default model. Add the `model_calls` and `work_times` tables, `record_model_call` and `record_work_time` in `main.py` with the other claim operations, and the run's id in `ClaimContext`. Record each model call's tokens and cost in the claim graph's `agent` node, and each spell of work in the harness. Tag each claim's trace with its run's id. The queue run still exists in this phase, so its claims record its id. The stub model's replies carry a `token_usage` like OpenRouter's.

- [x] pytest: with no `MODEL_NAME`, `model()` is `openai/gpt-6-luna` with reasoning effort `low`, a 120 second timeout and 5 retries; with `MODEL_NAME=openrouter/free` it has no reasoning effort
- [x] pytest, backend: `record_model_call` on a started claim records the tokens, the cost, the claim's thread, the time and the run, with a run's id and with null. A claim that hasn't started returns 409, `CLM-9999` and an unknown run return 404, and negative tokens or cost return 422
- [x] pytest, backend: `record_work_time` records the seconds, the run and a start equal to the recording time less the seconds, with the same 404, 409 and 422 rules
- [x] The shared OpenAPI test passes
- [x] Stub model test: working `CLM-1001` with no run records one model call per reply, with the stub's tokens and cost and no run, and one spell of work on the claim's thread
- [x] Stub model test, a queue run of two claims: every model call and spell of both claims carries the run's id, and each claim's root run has `langfuse_tags` equal to `[run_id]`. `CLM-1001` worked alone has no tags
- [x] Stub model test: a claim whose first attempt fails after one model call, worked again in the same run, has both attempts' model calls and spells under the run
- [x] Stub model test: `CLM-1002` approved for 1,350.00 pauses; the harness's clock is moved on an hour, and it is signed off and carried on with no run. It has two spells, which together come to under a second, and the second has no run
- [x] `npm run seed`, then Supabase MCP: `model_calls` and `work_times` are in `undercover` and empty
- [x] With `npm run dev` running: after `start_claim` on `CLM-1004` with curl, `record_model_call` with 1,200 input tokens, 300 output tokens and a cost of 0.0042, and `record_work_time` with 12.5 seconds, both return 200 and Supabase MCP shows the rows with no run. `npm run seed` afterwards
- [x] `npm run check` passes

## Phase 2: The dispatcher in place of the queue agent

Add `agent/dispatcher.py` as the design describes, `work_in_run` and `TRANSIENT` in the harness, and the checkpoint pool with a saver per claim run, with the tests' fixture that takes the waits out of the `RetryPolicy`. In the backend, first move the `Database` dependency to `dependencies.py`, `to_claim` and `to_summary` to `views.py` and `now()` to `database.py`. Then start the runs router, `backend/runs.py`, in place of the run operations in `main.py`: rework `runs` and add `run_claims`, `create_dispatch`, `record_run_claims`, `finish_run` with its summary, `stop_runs` and `get_latest_dispatch`. Give the service `start_dispatch`, one run at a time, the stop at startup and the claims it is resuming. Remove everything in "What goes". On the dashboard, the dispatch panel shows the latest dispatch's claims, cost, time and summary, without the form yet, and the instructions page shows the claim instructions alone.

- [x] `grep -rn "create_agent\|Middleware\|write_todos\|run_queue\|RunContext\|queue.md\|getLatestRun" agent backend dashboard/src e2e` finds nothing, and `grep -rn todos backend agent dashboard/src e2e` finds only the retired table's name in `backend/database.py`
- [x] `backend/main.py` defines no operation under `/api/runs`, `/api/dispatches` or `/api/evaluations` (`grep -n '"/api/\(runs\|dispatches\|evaluations\)' backend/main.py` finds nothing), every one is on the router in `backend/runs.py`, and no module in `backend/` imports `backend.main` apart from the tests
- [x] A pytest test checks the dispatcher's nodes, `list_claims`, `work_claim` and `finish_run`, and its edges against the table in the design, and that `work_claim` has the real `RetryPolicy`: three attempts on `TRANSIENT`, waiting 10 seconds first
- [x] pytest: in the tests the dispatcher's `RetryPolicy` has `initial_interval` 0 and `jitter` off, with its three attempts, and `uv run pytest agent -q --durations=5` lists no dispatcher or service test taking a second or more
- [x] Stub model test, six waiting claims at N=3, with a stub that sleeps briefly in each reply and counts the claims it is working on at once: never more than 3 at once, 3 at once at the start, and every claim decided, each on its own thread. The stub keeps a script for each claim, chosen by the claim named in its first message
- [x] Stub model test: a dispatch lists the claims in progress and waiting, oldest submitted first, and leaves decided claims, claims waiting for sign-off and claims left for a handler alone; `record_run_claims` gets them in that order
- [x] Stub model test: a claim that hits `ModelRateLimitError` once carries on as the same attempt on the same thread, with one decision, no `error` step, and both spells under the dispatch
- [x] Stub model test: a claim that hits `ModelRateLimitError` on every try is tried three times, in under a second with the waits at zero, then stays in progress with attempts 1 and no `error` step, and its report is `CLM-…  left for the next dispatch: ModelRateLimitError: …`. The other claims are decided and the dispatch finishes. The same holds for `ModelTimeoutError`
- [x] Stub model test: a claim that fails with a provider error on its first attempt is worked once more in the same dispatch, as attempt 2 on a new thread, and decided. One that fails both times is left for a handler and not tried a third time
- [x] Stub model test: when `start_claim` is refused, because another process started the claim, the dispatch reports it and works the rest
- [x] A test records LangGraph's behavior: a graph whose worker has an `error_handler` and fails beside another worker raises from `invoke` after the handler has run
- [x] Stub model test: a dispatch stopped with `KeyboardInterrupt` partway leaves its claims in progress. The next dispatch carries them on as the same attempts on the same threads, each with one decision, and carries on a claim signed off while the service was away, paying it with the sign-off on the payment
- [x] Stub model test: a dispatch started while the service is resuming a claim leaves that claim out
- [x] pytest, with a stand-in pool: `checkpoint_pool()` opens at most 4 connections with `timeout=120` and sets up the saver once, and each graph from `claim_graphs()` has a `PostgresSaver` of its own on that pool
- [x] pytest, backend: `create_dispatch` returns a running dispatch with its N, model and reasoning effort, and N of 0 or 26 returns 422. `record_run_claims` keeps the order. `get_latest_dispatch` returns the newest dispatch with each claim's state, decision, payout, start, seconds and model cost in this dispatch, and the dispatch's model cost, or null before the first
- [x] pytest, backend: with one claim of a dispatch paid, one declined, one referred, one waiting for sign-off for 2,240.00, one left for a handler, one in progress, one signed off but not yet paid and one never started, `finish_run` gives the summary `{approved: 2, declined: 1, referred: 1, waiting_for_sign_off: [{claim_id, payout: 2240.0}], left_for_handler: [...], unfinished: [the last three]}` and a finish time. A second `finish_run` returns 409. `stop_runs` stops every running run and leaves finished ones alone
- [x] pytest, service: `start_dispatch` with N=2 returns 202, and the dispatch runs with `max_concurrency` 2 and finishes. A second start while it runs returns 409 with "A dispatch or an evaluation is already running" and creates nothing; once it ends, a start is accepted. N=0 returns 422
- [x] pytest, service: the lifespan, with the checkpoint pool stubbed, marks a running run stopped. A dispatch whose dispatcher fails is marked stopped, and the next start is accepted
- [x] The shared OpenAPI test passes for the backend and the agent's service
- [x] Command line: `uv run -m agent` exits with "the following arguments are required: claim_id", and `CLM-1001` works one claim with no run (tested with the pool and the claim stubbed)
- [x] `curl -s localhost:8000/api/instructions` returns `claim` alone
- [x] vitest: the dispatch panel shows "No dispatch yet.", a running dispatch with its claims, their states and links, a finished dispatch with its summary lines, model cost and time, and a stopped dispatch; the instructions page shows "Working a claim" alone
- [x] e2e: the dispatch panel follows a dispatch played out through the API on `CLM-1013` and `CLM-1014`, from Running with both claims Waiting, through In progress and Decided, to Finished with its summary, model cost and time
- [x] `npm run seed`, then Supabase MCP: `runs` has the columns in the design, `run_claims` is there, and `todos` isn't
- [x] With `npm run dev` running, after a dispatch is created with curl (`create_dispatch`), restarting `npm run dev` leaves it Stopped in `curl -s localhost:8000/api/dispatches/latest`, and `curl -s localhost:8002/api/health` answers. `npm run seed` afterwards
- [x] Browser: the queue shows "No dispatch yet." after the reseed, with no errors in `browser_console_messages`
- [x] `npm run check` passes

## Phase 3: Starting a dispatch from the dashboard

Add `start_dispatch` to the runs router and `agent_service.py`, the start form on the dispatch panel, and starts to the stand-in.

- [x] pytest, backend: `start_dispatch` with N=7 asks the agent's service once, with `{"agents": 7}`, returns 202 and writes nothing to `runs`. The service's 409 comes back as a 409 with its detail. A service that can't be reached gives 503 with "The agent's service isn't running". N of 0 or 26 returns 422 and the service isn't asked
- [x] `grep -rn "UNDERCOVER_AGENT\|8002" backend --include=*.py` finds them only in `backend/agent_service.py`
- [x] vitest: the form offers 1 to 25 with 3 chosen, and starting with 7 posts `{"agents": 7}`; a 409 and a 503 show their detail in an alert, and the button can be pressed again afterwards
- [x] e2e: choosing 7 and pressing "Start a dispatch" reaches the stand-in with `{"agents": 7}`
- [x] Browser, with `npm run dev:backend` and `npm run dev:dashboard` running but not the agent's service: pressing "Start a dispatch" shows "The agent's service isn't running", and no dispatch appears
- [x] Browser: with a dispatch of five claims played out with curl, finished with one held for sign-off and one left for a handler, screenshots of the panel in light and dark mode show rounded panels with no outlines, no one-edge borders and no gradients, and `browser_console_messages` shows no errors. `npm run seed` afterwards
- [x] `npm run check` passes

## Phase 4: Evaluations

Seed the held-out claims and the handlers' decisions. Add `evaluation_id` and `copy_of` to `claims`, `scoring.py`, and in the runs router `create_evaluation` with its copies, `list_evaluations`, `get_evaluation` and `start_evaluation`. Add the refusal of a sign-off on a copy in `main.py`, and `start_evaluation` to the agent's service. The dispatcher lists an evaluation's copies, and `work_in_run` clears a held copy's progress.

- [x] `uv run -m backend.seed` prints `Seeded 25 claims, 50 policies, 49 customers and 3 handlers into undercover.db, with 25 held-out claims and 50 handlers' decisions for evaluations`
- [x] pytest, scoring: a test for each rule of the cost of mistakes, including a wrongful approval that wasn't paid; a payout 99 cents out counting as right and one $1.01 out as wrong; an undecided claim counting as a referral; and the measures of a hand-made evaluation
- [x] pytest, backend: `create_evaluation` of the held-out set's `tiny` claims at N=5 makes five waiting copies, `CLM-1104-E1`, `CLM-1106-E1`, `CLM-1110-E1`, `CLM-1112-E1` and `CLM-1114-E1`, each with its id in its record, and the evaluation records its set, `tiny`, N, model and reasoning effort. The whole evaluation set makes 25 copies. An unknown set returns 422
- [x] pytest, backend: `list_claims` returns the same 25 claims before and after an evaluation, and `get_claim` on a copy shows its `evaluation_id` and `copy_of`
- [x] pytest, backend: `get_claim` on every copy, and `create_evaluation`'s response, hold none of the handlers' reasons, references or calculations, and no field from `handler_decisions`
- [x] pytest, backend: `sign_off_claim` on a copy held for sign-off returns 409 and changes nothing
- [x] pytest, backend: `start_evaluation` passes the set, `tiny` and N to the agent's service, with the same 409, 503 and 422 rules as `start_dispatch`
- [x] Stub model test, through the agent's service: an evaluation of the evaluation set's five `tiny` claims at N=5, where the stub approves `CLM-1007` for 50.00, approves `CLM-1015` for 300.00, declines `CLM-1017`, approves `CLM-1020` for 1,240.00 and fails twice on `CLM-1021`. It finishes, the queue is the same before and after, and the copy of `CLM-1020` is waiting for sign-off with no saved progress on its thread. `get_evaluation` gives decision accuracy 0.4, accuracy 0.2, cost of mistakes 2,850.00 and straight-through 0.8, with the model cost per claim and time per claim the stub's records add up to
- [x] Stub model test: a dispatch started after an evaluation leaves its copies alone, including one left in progress
- [x] pytest, service: `start_evaluation` while a dispatch runs returns 409, and `start_dispatch` while an evaluation runs returns 409
- [x] A pytest test checks that `agent/api.py` has no function for `list_evaluations`, `get_evaluation`, `start_dispatch` or `start_evaluation`
- [x] `grep -n '"/api/\(runs\|dispatches\|evaluations\)' backend/main.py` still finds nothing: every new run operation is in `backend/runs.py`
- [x] The shared OpenAPI test passes for the backend and the agent's service
- [x] `grep -rn evals agent dashboard/src e2e` finds nothing, and `grep -rn evals backend --include=*.py` finds it only in `backend/database.py` and `backend/tests/`
- [x] `npm run seed` prints the counts above for the `undercover` schema, and Supabase MCP shows 25 rows in `held_out_claims` and 50 in `handler_decisions`, 10 of them `tiny`
- [x] With `npm run dev` running: `create_evaluation` with curl for the held-out set's `tiny` claims makes five copies, `curl -s localhost:8000/api/claims` still returns 25 claims, and `curl -s localhost:8000/api/evaluations` lists the evaluation with every measure, with every copy counted as a referral. `npm run seed` afterwards
- [x] `npm run check` passes

## Phase 5: The scoreboard

Add the Scoreboard page with its start form and the list of evaluations, an evaluation's page, the header link, and a copy's claim page without a sign-off form.

- [x] vitest: the Scoreboard lists evaluations newest first with their measures formatted (80%, $1,600.00, $0.0125, 40 s, 2 min 41 s); the form starts with the evaluation set, all 25 and 3 agents, and posts the choices made; a 409 and a 503 show their detail
- [x] vitest: an evaluation's page shows each claim with the handler's decision and payout beside the agent's, a Miss chip on each miss, "No decision" for an undecided claim, and links to the copies
- [x] vitest: a copy's claim page says which evaluation it's in, with a link, and a held copy shows no sign-off form
- [x] e2e: on the Scoreboard, choosing the held-out set, the five tiny claims and 5 agents, then "Start an evaluation", reaches the stand-in with `{"evaluation_set": "held_out", "tiny": true, "agents": 5}`
- [x] e2e: an evaluation of the held-out set's `tiny` claims, played out through the API, in which the agent approves `CLM-1104` for 250.00, approves `CLM-1106` for 300.00, refers `CLM-1110`, approves `CLM-1112` for 1,200.00, which is held for sign-off, and leaves `CLM-1114` undecided, with a model call costing $0.0125 and 40 seconds of work on each copy. The Scoreboard shows decision accuracy 80%, accuracy 40%, cost of mistakes $620.00, straight-through 60%, $0.0125 per claim and 40 s per claim. Its page marks the copies of `CLM-1106`, `CLM-1112` and `CLM-1114` as misses, and the copy of `CLM-1112` opens with no sign-off form
- [x] Browser: with that evaluation played out with curl, screenshots of the Scoreboard and the evaluation's page in light and dark mode show rounded panels with no outlines, no one-edge borders and no gradients, and Right and Miss chips in Sea Green and Raspberry (`browser_evaluate`). `browser_console_messages` shows no errors. `npm run seed` afterwards
- [x] `npm run check` passes

## Phase 6: The live runs, and the docs

Run the trial the brief describes, fix what it finds, then bring `docs/SPEC.md`, `docs/TECH_STACK.md`, `docs/PROCESS.md`, `docs/CODE_STANDARDS.md` and `docs/STATUS.md` up to date.

- [x] Live: after one `npm run seed`, with `npm run dev` running and the default model, start a dispatch at N=3 on the queue page. Once at least three claims are decided, stop it with `kill -9` on every process from `lsof -ti tcp:8002`, which makes `npm run dev` stop the others, and start `npm run dev` again. The N=3 dispatch shows Stopped
- [x] Live: a dispatch at N=25 carries on the claims left in progress, each with the thread and attempts it had and one decision, and works the rest. The start times of the claims it worked from the start are within a few seconds of each other. (CLM-1004 carried on as attempt 1 on its thread, then the model finished without recording a decision, so the dispatch worked it once more as attempt 2, which decided it once: see `docs/STATUS.md`.)
- [x] Live: its run takes well under the sum of its claims' times
- [x] Live: claims worked from the start take about as long on average at N=25 as at N=3, from the work times of both dispatches through Supabase MCP. If they are slower, report where the time goes, from the model calls' times in Langfuse and the gaps between each claim's steps, keeping to 4 connections a process
- [x] Live: claims held for sign-off show Waiting for sign-off, and signing one off on its page shows it paid, with the handler and the time, within five seconds (`browser_wait_for`)
- [x] Live: no claim has an `error` step about a database connection or a pool timeout, and Supabase MCP, checked several times during the N=25 dispatch, never shows more than 12 connections from `select count(*) from pg_stat_activity where usename = 'postgres'`
- [x] Live: an evaluation of the evaluation set at N=25, and one of the held-out set's five `tiny` claims at N=5, started on the Scoreboard, finish and appear with every measure, and the queue page's counts are the same before and after them
- [x] Live: through Langfuse's API, `trace.list(tags=[run_id])` for the N=25 dispatch returns a trace for each of its claims
- [x] `docs/SPEC.md`: its section on working the queue describes dispatches, with N claim agents at once, code choosing the order, problems put right as the brief says, cost and time, and evaluations on copies; its section on what the team needs to see describes the dispatch panel, the Scoreboard and the claim agent's instructions. Its Rules are unchanged
- [x] `docs/TECH_STACK.md` names the backend's runs router beside the claim operations, and the dispatcher as a fifth part of the agent, with `Send`, `max_concurrency` and `RetryPolicy`; a saver per claim run on a pool of 4; `work_claim`, `carry_on` and `work_in_run`; GPT-6 Luna by default; cost from `usage.cost`; and the Langfuse tags
- [x] `docs/PROCESS.md`: these live runs, a dispatch from the dashboard after a reseed and evaluations, which need none, replace the five-claim cap
- [x] `docs/CODE_STANDARDS.md`: rule 10 names the dispatcher's LangGraph tools in place of the queue agent's middleware, and rule 13 gives the agent five parts, with the dispatcher reaching the claim agent only through the harness's one function
- [x] `docs/STATUS.md` describes what's built, how to start a dispatch and an evaluation, the live runs' times, decisions, connections and measures, and the known gaps, including LangGraph's `error_handler`
- [x] `npm run check` passes, both with `.env` in place and with it moved out of the way

## Not in this plan

- Sending the scores to Langfuse, as the lab does with `create_score`.
- Moving to `error_handler` once a LangGraph release stops re-raising a handled error.
- Choosing the model on the dashboard. `MODEL_NAME` still chooses it, and each run records it.
- Clearing old checkpoints and old evaluations' copies. Reseeding clears the copies and the scoreboard.
- Telling a dispatch which claim `uv run -m agent CLM-…` is working. As today, the backend still decides and pays such a claim once.
- Stopping a dispatch from the dashboard.
- Rejecting a held payout, running the agent's service in the cloud, sign-in, real payments and messages to customers.
