# Plan: sending claims back, and the agent on AgentCore Runtime

This plan makes the changes in `docs/RUNTIME.md`, one phase for each of its four steps, in order. Each phase leaves `npm run check` green and is committed before the next one starts. Step 4 is the largest phase. The live checks from every step, and from the brief's "What done looks like", run once at the end of phase 4, after one reseed.

SIDENOTE: For consistency with the course, please read `labs/week3day4_lab2.ipynb`, which deploys the agent on AgentCore Runtime and points the app at it, without running it. Where the notebook and this document differ, follow this document. The pause in step 1 was in the course's build for self-improvement, before the security build took it out: `git show week2day5-end:agent/harness.py` has its `wait_for_sign_off` node, and `git show week2day5-end:agent/service.py` its `resume_claim` route. Lab 1's `agentcore dev` also serves on port 8080, so stop it before `npm run dev`. Include this sidenote in your plan too.

When it's done, an approval that waits for sign-off pauses the claim graph with LangGraph's `interrupt()`, its place saved in Supabase. A senior handler signs it off, which pays it and lets the agent finish its work on the claim, or sends it back with a note, which the agent reads as a senior handler's review before it decides again. The agent is an AgentCore app in `agent/entrypoint.py`, which `npm run dev` serves on 127.0.0.1:8080 and the platform team's `runtime/main.py` runs on Runtime, taking one JSON payload per operation, answering at once and keeping its session busy while the work goes on. The app reaches it at `/invocations` with the agent's key on a laptop, or through boto3's `invoke_agent_runtime` when `UNDERCOVER_AGENT_RUNTIME` names a runtime. The app, not the agent, keeps one dispatch, evaluation or working round going at a time: it creates the runs and rounds and records the reviews, then asks the agent to work them by id, and the agent tells it every minute that it's still working.

Phases 1 to 4 are checked with tests, local commands and a SQLite backend, and none of them uses the real model, AWS or Supabase. The live checks run last, in phase 4, on the default model, on the direct route with memory off.

## Design

### Modules

The agent:

- `harness.py`: the claim graph gains a pause node, `wait_for_handler` (phase 1), which a held approval goes to unless the graph is an evaluation's, and which leads to the end of the work after a sign-off or back to the model after a send back (phase 2). `claim_graphs(version, kind, pool)` tells `claim_graph` whether it pauses, from the kind of run, as it already decides the memory. New entry point `resume(claim_id, agent)`, and `paused(claim, agent)`. `carry_on` resumes a thread whose next step is the pause, and `work_in_run` takes a sent-back claim before carrying it on (phase 2). `checkpoint_pool()` turns prepared statements off, and splits into `open_checkpoint_pool()`, which the entry point keeps open for its process, and the context manager around it, which `uv run -m agent` and the tests use (phase 3).
- `handler_answer.py` (new, phase 1): a handler's answer to a held approval, read from the app's record of the claim: signed off by whom, or sent back by whom with which note (phase 2), or no answer yet; and the message that gives the model the note (phase 2). It uses nothing else in the agent.
- `heartbeat.py` (new, phase 2): `beating(tell)`, a context manager that calls `tell()` every minute on a daemon thread while its block runs and stops when it ends. A failed call is logged and never stops the work. It uses nothing else in the agent.
- `identity.py` (new, phase 3): AgentCore Identity. `on_runtime()` says whether the deployment named any credential (a setting `AGENTCORE_CREDENTIAL_<NAME>_NAME`), and `fetch_credentials()` fetches each one's value with `requires_api_key(provider_name=...)` from `bedrock_agentcore.identity.auth` into the setting `<NAME>`. It is the one place with `AGENTCORE_CREDENTIAL_` and `requires_api_key`, and it uses nothing else in the agent.
- `entrypoint.py` (new, phase 3) takes the place of `service.py`: `app = BedrockAgentCoreApp()` with one `@app.entrypoint`, which gets ready, checks the key off Runtime, validates the payload and hands the operation to the dispatcher, the harness or the improver on a thread of its own, registered as an async task. In phase 3 it keeps today's `OneAtATime`, the service's routes as operations and the start-up stops; phase 4 takes all three out.
- `dispatcher.py` (phase 2): a dispatch also works sent-back claims, and leaves alone a claim in progress that a resume is working on.
- `api.py`: `Status.SENT_BACK`, `take_claim` and `record_claim_heartbeat` (phase 2); `get_run`, `fail_run` and `record_run_heartbeat` in, `create_dispatch`, `create_evaluation` and `stop_runs` out (phase 4).
- `improver_api.py` (phase 4): `get_proposal`, `fail_round` and `record_round_heartbeat` in; `create_round`, `record_review` and `stop_rounds` out.
- `service.py` gains the `resume_claim` route (phases 1 and 2) and is then removed (phase 3). `improver.py`, `tools.py` (apart from `claim_as_read`, below), the routes and the memory don't change.

The backend:

- `dependencies.py` (phase 1): `database()` opens one connection for the request and commits at its end, as now, but a route can commit sooner with `db.commit()`; whatever it writes after that is committed at the end. A route that asks the agent for something commits first, so the agent sees it, and every request holds one connection at a time.
- `main.py`: `sign_off_claim` moves the claim on with a conditional update, commits, then asks the agent to resume the claim (phase 1). New `send_back_claim`, `take_claim` and `record_claim_heartbeat` (phase 2). `claim_in_full(db, claim_id)` replaces the many `to_claim(find_claim(...))`.
- `sent_back.py` (new, phase 2): the decisions handlers sent back: keeping one with its note, and reading a claim's, oldest first.
- `agent_work.py` (new): what the app knows of the agent's work. Phase 2 brings `QUIET` (five minutes) and `heard_lately(stamp)`, which the queue's `resuming` uses. Phase 4 brings the rest: taking the lock, marking quiet work stopped, refusing while work is going, and asking the agent with an undo for when it didn't take the work. The runs and improvement routers both use it, and neither uses the other's helpers.
- `agent_service.py`: `resume_claim(claim_id)`, posting to the service's new route (phase 1). Then (phase 3) the agent, as the app calls it. Two routes chosen per call: `/invocations` at `UNDERCOVER_AGENT` (by default `http://127.0.0.1:8080`) with the key as `Authorization: Bearer <key>` and a 10-second timeout, or `invoke_agent_runtime` on `UNDERCOVER_AGENT_RUNTIME`. One function per operation, each building a payload; `NotTaken` (with the status and reason the handler gets) and `MayHaveStarted`. It is the one place with `UNDERCOVER_AGENT`, `UNDERCOVER_AGENT_RUNTIME`, `/invocations` and the `bedrock-agentcore` client.
- `runs.py` (phase 4): `start_dispatch` and `start_evaluation` create the run themselves, then ask the agent to work it. New `get_run`, `fail_run` and `record_run_heartbeat`; `create_dispatch`, `create_evaluation` and `stop_runs` go as operations, while the functions that make runs stay. `finish_run` answers with a run that was stopped meanwhile, leaving it stopped.
- `improvement.py` (phase 4): `start_round` creates the round, and `approve_proposal` and `reject_proposal` record the review, then ask the agent. New `get_proposal`, `fail_round` and `record_round_heartbeat`; `create_round`, `record_review` and `stop_rounds` go as operations.
- `round_state.py` (phase 4): `stop()` also stops the round's running evaluation, with the round's reason.
- `database.py`: `sent_back_decisions` and `claims.resume_heard_at` (phase 2); `runs.heard_at`, `runs.stopped_because`, `rounds.heard_at` and a one-row `locks` table (phase 4).
- `models.py`: `Status.SENT_BACK`, the `sent_back` step kind, which only the app records, `SendBackRequest`, `SentBackDecision`, `Claim.sent_back_decisions`, `ClaimSummary.resuming` and `TakeRequest` (phase 2); `RunDetails.stopped_because` (phase 4).
- `views.py`: `to_claim` takes the claim's sent-back decisions, and `to_summary` says whether a resume is working on the claim (phase 2).
- `instructions/claim.md` (phase 2): only the words "which can't be changed afterwards" change, to say a decision stands unless a senior handler sends it back with a note.

The dashboard:

- `api.ts`: the `sent_back` state and step kind, `SentBackDecision`, the claim's `sent_back_decisions`, the summary's `resuming`, `sendBack(claimId, note)` (phase 2), and the run's `stopped_because` (phase 4).
- `DecisionPanel.tsx`: on a held payout, a handler who can sign off over the limit gets Sign off (`SignOffForm.tsx`, as now) and Send back (`SendBackForm.tsx`, new), and a sent-back claim says what happens next. `SentBackDecisions.tsx` (new) shows each decision sent back with its note, who sent it back and when, beside the current decision. `StepList.tsx` shows the note as a step. The queue page gains a tile for the new state (phase 2).
- `DispatchPanel.tsx` and the evaluation page show why a run stopped (phase 4).

The rest:

- `pyproject.toml` (phase 3): `bedrock-agentcore` joins the dependencies; a `runtime` group with exactly what the agent imports on Runtime (`bedrock-agentcore`, `boto3`, `httpx`, `langchain`, `langchain-openai`, `langchain-mcp-adapters`, `langfuse`, `langgraph`, `langgraph-checkpoint-postgres`, `langgraph-checkpoint-aws`, `mcp`, `psycopg[binary]`, `psycopg-pool` and `pydantic`); `boto3` joins the `server` group; ruff and pyright take in `runtime/`.
- `package.json` (phase 3): `dev:agent` becomes `uv run --env-file .env uvicorn agent.entrypoint:app --port 8080 --reload --reload-dir agent`, and `check:runtime` is `uv run --isolated --only-group runtime python -c "import runtime.main"`, beside `check:server` and `check:context`. `lefthook.yml`'s Python glob takes in `runtime/`.
- `conftest.py`: no test sees `UNDERCOVER_AGENT_RUNTIME` or any `AGENTCORE_CREDENTIAL_*` setting, and the agent's stand-in keeps each payload (phase 3).
- `e2e/agent_stand_in.ts`: records the resume (phase 1), moves to `/invocations` and `/ping` (phase 3), and gets the app's address and the agent's key to stop the work it was given (phase 4). `playwright.config.ts` blanks `UNDERCOVER_AGENT_RUNTIME` for the backend.
- `agentcore/` and `runtime/` don't change.

### A claim's states

| State | Meaning | Label | Tile |
| --- | --- | --- | --- |
| `waiting` | In the queue, not started | Waiting | Cerulean |
| `in_progress` | The agent is working on it | In progress | Marigold |
| `waiting_for_sign_off` | Approved over the limit, or the Gateway refused the payment; the claim graph is paused | Waiting for sign-off | Coral |
| `sent_back` (new) | A senior handler sent the decision back with a note, and the agent hasn't taken it yet | Sent back | Marigold, with Lucide's `Undo2` |
| `decided` | Decided, paid or signed off | Decided | Sea Green |
| `left_for_handler` | Failed twice | Left for a handler | Raspberry |

The brand has five colors for five states. Sent back shares Marigold with In progress, since both are in the agent's hands, and its icon and label tell the two tiles apart.

A held claim moves on once: a sign-off moves it from waiting for sign-off to decided and pays it, and a send back moves it to sent back. Each is a conditional update of the claim's row on that status, checking the row count, as `finish_run` does, so a sign-off and a send back at the same moment can't both happen, on SQLite or Postgres. A sent-back claim moves to in progress once, through `take_claim`, the same way.

### The pause and the answer

```
START -> screen --(instructions found)--> refer -> END
            |
            +--(none found)--> agent <-> tools --(paid at once)--> pay --(paid)--> remember -> END
                                 ^         |                         +--(held)----> wait_for_handler
                                 |         +--(held)--> wait_for_handler --(signed off)--> remember -> END
                                 |         +--(declined or referred)--> remember -> END
                                 +---------------------(sent back, with the note)--- wait_for_handler
```

- With memory off, `remember` is `END`. An evaluation's graph has no `wait_for_handler`: its held edges go to the end, as today. `after_tools` and a new `after_pay` say "held" and the graph's path map sends that to the pause or to the end.
- `wait_for_handler` calls `interrupt({"claim_id": ...})` first thing, with nothing before it, since a resume runs the node again from the top. What the interrupt returns is the handler's answer.
- The answer comes from the app's record, never from the request: `handler_answer.answer_of(claim)` reads the claim from `get_claim` and gives `{"answer": "signed_off", "by": ...}` for a decision with a sign-off, `{"answer": "sent_back", "by": ..., "note": ...}` for a claim with no current decision whose newest sent-back decision has its note, or nothing.
- Signed off: the node returns nothing, and the work ends as for any decision, through `remember` when there's a memory. The node never pays: the sign-off has already paid.
- Sent back (phase 2): the node forgets the decision (`decision` and `status` set to empty), gives the claim agent its full allowance of model calls again (it adds minus the count so far, since `model_calls` adds up), and adds the note message, then goes to `agent`. Nothing in the graph's state can pay the old decision, and the app has cleared it too.
- A claim is paused when `graph.get_state(thread).interrupts` holds an interrupt. `next` names the pause as soon as the step before it is saved, while the first run may still be going, so `paused()` never uses it.
- `resume(claim_id, agent)` runs the claim graph on the claim's thread with `Command(resume=answer)`, traced as "Resume" in the claim's Langfuse session, timed as a spell of work with no run, then settled and reported like `carry_on`.
- `carry_on` resumes with `Command(resume=answer)` whenever the thread's next step is the pause, whether the pause has run or not: LangGraph 1.2.12 saves a resume with no interrupt waiting as a write the pause's `interrupt()` returns at once. This is how a dispatch picks up a sent-back claim whose thread is paused, and one whose process stopped after the decision and before the pause. A test covers both.

### Sign off or send back

- The sign-off panel shows two actions to a handler who can sign off over the limit: Sign off, as now, and Send back, which opens a required note, "What should the agent look at again?", of up to 1,000 characters, with Send back to the agent. Anyone else sees today's `NotAllowed` message for both.
- `send_back_claim` (`POST /api/claims/{claim_id}/send-back`, body `{note}`, for `senior("send this back")`): a copy gets a 409, an unknown claim a 404, a blank note or one over 1,000 characters a 422. The conditional update moves the claim from waiting for sign-off to sent back (a 409 otherwise). Then it copies the decision into `sent_back_decisions`, with its calculation, the note, the handler's name and the time, deletes the decision and the claim's calculation, so the new decision needs a calculation of its own, and records the note as a `sent_back` step on the claim's thread, "Sent back by Dana Whitfield: ...". It commits, asks the agent to resume the claim, and answers with the claim in full whatever happens to that call, logging a warning when it fails or times out.
- `sign_off_claim` does the same around today's sign-off: the conditional update, the sign-off and the payment, a commit, the call to resume, and the claim in full.
- `take_claim` (`POST /api/claims/{claim_id}/take`, body `{run_id}`, the agent's key only): moves a sent-back claim to in progress, keeping its thread and its attempt; any other claim gets a 409, "Claim CLM-1011 isn't sent back", so only the first caller gets it. `run_id` is the dispatch taking it, or `null` for a resume, which also sets `resume_heard_at`.
- `record_claim_heartbeat` (`POST /api/claims/{claim_id}/heartbeat`, the agent's key only) sets `resume_heard_at` to now. A claim's summary says `resuming` while that is within the last five minutes (`agent_work.heard_lately`).
- `get_claim` gives the claim's `sent_back_decisions`, oldest first. `claim_as_read` leaves them out, so neither the check for hidden instructions nor the claim agent's `get_claim` reads a handler's note as part of the claim: the note reaches the model only as the handler's message.
- The note message is code, in `handler_answer.py`, so a version of the instructions can't drop it. Its goals: it names who sent the decision back and gives the note; it says the earlier decision no longer stands and nothing has been paid; it asks the agent to treat the note as a senior handler's review, checked against the policy wording and the claims manual like everything else, and to record a new decision; and when the wording doesn't support what the note asks, to refer the claim to a handler, saying why.
- A new decision goes through the same checks as any other: an approval needs its calculation on the same thread, a payout over the limit waits for sign-off and pauses again, and one within the limit is paid by `pay`. A claim can be sent back more than once.
- The claim page shows the current decision as now, then each decision sent back with its chip, payout, section, reason, who made it, its note, and "Sent back by Dana Whitfield at 2:05 PM". While a claim is sent back the panel says "Sent back to the agent, which hasn't taken it up yet. The next dispatch works on it." The step list shows the note with "Sent back" and an icon at the text's size.

### Who works a sent-back claim

- The agent's `resume_claim` reads the claim, builds a claim agent on the current version (memory as for no run, pausing on), and refuses unless the claim is paused and has an answer. For a sent-back claim it then takes it with `take_claim(claim_id, None)`, refusing with the app's reason if a dispatch got there first. It answers at once and resumes on a thread of its own, telling the app every minute with `record_claim_heartbeat`.
- A dispatch lists waiting, sent-back and in-progress claims, oldest submitted first, and leaves out an in-progress claim whose summary says `resuming`. `work_in_run` takes a sent-back claim with the run's id, then carries it on, which resumes the paused thread with the note. When a resume took it first, the report line says so, "CLM-1011  taken by a resume", and the dispatch goes on.
- So a send back the agent never got, because the call failed or its session ended first, waits for the next dispatch, and a claim whose resume went quiet for five minutes is carried on by the next dispatch.
- `finish_run`'s summary counts a sent-back claim as unfinished, for the next dispatch.

### The agent's operations

Each payload names an operation and carries all its inputs; there are no optional ones. A payload is validated with one Pydantic discriminated union on `operation`, with extra inputs forbidden, and a payload it can't read gets a 400, `{"error": "agents: Input should be less than or equal to 25"}` or "Unknown operation: ...".

| Phase 3 | Phase 4 | Inputs |
| --- | --- | --- |
| `health` | `health` | none |
| `start_dispatch` | `work_run` | `agents` / `run_id` |
| `start_evaluation` | (`work_run`) | `agents`, `evaluation_set`, `tiny` |
| `start_round` | `work_round` | `handler_id` / `round_id` |
| `review_proposal` | `carry_round_on` | `round_id`, `proposal_id`, `review`, `handler_id`, `reason` / `round_id`, `proposal_id` |
| `resume_claim` | `resume_claim` | `claim_id` |

- Answers: `{"accepted": true}` once the work is registered and started, `{"refused": "<reason>"}` where the service answers a 409 today (and where the app refuses with `Refused`, such as an unknown claim), `{"healthy": true}` for the health check.
- Each operation checks what it must, registers its work with `app.add_async_task(name)` before it answers, and runs the work on a thread of its own that ends with `app.complete_async_task(task_id)` however it ends. The AgentCore app's own `/ping` then says `HealthyBusy` while work is going and `Healthy` after.
- Phase 4's refusals come from the app's records: `work_run` refuses a run that isn't running, `work_round` a round that isn't open, `carry_round_on` a round that isn't open or a proposal with no review, and `resume_claim` a claim that isn't paused or a sent-back claim it can't take.
- In phase 4 a failed run is stopped by its id with `fail_run(run_id, reason)`, and a failed round with `fail_round(round_id, reason)`, which also stops its running evaluation. Nothing else is stopped.

### Getting ready

- Importing `agent.entrypoint` or `runtime.main` reads no setting that a missing value would break, opens no connection, fetches nothing and starts no thread; the module-level HTTP client in `connection.py` opens nothing until its first request.
- The first request, whatever it is, gets ready once in the process, behind a lock: on Runtime it calls `random.seed()` and `identity.fetch_credentials()`; then it sets up the report lines, checks the agent's key is set, opens the checkpoint pool with `open_checkpoint_pool()` and builds the workers (the claim agents on the pool, the improver's model and its saver). In phase 3 it then marks stopped the runs and rounds left running, as the service's lifespan does today; phase 4 takes that out. If any of it fails, the request answers 503, "The agent couldn't get ready: ...", and the next request tries again.
- Off Runtime, every request but the health check needs `Authorization: Bearer <key>` matching `UNDERCOVER_API_KEY`, compared with `secrets.compare_digest`, or gets a 401. On Runtime, AWS has already checked the caller, and the agent asks for no key.
- The checkpoint pool opens with `prepare_threshold=None`, so it works through either pooler.

### From the app to the agent

| What happened | Laptop route (httpx) | Runtime route (boto3) | The agent took it? | The handler gets |
| --- | --- | --- | --- | --- |
| Accepted | 200 `{"accepted": true}` | the same, read from `response["response"]` | Yes | 202, as today |
| Refused | 200 `{"refused": ...}` | the same | No | 409 with the reason |
| Never sent or never connected | `ConnectError`, `ConnectTimeout`, `PoolTimeout` | botocore's `ConnectionError` and its subclasses | No | 503 "The agent's service isn't running" |
| Error answer | any status of 400 or more, or a whole answer that is neither | `ClientError`, a `statusCode` of 400 or more in the response, or a whole answer that is neither | No | 502 "The agent couldn't take the work: ..." |
| Sent, then a timeout or a cut-off answer | any other `httpx.TransportError` | any other exception, such as `ReadTimeoutError` or `IncompleteReadError` | Maybe | 503 "The agent's service didn't answer in time. Reload the page ..." |

- "Neither" means a whole answer that is neither `{"accepted": true}` nor an object with a `refused` reason, such as `{"accepted": false}`, today's `{"status": "accepted"}`, or a body that isn't JSON. On both routes it counts as an error answer: the agent didn't take the work. An answer cut off partway is still a cut-off, which may have started the work.
- On the Runtime route, `invoke_agent_runtime` can return the agent's own error status as the response's `statusCode` rather than raising `ClientError`, so the app reads `statusCode` before the body.
- Today an error answer is an unhandled 500; the 502 with the reason is the one deliberate change to what a handler sees.
- The Runtime route: `boto3.client("bedrock-agentcore", config=Config(retries={"total_max_attempts": 1}, connect_timeout=5, read_timeout=20)).invoke_agent_runtime(agentRuntimeArn=..., runtimeSessionId=str(uuid.uuid4()), payload=json.dumps(payload))`, in the region the app runs in, with no key. A UUID's 36 characters meet the 33.
- "Didn't take it" undoes what the app did for the work (phase 4) and commits the undo before the refusal is raised. "Maybe" changes nothing. The sign-off and the send back answer with the claim either way, logging a warning.

### One piece of the agent's work at a time (phase 4)

- Work that's going: a running run that isn't a round's evaluation, and an open round with no proposal waiting for a handler. A round's evaluation is part of its round's work.
- A start (`start_dispatch`, `start_evaluation`, `start_round`, `approve_proposal`, `reject_proposal`) works on the request's one connection, in this order: take the lock, an `UPDATE` of the `locks` row, which is the transaction's first write, so Postgres's row lock and SQLite's write lock hold until the commit and a second start waits for it and then sees the first's work; mark quiet work stopped; refuse with a 409 naming what's going ("A dispatch is running", "An evaluation is running", "Round 3 is running"), and for `start_round` also while any round is open, as today; create the run or the round, or record the review; set `heard_at`; commit; ask the agent.
- Quiet work: a run or a round whose `heard_at` is more than five minutes old. `heard_at` is set when the app creates the run or the round or records a review, and by each heartbeat, so it is the later of the two. Quiet work is marked stopped with "The agent stopped answering", a round with its running evaluation, and the new work goes ahead. A round's evaluation is never stopped on its own.
- When the agent didn't take the work: a run is marked stopped with the reason, a new round is stopped with it, and a review is cleared, so the proposal waits for a handler again.
- The agent tells the app every minute while it works: `record_run_heartbeat` for a dispatch or an evaluation it was asked to work, `record_round_heartbeat` for a round, covering the evaluation it is working on, and `record_claim_heartbeat` for a resume.
- `get_run` gives the agent a run by id; `get_proposal` gives it a proposal with its review and the reason, which `carry_round_on` resumes the improver with. The agent no longer creates runs, rounds or reviews, apart from the evaluations a round makes as it goes.
- `round_state.stop()` stops the round's running evaluations with the round's reason, whoever stops it. `finish_run` on a run stopped meanwhile answers with the run and leaves it stopped, so a dispatcher still finishing a run that was stopped ends quietly; finishing a finished run is still a 409.
- Runs record `stopped_because`: the agent's refusal or why it couldn't be reached, the error from `fail_run`, "The agent stopped answering", the round's reason, or why a round's spending limit cut it short. The dispatch panel and the evaluation page show it.

### The app's operations, old and new

| Operation | Route | Who | Phase |
| --- | --- | --- | --- |
| `send_back_claim` | `POST /api/claims/{claim_id}/send-back` | A handler who can sign off over the limit | 2 |
| `take_claim` | `POST /api/claims/{claim_id}/take` | The agent's key | 2 |
| `record_claim_heartbeat` | `POST /api/claims/{claim_id}/heartbeat` | The agent's key | 2 |
| `get_run` | `GET /api/runs/{run_id}` | The agent's key | 4 |
| `record_run_heartbeat` | `POST /api/runs/{run_id}/heartbeat` | The agent's key | 4 |
| `fail_run` | `POST /api/runs/{run_id}/failure` | The agent's key | 4 |
| `get_proposal` | `GET /api/rounds/{round_id}/proposals/{proposal_id}` | The agent's key | 4 |
| `record_round_heartbeat` | `POST /api/rounds/{round_id}/heartbeat` | The agent's key | 4 |
| `fail_round` | `POST /api/rounds/{round_id}/failure` | The agent's key | 4 |

Phase 4 removes `create_dispatch`, `create_evaluation`, `create_round`, `record_review`, `stop_runs` and `stop_rounds`. Every operation keeps an `operation_id`, a one-line docstring and no optional inputs, and `backend/tests/gates.py` lists each new one under its gate. The claim agent's API document keeps its six operations.

### The platform team's folders

`agentcore/agentcore.json` declares the runtime `agent` built from `runtime/` with a 60-second idle timeout and the three credentials; `agentcore/cdk/lib/cdk-stack.ts` stages `runtime/` with `agent/` (no tests) and `uv export --only-group runtime`; `runtime/main.py` imports `app` from `agent.entrypoint` and calls `app.run()`. Reading them, nothing stops the agent working, provided the product does its part: the `runtime` group exists in `pyproject.toml` (the stack's `uv export` fails without it), `agent/entrypoint.py` exports `app`, nothing in `agent/` imports from `backend/` or `context/` outside the tests, and nothing happens at import, since the stack puts the runtime on V2. The implementation reports anything that turns out otherwise rather than editing either folder, and `git diff main -- agentcore runtime` stays empty.

### The tests

- The agent's tests drive the AgentCore app through Starlette's `TestClient` (phase 3), with the checkpoint pool and the workers stood in by monkeypatching what getting ready builds, a stub model, an `InMemorySaver`, and a stand-in for `requires_api_key` that records each provider asked for. They wait for background work by polling `/ping` until it says `Healthy`.
- The backend's stand-in for the agent keeps each payload (phase 3), and a stand-in for the Runtime client raises each botocore exception in turn. No test calls AWS: `conftest.py` deletes `UNDERCOVER_AGENT_RUNTIME` and every `AGENTCORE_CREDENTIAL_*`.
- The backend's test helpers start runs, rounds and reviews through the handlers' operations once the app creates them (phase 4), reading the run or round id from the payload the stand-in got; a test that needs a second run finishes the first.
- Quiet work is made in a test by setting `heard_at` or `resume_heard_at` six minutes back in the database. Same-moment requests are two threads released together from a `threading.Barrier`. One connection a request is counted with SQLAlchemy's pool `checkout` and `checkin` events.
- The heartbeat's interval is a module constant the tests shorten.
- The e2e stand-in gets `PORT`, `UNDERCOVER_API` and `UNDERCOVER_API_KEY`. It answers `/ping`, answers `health`, records every other payload with `{"accepted": true}`, lists them at `/api/started`, and on `POST /api/stop` stops each run and round it was given that's still going, through `fail_run` and `fail_round` with the key, "The test is over". Specs that start work call it after each test.

### Following the notebook

The notebook expects what the brief does: `agent/entrypoint.py` with `BedrockAgentCoreApp`, payloads like `{"operation": "work_run", "run_id": ...}`, `{"operation": "health"}` answering `{"healthy": true}` once the agent has fetched its three credentials from Identity and opened its pool, the database on the transaction pooler, the runtime deployed as `undercover_default_agent`, and `UNDERCOVER_AGENT_RUNTIME` on the app's function with `boto3` in its package. Its part 5 sends CLM-1011 back with a note about Meridian Air's $350 and signs off another claim, which the live checks do on the laptop. Nothing in it differs from the brief, and the plan doesn't run it.

### Checked against the code standards

- One way to call each service: the backend reaches the agent only through `agent_service.py`, where its address, the runtime's ARN, `/invocations` and the boto3 client are written once. The agent reaches the app only through `api.py` and `improver_api.py`, Identity only through `identity.py`, and the memory only through `memory.py`, as now.
- Each module has one job: `entrypoint.py` receives payloads and hands them on; getting the credentials is `identity.py`'s, the heartbeat `heartbeat.py`'s, a handler's answer and the note message `handler_answer.py`'s, the pause the harness's, and the claim's sent-back decisions `sent_back.py`'s. The runs and improvement routers share `agent_work.py` rather than each other's helpers.
- The framework's own way: `BedrockAgentCoreApp`'s entrypoint, async tasks and `/ping`; LangGraph's `interrupt()`, `Command(resume=...)`, `get_state().interrupts` and path maps; a Pydantic discriminated union for the payloads; SQLAlchemy conditional updates for the moves only one caller may make.
- Functions do one job: in the entry point, getting ready, checking the key, reading the payload and starting the work are separate functions, and so are taking the lock, marking quiet work stopped and refusing while work is going in `agent_work.py`.
- Instructions as goals: the note message gives the agent its goal and what done looks like, and the one line in `claim.md` says when a decision changes.
- `CODE_STANDARDS.md` rules 7, 10 and 13 are updated in phase 3, with the entry point, `identity.py`, `heartbeat.py`, `handler_answer.py`, `agent_service.py`'s two routes and `agent_work.py`.

### How the criteria are checked

pytest, vitest and Playwright run with `npm run check` and never read `.env`. Grep checks run from the repo root. The live checks at the end of phase 4 run against Supabase with `npm run dev`, on the default model, on the direct route with no `UNDERCOVER_GATEWAY_URL`, `UNDERCOVER_MEMORY_ID` or `UNDERCOVER_AGENT_RUNTIME`, after one `npm run seed`, signed in as Dana Whitfield through the Playwright MCP server.

## Phase 1: The claim approval comes back

Add `wait_for_handler`, `after_pay`, `paused()`, `resume()` and `handler_answer.answer_of` for a sign-off. Add `resume_claim` to the agent's service, `POST /api/claims/{claim_id}/resume`, 202 or 409, outside `OneAtATime`. Change the `Database` dependency so a route can commit sooner, and make `sign_off_claim` move the claim with a conditional update, commit, and ask the agent to resume it through `agent_service.resume_claim`, logging any failure as a warning. The e2e stand-in records each resume it gets. The live check for this step is at the end of phase 4.

- [x] Stub test: CLM-1003 approved for $3,750.00 ends its graph's run reported `CLM-1003  approve  $3,750.00, waiting for sign-off`, with one interrupt waiting on its thread, which a new graph on the same saver also sees
- [x] Stub test, Gateway route: with the approval limit at $2,000, an approval of $1,500.00 whose payment the Gateway refuses is held with the Gateway's reason, and its thread is paused
- [x] Stub test: an evaluation's copy approved over the limit ends as today: waiting for sign-off, no interrupt, nothing left to run
- [x] Stub test: a claim worked on the command line, with no run, pauses like a dispatch's
- [x] Stub test, stand-in memory: after Dana Whitfield's sign-off pays CLM-1003, `resume` finishes its work: one payment, a `memory_save` step, the stand-in memory holds the claim's two events, and the thread has no interrupt and nothing left to run; with memory off it ends with no `memory_save` step
- [x] pytest (service): `resume_claim` on a paused, signed-off claim answers 202 at once and resumes it in the background on the current version's claim agents, with its work time and model calls recorded with no run
- [x] pytest (service): `resume_claim` refuses with a 409 and the reason a claim still waiting for sign-off, a decided claim that never paused, an evaluation's copy, and a claim whose process stopped after the decision was saved and before the pause ran (its `next` names the pause, but no interrupt waits); an unknown claim gets the app's 404
- [x] pytest (service): `resume_claim` is accepted while a dispatch is running
- [x] pytest (backend): a sign-off pays the claim, records who and when, and makes exactly one call to the agent, naming only the claim; the stand-in, reading the claim through a fresh connection when the call arrives, finds it decided and paid
- [x] pytest (backend): when the call can't connect, times out, is refused or gets an error answer, the sign-off still answers 200 with the paid claim, and a warning names the claim
- [x] pytest (backend): two sign-offs released together pay the claim once; the other gets a 409
- [x] e2e: Dana signs off a held payout on its page, which shows "Paid $1,350.00, signed off by Dana Whitfield", and the agent's stand-in received the resume for that claim
- [x] The boundaries test: `handler_answer` uses nothing else in the agent, and the harness uses it
- [x] `docs/STATUS.md`'s known gaps say that a sign-off whose call to the agent fails, or whose claim never paused, stands, and the claim isn't saved to memory
- [x] `npm run check` passes with `.env` moved out of the way

## Phase 2: Sign off or send back

Add the `sent_back` state and step, `sent_back_decisions`, `resume_heard_at`, `send_back_claim`, `take_claim` and `record_claim_heartbeat`, `sent_back.py` and `agent_work.py`'s `QUIET`. Give `wait_for_handler` its send-back branch and `handler_answer.py` the note message, add `heartbeat.py`, and teach `resume_claim`, `carry_on`, `work_in_run` and the dispatcher about sent-back claims. Build the dashboard's Send back, the sent-back decisions and the new tile. Update `claim.md`'s one line and `SPEC.md`. The live check for this step is at the end of phase 4.

- [x] pytest (backend): `send_back_claim` refuses Marcus Oyelaran with a 403 naming "send this back", an evaluation's copy and a claim not waiting for sign-off with a 409, a blank note and a 1,001-character note with a 422, an unknown claim with a 404, and a request with no sign-in with a 401; a 1,000-character note is accepted
- [x] pytest (backend): a send back of CLM-1008 keeps its decision of $2,240.00 with its calculation, the note, "Dana Whitfield" and the time; clears its decision and its calculation; records a `sent_back` step with the note; leaves the claim sent back; and makes one call to the agent, naming only the claim, after the commit
- [x] pytest (backend): the send back answers with the claim when the call fails or times out, logging a warning
- [x] pytest (backend): a sign-off and a send back released together: exactly one succeeds and the other gets a 409, and the claim is either paid with no sent-back decision or sent back with no payment
- [x] pytest (backend): `take_claim` moves a sent-back claim to in progress on the same thread and attempt for the first caller only; a second call, or a claim that isn't sent back, gets a 409; without the key, a 401. Taken with no run, the claim's summary says `resuming`, and six minutes after its last heartbeat it doesn't; taken by a run, it never does
- [x] pytest (backend): the queue lists a sent-back claim as `sent_back`, and a dispatch's summary counts it as unfinished
- [x] Stub test: a held claim sent back with a note is taken by `resume_claim` and resumed: the model's next input ends with the note message, naming Dana Whitfield; the graph's decision is empty and its model calls start again from zero; a new approval of $890.00, within the limit, is recorded with its own calculation and paid once, and the claim ends decided, with the first decision among its sent-back decisions
- [x] Stub test: a new decision over the limit waits for sign-off and pauses again; a second send back is taken and resumed the same way, leaving two sent-back decisions
- [x] Stub test: a thread that made 29 model calls before its send back can make 30 more before the limit stops it
- [x] Stub test: on a version whose instructions say only "Decide the claim.", the model still gets the note message with the words about a senior handler's review, the policy wording and the claims manual, and a referral when the wording doesn't support the note
- [x] pytest: `claim_as_read` leaves out the sent-back decisions, so the check's input and the claim agent's `get_claim` hold no note
- [x] pytest: `resume_claim` and a dispatch asking for the same sent-back claim at once: one takes it, the dispatch's line says "taken by a resume" when it lost, and the claim gets one new decision
- [x] pytest: a dispatch started while a resume is working on its claim leaves the claim alone; once the resume has been quiet for six minutes, the next dispatch carries it on
- [x] pytest: a send back the agent never got, because the call failed, leaves the claim sent back; the next dispatch takes it, resumes the paused thread with the note, and records a new decision
- [x] pytest: a claim whose process stopped after its decision was saved and before the pause ran, then sent back, is taken by the next dispatch and resumed with the note
- [x] pytest: `heartbeat.beating` calls its function each interval while its block runs and never after, and a failing call is logged without stopping the block
- [x] vitest: a handler who can sign off over the limit sees Sign off and Send back; Send back needs a note and allows 1,000 characters; Marcus Oyelaran sees why he can't; the queue has a Sent back tile; a sent-back claim says it's with the agent; each sent-back decision shows its note, who sent it back and when; a `sent_back` step shows the note
- [x] e2e: Dana sends a held claim back with a note on its page; the page shows Sent back, the sent-back decision with the note and "Sent back by Dana Whitfield", and the note among the steps, and the stand-in received the resume. Then the test, as the agent, takes the claim, works out and records an approval of $900.00 and pays it, and without a reload the page shows the new decision above the sent-back one
- [x] `git diff main -- backend/instructions/claim.md` changes only the sentence that said a decision can't be changed (checked against ec02afd: `main` has no `backend/`)
- [x] The boundaries test: `heartbeat` uses nothing else in the agent
- [x] `docs/SPEC.md` describes the sign-off or the send back, and the claim's states
- [x] `npm run check` passes with `.env` moved out of the way

## Phase 3: The agent as an AgentCore app

Add `bedrock-agentcore`, the `runtime` group and `check:runtime`, and `boto3` to the `server` group. Write `agent/entrypoint.py` and `agent/identity.py`, move the service's operations onto payloads and remove `agent/service.py`. Rewrite `backend/agent_service.py` for the two routes. Move `npm run dev`'s agent to port 8080, the e2e stand-in to `/invocations`, and turn off prepared statements in the checkpoint pool. The live check for this step is at the end of phase 4.

- [x] pytest: in a subprocess with no settings but `PATH` and sockets that refuse to connect, `import runtime.main` succeeds, and `runtime.main.app` is `agent.entrypoint.app` (checked by importing the agent's modules afresh in the test's own process, with the three credential settings named too, since ruff's S603 flags every subprocess call and the rules stay on)
- [x] pytest: on Runtime (`AGENTCORE_CREDENTIAL_OPENROUTER_API_KEY_NAME` and the other two set), the first request asks the stand-in Identity for each provider once, puts each value in its setting, reseeds `random` and opens the pool before it answers; a second request fetches nothing
- [x] pytest: when getting ready fails, the request gets a 503 with the error, and the next request gets ready and is answered
- [x] pytest: `{"operation": "health"}` answers `{"healthy": true}` without the key, and only once the agent is ready
- [x] pytest: each of `start_dispatch`, `start_evaluation`, `start_round`, `review_proposal` and `resume_claim` answers `{"accepted": true}` and its work runs; each start answers `{"refused": "A dispatch is running"}` (or the round's message) while other work holds `OneAtATime`; `resume_claim` refuses a claim that isn't paused
- [x] pytest: an unknown operation, a missing input, an input of the wrong type, an extra input and `agents` of 26 each get a 400 whose `error` says what's wrong
- [x] pytest: `/ping` says `HealthyBusy` while a dispatch is held open, and `Healthy` once it has finished, and again after a dispatch whose work raised
- [x] pytest: off Runtime, a request with no `Authorization` or the wrong key gets a 401 and the right key is accepted; on Runtime, a request with no key is accepted
- [x] pytest (backend), laptop route: the app posts the payload to `http://127.0.0.1:8080/invocations` by default, or `UNDERCOVER_AGENT`'s, with `Authorization: Bearer <key>` and a 10-second timeout
- [x] pytest (backend), Runtime route: with `UNDERCOVER_AGENT_RUNTIME` set, the stand-in client gets the ARN, the payload as JSON, no key, and a session id of at least 33 characters that differs on each call, from a client with one attempt, 5 seconds to connect and 20 to read
- [x] pytest (backend), each route: an acceptance gives a 202; a refusal a 409 with its reason; a failed connection a 503 "The agent's service isn't running"; an error answer a 502; and a timeout or a cut-off answer a 503 telling the handler to reload, recording nothing
- [x] pytest (backend), Runtime route: a response whose `statusCode` is 400 or 500, with the agent's `{"error": ...}` as its body, gives a 502 and counts as not taken, without the body being read as an acceptance or a refusal
- [x] pytest (backend), each route: a whole answer of `{"accepted": false}`, `{"status": "accepted"}` or a body that isn't JSON, with a 200 or a `statusCode` of 200, gives a 502 and counts as not taken
- [x] pytest (backend): a sign-off on the Runtime route sends `{"operation": "resume_claim", "claim_id": "CLM-1008"}`
- [x] pytest: the checkpoint pool's connections have `prepare_threshold` of `None`
- [x] `npm run check:runtime` passes and `npm run check` runs it; `uv export --only-group runtime` lists `bedrock-agentcore`, and the `server` group has `boto3`
- [x] Ruff and pyright check `runtime/main.py` and pass
- [x] `git diff main -- agentcore runtime` is empty, and `agent/service.py` is gone (checked against this branch's starting commit, ec02afd: `main` keeps both folders under `setup/setup_week3day4`)
- [x] `grep -rn "fastapi" agent --include='*.py'` finds only tests; `grep -rln "UNDERCOVER_AGENT\|invocations\|invoke_agent_runtime" backend --include='*.py'` finds only `backend/agent_service.py` and tests; `grep -rln "AGENTCORE_CREDENTIAL_\|requires_api_key" agent --include='*.py'` finds only `agent/identity.py` and tests
- [x] `package.json`'s `dev:agent` serves `agent.entrypoint:app` on port 8080 with reload, and nothing mentions port 8002
- [x] e2e: the stand-in answers `/invocations` and `/ping`, and the queue page's and the Scoreboard's starts and the sign-off reach it as payloads
- [x] `docs/CODE_STANDARDS.md` rules 7, 10 and 13 and `docs/TECH_STACK.md` describe the entry point, Identity, the heartbeat, the two routes from the app and the `runtime` group; `docs/PROCESS.md` describes the agent on port 8080 and the runtime check
- [x] `npm run check` passes with `.env` moved out of the way

## Phase 4: The app keeps one run at a time, then the live checks

Add `runs.heard_at`, `runs.stopped_because`, `rounds.heard_at` and the `locks` table, and the rest of `agent_work.py`. Move the creating of runs and rounds and the recording of reviews into the app's start routes, with the undo, and replace the agent's four starts with `work_run`, `work_round` and `carry_round_on`. Add the heartbeats for runs and rounds, `get_run`, `get_proposal`, `fail_run` and `fail_round`; remove `OneAtATime`, the stops on getting ready and the six operations the agent no longer calls. Show why a run stopped. Then bring the docs up to date and run the live checks.

- [x] pytest (backend): `start_dispatch` creates a running dispatch with its N on the current version, commits it, sends `{"operation": "work_run", "run_id": ...}`, which the stand-in finds running through a fresh connection, and answers 202; `start_evaluation` does the same with the evaluation and its copies
- [x] pytest (backend): `start_round` creates the round and sends `work_round`; `approve_proposal` and `reject_proposal` record the review with who, when and the reason, then send `carry_round_on` with the round and the proposal, and `get_proposal` gives the agent the review and the reason
- [x] pytest (backend): while a dispatch, an evaluation or a working round is going, each start gets a 409 naming it, and a review gets "A dispatch is running" with its proposal still waiting; a round waiting for a handler doesn't stop a dispatch; `start_round` with a round open still gets "Round N is open"
- [x] pytest (backend): two dispatches started at the same moment: one gets a 202 and the other a 409, and one run is recorded
- [x] pytest (backend): a start after a dispatch has been quiet for six minutes marks it stopped, "The agent stopped answering", and goes ahead; a quiet round is stopped with its running evaluation, both with that reason; a round's evaluation whose own `heard_at` is old, in a round heard from lately, stays running
- [x] pytest (backend): when the agent didn't take the work (not running, refused, an error answer), the dispatch or evaluation is stopped with the reason, a new round is stopped with it, and a review is cleared so the proposal waits again and can be approved again; the handler gets the 503, 409 or 502
- [x] pytest (backend): a timeout leaves the dispatch running and gives the 503 to reload; the next start gets a 409 until the dispatch has been quiet for five minutes
- [x] pytest (backend): `start_dispatch`, `approve_proposal`, `sign_off_claim` and `send_back_claim` never hold more than one database connection at once
- [x] pytest (backend): a handler stopping a round stops its running evaluation, "Stopped by Dana Whitfield"; `finish_run` on that evaluation then answers with it, still stopped; finishing a finished run is still a 409
- [x] pytest (backend): `create_dispatch`, `create_evaluation`, `create_round`, `record_review`, `stop_runs` and `stop_rounds` are gone from `/openapi.json`, and the gates test and the API rules test pass
- [x] pytest (agent): `work_run` refuses a run that isn't running, `work_round` a round that isn't open, and `carry_round_on` a proposal with no review, each with the reason
- [x] pytest (agent): while a run, a round or a resume works, the app hears from it each interval, and not after it ends
- [x] pytest (agent): a dispatch whose dispatcher fails is stopped by its id with the error, and an open round waiting for a handler stays open; a round whose work fails is stopped with its running evaluation, and nothing else is
- [x] pytest (agent): getting ready stops nothing: a run that was running before the agent's first request is still running after it
- [x] pytest (agent): the agent itself keeps no one-at-a-time: two `work_run` requests for two running runs are both accepted, and `resume_claim` is accepted beside a dispatch
- [x] pytest (agent): a round started by the app works its first evaluations and its improver to a proposal, and after the app records an approval, `carry_round_on` works the version's evaluations to a verdict, as the round tests do today
- [x] vitest: a stopped dispatch shows "Stopped: The agent stopped answering", and a stopped evaluation's page shows its reason
- [x] e2e: every spec passes with the app creating the runs, the rounds and the reviews; the stand-in stops the work it was given after each test that starts some; starting a dispatch on the queue page while one is running shows "A dispatch is running"
- [x] `grep -rnwE "OneAtATime|stop_runs|stop_rounds|create_dispatch|create_evaluation|create_round|record_review" agent --include='*.py'` finds nothing outside tests (`create_round_evaluation` stays)
- [x] `docs/SPEC.md`, `docs/TECH_STACK.md` (with the Deployment section's agent on Runtime and `UNDERCOVER_AGENT_RUNTIME`), `docs/PROCESS.md`, `docs/CODE_STANDARDS.md` and `docs/STATUS.md` describe the product as it now is, with the known gaps: a sign-off whose resume fails isn't remembered; a sent-back claim whose resumed work fails goes back to the queue and is worked afresh without the note; a claim stopped between its decision's tool call and that step's save, then sent back, records its old decision again without the note
- [x] `npm run check` passes with `.env` moved out of the way

Then the live checks, after one reseed, with Lab 1's `agentcore dev` stopped:

- [x] `npm run seed` prints the 26 claims seeded into the `undercover` schema on Postgres
- [x] With `npm run dev` stopped, `uv run --env-file .env --isolated --only-group runtime python -m runtime.main` serves the agent on port 8080, and `{"operation": "health"}` posted to `http://127.0.0.1:8080/invocations` answers `{"healthy": true}`
- [x] With `npm run dev` running and Dana Whitfield signed in, the queue, a claim, the Scoreboard and the Improvement, Configuration and Settings pages load with no console errors
- [x] A dispatch at N=25 on the queue page works the 26 claims; while it runs, Start a dispatch again shows "A dispatch is running"; it finishes with its summary, every claim decided once and the held payouts listed
- [x] A short script with no model shows an interrupt waiting on the thread of each claim held for sign-off
- [x] CLM-1011, or another held claim if it wasn't held, sent back on its page with a note saying Meridian Air has already paid $350 for the lost bag, is taken by the agent and decided again; its page shows the new decision, the sent-back decision with its note, who sent it back and when, and the note among the steps, in light and dark mode, with no console errors
- [x] Another held claim signed off on its page shows "Paid $..., signed off by Dana Whitfield" at once, and its thread has no interrupt and nothing left to run
- [x] An evaluation of the evaluation set's five tiny claims on the Scoreboard finishes with its measures
- [x] Supabase: no run is left running, every finished run has a `heard_at`, and `sent_back_decisions` holds the one decision sent back with its note
- [x] What it cost: the backend's records for the dispatch, the resume and the evaluation, beside the rise in the OpenRouter key's usage over the same time, in `docs/STATUS.md`'s "Last live run"

## After the branch review

The review of the whole branch changed these, beyond the phases:

- `wait_for_handler` resets the model calls with LangGraph's `Overwrite(0)`.
- Stopping a round is a conditional update, on an open round and, for quiet work, one still quiet, so a round that finished or spoke meanwhile is left as it is. `start_claim` moves a waiting claim conditionally, and a handler's answer reads the claim after its move.
- `agent/work.py` holds the run, round and resume work, which the entry point hands on. The entry point checks the key before it reads a payload, a resume that fails is logged, and the checkpoint pool waits up to 5 seconds for its first connection.
- The e2e start tests check the one payload each start sends and the run or round it names, and the agent's stand-in needs the key.
- A sent-back claim's panel says "Sent back to the agent, which hasn't taken it up yet. The next dispatch works on it.", and a handler who can't sign off over the limit is told they can't send it back either.

## Not in this plan

- A Runtime session for each claim, Langfuse on Runtime, and stopping a Runtime session from the dashboard, as the brief says.
- Creating anything on AWS: `labs/week3day4_lab2.ipynb` deploys the agent, and `agentcore/` and `runtime/` stay as the platform team wrote them.
- Declining a held payout outright, real payments and messages to customers, as `SPEC.md` says.
