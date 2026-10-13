# A swarm of claim agents and a scoreboard

From the head of claims operations, with our IT team.

SIDENOTE: For consistency with the course, please read `labs/week2day4.ipynb` and build the dispatcher in the same style as the lab. Where the lab and this brief differ, follow the brief. Include this sidenote in your plan too.

## Where we're heading

Our claims arrive in batches, and a busy morning brings a whole queue at once. Today the queue agent hands the claims to the claim agent one at a time, so a queue of 25 takes over ten minutes. Choosing which claim goes next is a fixed rule that doesn't need a model.

We also can't see how well the agent is doing. Nobody can say how often it agrees with our handlers, what a claim costs or how long it takes without reading the traces in Langfuse.

Our team's experiment in `labs/week2day4.ipynb` worked the harder claims with up to 25 claim agents at once, using a dispatcher with no model. The run took about as long as its slowest claim, and each claim cost the same as before.

## What we want

1. **A dispatcher in place of the queue agent.** A dispatch works every claim left in progress and every waiting claim, oldest submitted first, with up to N claim agents working at once. Code chooses the claims and keeps track of the run, with no model. Each claim is worked by the claim agent as it is today, with its progress saved, its pause for a sign-off and its recovery after a restart.

2. **Problems are put right.** A claim that hits a rate limit or a timeout waits and carries on from where it got to, as the same attempt, and one that is still hitting them after its waits stays in progress for the next dispatch. A claim that fails with any other error goes back to the queue and the same dispatch tries it once more, and a claim that fails twice is left for a handler, as today. One bad claim never stops the dispatch, and no claim is ever decided or paid twice.

3. **Starting a dispatch from the dashboard.** On the queue page a handler chooses N, the number of claim agents at once, from 1 to 25 with 3 to start with, and starts a dispatch. Only one dispatch or evaluation runs at a time, and a second start is refused while one is running. The run panel shows each of the dispatch's claims and where it stands. When the dispatch finishes, the panel shows a summary built from our records, with no model writing it: how many claims were approved, declined and referred, each payout waiting for a sign-off, and each claim left for a handler or still in progress. If the agent's service isn't running, the start says so.

4. **Cost and time for every claim.** Record the tokens and the cost of each model call, as OpenRouter reports them, and the time the agent spends working on each claim, which leaves out any wait for a handler's sign-off. Record them with the dispatch or evaluation they happened in, or with no run when there is none, so that each run's totals are its own, failed attempts included. The run panel shows the dispatch's model cost and time.

5. **Evaluations.** On a new Scoreboard page, a handler starts an evaluation with N claim agents at once on one of our two labelled sets, whole or just its five `tiny` claims. The evaluation set is the 25 claims of the queue, with the handlers' decisions in `data/evals/decisions.json`. The held-out set is in `data/evals/held_out_claims.json` and `data/evals/held_out_decisions.json`.

   An evaluation works its own copies of the claims, through the same dispatcher and claim agent as a dispatch. The copies never show in the queue, a dispatch never carries them on, and nobody can sign them off: a copy's page has no sign-off form, an approval held for sign-off counts as finished, and its saved progress is cleared. An evaluation that stopped partway shows as stopped.

   Each evaluation records its set, N, the model and the reasoning effort, and for each claim the agent's decision, payout and reason, with its cost and time.

6. **The scoreboard.** The Scoreboard page lists the evaluations, newest first, with the measures from our team's labs: `decision_accuracy` (the agent's decision matches the handler's), `accuracy` (the decision matches and the payout is within a dollar), the cost of mistakes (a wrongful decline costs $1,500, a wrongful approval its payout whether or not it was paid, a needless referral $50, and a wrong amount on a right approval the difference), the straight-through rate (the share of claims not referred), model cost per claim, time per claim and the time for the whole run. A claim the agent didn't decide counts as a referral. Each evaluation opens to its claims, with the handler's decision and payout beside the agent's, the misses easy to spot and each claim linked to its page.

7. **The whole run in Langfuse.** Each claim keeps its own session in Langfuse, as it does today, and every claim's trace is tagged with its dispatch or evaluation, so a whole run can be found together.

8. **GPT-6 Luna by default.** The agent uses `openai/gpt-6-luna` with low reasoning effort by default, the model in our team's labs, in place of DeepSeek V4.1 Flash. `MODEL_NAME` still chooses another model, which runs with no reasoning effort set, and a run records that as none.

## Our IT team's choices

- **The dispatcher** is a fifth part of the agent, `agent/dispatcher.py`, beside the four in `docs/CODE_STANDARDS.md`, and it runs evaluations too. It is a LangGraph graph with no model, as in the lab: a node that lists the claims to work and fans out with one `Send` per claim, and a worker node, with `max_concurrency` set to N. The worker calls one function in the harness with the claim's id and its run, which carries on a claim in progress or starts a waiting one. That function is the only place the dispatcher touches the claim agent, so that later we can point it at the agent in the cloud. Each claim keeps its own thread, as it does today, never a shared thread or a subgraph, because a claim can wait days for a sign-off. The dispatcher saves no progress of its own: each claim saves its own, and the next dispatch finishes what a stopped one left. A dispatch skips a claim the service is already resuming after a sign-off.
- **Retries:** the worker has a `RetryPolicy` whose `retry_on` is LangChain's `ModelRateLimitError` and `ModelTimeoutError`, which the harness function lets through without settling the claim, so a retry carries the claim on from its last saved step. That's safe because the backend never decides or pays a claim twice. When the retries run out, the worker's `error_handler` leaves the claim in progress for the next dispatch, so no error stops the dispatch. Any other error fails the claim as it does today.
- **The checkpointer:** LangGraph's `PostgresSaver` holds a lock around every read and write, so each claim run gets a saver of its own on the process's shared pool. One saver shared by 25 claim agents would make them take turns.
- **Connections:** the claim agents in a process share its connections and wait for one rather than fail. Keep each process at 4 at most, since the free plan allows 15 through the session pooler across all of them.
- **The agent's service** starts dispatches and evaluations. The backend asks it through `backend/agent_service.py`, passing N and the set in the call, and writes nothing the service needs before it. The service answers at once, or refuses with a 409 while a run is going, then creates the dispatch or evaluation through the backend and works in the background. When the service starts, it marks any dispatch or evaluation still running as stopped. The dashboard reaches the service only through the backend, and the claim agent gets no tool for starting a run.
- **The answer key:** seeding stores the held-out claims, out of the queue, and the handlers' decisions in tables of their own, which no claim operation reads. The backend scores each evaluation from its own records, and the agent's service never asks for the decisions. You may open `data/evals/` for this change. Each copy gets a new id, written into its record too.
- **Cost** comes from OpenRouter's `usage.cost` on each model reply, as in the lab, and the claim graph's model node records it through a backend operation.
- **Langfuse:** tag each claim's trace with its run's id, with `langfuse_tags` in the metadata.
- **What goes:** the queue agent and its middleware, `backend/instructions/queue.md`, the to-do list (`write_todos`, its table and its end-to-end test) and `uv run -m agent` without a claim id. Seeding on Supabase drops the old to-do table too. `uv run -m agent CLM-1001` still works one claim. The run panel shows the dispatch's claims, and the instructions page shows the claim agent's instructions.
- **Windows:** everything `npm run dev` starts must work on Windows too (`docs/PROCESS.md`).

## What stays the same

- The rules in `docs/SPEC.md`, including the sign-off for payouts over $1,000. Update its sections on working the queue and on what the team needs to see, and leave its Rules alone.
- The claim agent's graph, tools and instructions, apart from recording cost and time and the default model.
- The API rules in `docs/TECH_STACK.md`: every operation has an `operation_id`, a one-line docstring and no optional inputs.
- Tests never call a model, and the code follows `docs/CODE_STANDARDS.md`.
- `npm run seed` rebuilds everything, as it does today, so it empties the scoreboard too. Evaluations work copies and need no reseed.

## What done looks like

- `npm run check` is green with `.env` moved out of the way. Tests on a stub model cover each new behavior: never more than N claims worked at once; a claim that hits a rate limit carrying on as the same attempt with one decision, and staying in progress without stopping the dispatch when the retries run out; a claim that fails going back and being tried once more in the same dispatch; a second start refused; the summary built from the records; cost and time recorded with their run, leaving out a wait for a sign-off; an evaluation leaving the queue as it was, with its held claims counted as finished and their progress cleared, and its measures matching ones worked out by hand; `get_claim` on an evaluation's copy holding nothing from the handlers' decisions; and a sign-off refused on a copy. The end-to-end tests check that starting a dispatch and an evaluation on the dashboard reaches the stand-in for the agent's service with N, and that the scoreboard shows an evaluation the test plays out through the API, as `e2e/run.spec.ts` does with a run today.
- After one `npm run seed`, with `npm run dev` running and the default model, checked through the Playwright MCP server:
  - Start a dispatch at N=3 and stop it partway with `kill -9` on every process listening on port 8002 (uvicorn's reloader and its worker, from `lsof -ti tcp:8002`, or the Windows equivalent on a Windows machine), which makes `npm run dev` stop the others, then start `npm run dev` again. A dispatch at N=25 then carries on the claims left in progress as the same attempts, and works the rest with 25 at once, which the claims' start times show. Its run takes well under the sum of its claims' times. Comparing claims worked from the start, each takes about as long as the claims did at N=3; if they are slower, report where the time goes, keeping to 4 connections. Claims held for sign-off wait, and a sign-off still pays within five seconds. No claim fails for want of a database connection, and during the dispatch Supabase shows no more than 12 connections whose user is postgres in `pg_stat_activity`, through the Supabase MCP server.
  - An evaluation of the evaluation set at N=25, and one of the held-out set's five `tiny` claims at N=5, appear on the scoreboard with every measure, and the queue page's counts are the same before and after them.
  - Through Langfuse's API, the claims of the N=25 dispatch are found together by its tag.
- `docs/SPEC.md`, `docs/TECH_STACK.md`, `docs/PROCESS.md` (where these runs replace the five-claim cap), `docs/CODE_STANDARDS.md` (rules 10 and 13) and `docs/STATUS.md` describe the product as it now is.

## Planning

Follow `docs/PROCESS.md`, but write this plan to `docs/PLAN_SWARM.md` and tick it off there. Start with the default model and the cost and time, then the dispatcher in place of the queue agent, then starting it from the dashboard, then the evaluations and the scoreboard. For the live runs with the real model, reseed once first and keep to the runs above.
