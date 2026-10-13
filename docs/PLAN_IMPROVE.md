# Plan: an improver for the claim agent, and handlers who sign in

This plan builds what `docs/IMPROVE.md` asks for on top of the swarm and the scoreboard, in seven phases. Each phase leaves `npm run check` green and is committed before the next one starts.

SIDENOTE: For consistency with the course, please read `labs/week2day5.ipynb` and build the judge, the configuration's versions and the improver in the same style as the lab. Where the lab and this brief differ, follow the brief. Include this sidenote in your plan too.

When it's done, our handlers sign in to the dashboard through Supabase Auth, and the backend checks the signed-in handler on every action. The claim agent's instructions, model and reasoning effort are kept in versions, and every dispatch and evaluation records the version it used. A judge, Jev, grades each evaluated claim's explanation against the handler's reason. On a new Improvement page a senior handler runs rounds of the improver, a second agent that follows a recipe: it reads the results, proposes a new version, waits for a handler to approve it, asks for its evaluations, and proposes a better recipe. The backend keeps or rolls back each version by the business's rule, within a spending limit for each round. A Settings page holds the approval limit, the objectives, the noise and tolerance, the spending limit and the agents at once, and a Configuration page replaces the Instructions page. The whole dashboard is brought up to the standard of enterprise software, in light and dark mode.

Phase 7 is the only one that runs the claim agent or the improver on the real model. Phase 4 calls the real judge on the lab's four test explanations and on five claims played out with curl, for well under a cent.

## Design

### Modules

The backend:

- `database.py`: the tables and seeding. `handlers` gains `email`, and `handler_decisions` gains `reason` and `reference`, which seeding reads from `data/evals/`. `settings` becomes a history of the platform's settings, one row per change, and `plans.json` moves to a one-row table of its own, `payout_rules`. New tables: `models_allowed`, `versions`, `recipes`, `rounds`, `proposals`, `improver_calls` and `grades`. `runs` gains `version` and `round_id`. Seeding makes version 1 of the configuration and of the recipe, and the first settings row.
- `auth.py` (new): checks a Supabase access token. It reads `VITE_SUPABASE_URL` once, keeps one `PyJWKClient` on `/auth/v1/.well-known/jwks.json` under it, and returns the token's email when the token is signed by one of those keys, has the audience `authenticated` and hasn't expired. Nothing else reads the address.
- `dependencies.py`: gains `SignedIn`, the signed-in handler, found by the token's email (401 without a valid token, 403 when no handler has that email), and `senior(action)`, which makes the dependency for one action: a signed-in handler who can sign off payouts over the limit, or a 403 that names the action, such as "Only a handler who can sign off payouts over $1,000.00 can change the settings. Marcus Oyelaran can't." FastAPI's `HTTPBearer` reads the token.
- `free_models.py` (new): `free_model()`, the model in `MODEL_NAME` for students on free models, or none. Seeding, the judge and `create_round` use it, so the variable is read in one place in the whole product: the agent takes the claim agent's model from the version and the improver's from the round. Seeding chooses version 1 and the models allowed from it, so `MODEL_NAME` must be set in `.env` before `npm run seed`.
- `lookups.py`: gains finding a round, a version and the current version, and the settings, current or by number, which several routers need.
- `scoreboard.py` (new): what `runs.py`, `improvement.py` and `configuration.py` all need to read runs, moved out of `runs.py`: a run's claims with their cost and time, an evaluation scored against the handlers' decisions with its grades, and a version's scores from the evaluations its rounds ran.
- `diffs.py` (new): the lines that differ between two texts, with two lines of context, from Python's `difflib.unified_diff`, as the lab's `show_changed_lines` does. It serves both versions and recipes.
- `judge.py` (new): Jev, called through OpenRouter's Decisions endpoint with the `openrouter` package and the lab's three questions. The only module that calls the judge, and the only one that knows its address (`JUDGE_URL`, `https://openrouter.ai` by default).
- `verdict.py` (new): the rule that keeps or rolls back a version, as plain functions of two sets of scores and the settings, like `scoring.py`.
- `spending.py` (new): what a round has spent (the improver's calls, its evaluations' model calls and the judge) and the estimate of an evaluation's cost. `main.py`, `runs.py` and `improvement.py` use it.
- `configuration.py` (new router): the claim agent's versions, for the claim agent and the Configuration page, and the settings and models allowed, for the Settings page.
- `improvement.py` (new router): rounds, proposals, recipes and verdicts. The dashboard reads and acts under `/api/improvement`, and only the agent's service writes under `/api/rounds`.
- `runs.py`: gains `create_round_evaluation` under `/api/runs`, grading in `finish_run`, and the version on every run. Its read helpers move to `scoreboard.py`.
- `main.py`: the claim operations, with the signed-in handler on a sign-off and `get_signed_in_handler`. `start_claim` refuses an evaluation's copy once its round is stopped or has spent its limit. `get_instructions` gives way to the versions.
- `agent_service.py`: gains `start_round` and `review_proposal`.
- `models.py`: the new shapes and `StrEnum`s: `RoundStatus`, `RoundStage`, `Verdict`, `ProposalKind`, `Review` and `Grade`.
- `instructions/`: `claim.md` stays as version 1's source. `improver.md` (new) holds the improver's instructions around its recipe, and `recipe.md` (new) the lab's first recipe.

Inside the backend, each router uses `dependencies`, `lookups`, `database` and `models`, and `scoreboard` reads runs for three of them. `runs` uses `scoreboard`, `spending`, `judge`, `scoring` and `agent_service`; `improvement` uses `scoreboard`, `spending`, `verdict`, `diffs` and `agent_service`; `configuration` uses `scoreboard` and `diffs`; `main` uses `spending` and `agent_service`. No router imports another, and `judge`, `verdict`, `diffs` and `scoring` import nothing from the routers.

The agent, in six parts:

- `connection.py` (new): the backend's address, the one `httpx` client, `Refused` and the function that sends a request. `api.py` and `improver_api.py` both use it, so the address is written once.
- `api.py`: the backend's API for the claim agent and the service. It gains `get_version` and `get_current_version`; `create_dispatch` and `create_evaluation` lose the model and reasoning effort, which the backend now takes from the version; `get_instructions` goes. It still has no function that reads scores, grades, settings, rounds or the handlers' decisions.
- `improver_api.py` (new): the backend's API for the improver and the service's round work, one function per operation under `/api/rounds` and `create_round_evaluation`.
- `tools.py`: the claim agent's seven tools, unchanged.
- `harness.py`: builds the claim agent from a version: `model(version)`, `claim_graph(llm, saver, instructions)` and `claim_graphs(version, pool)`. It no longer reads `MODEL_NAME`. `work_in_run` gains the tags for a claim's trace.
- `dispatcher.py`: as today, and `work_run` runs the graph in a fresh `contextvars.Context`, so it is a root run wherever it is called, including inside the improver's tool.
- `improver.py` (new, the sixth part): the improver, a LangChain `create_agent`, with its context, its four tools, its middleware and `work_stretch`, which runs it until it waits for a handler or ends.
- `service.py`: builds each run's claim agents from the run's version. It gains `start_round` and `review_proposal`, and the one-run rule now names what is running.

Inside the agent, `service` uses `improver`, `dispatcher`, `harness`, `api` and `improver_api`; `improver` uses `improver_api` and `connection`; `dispatcher` uses `harness` and `api`; `harness` uses `tools` and `api`; `tools` uses `api`; `api` and `improver_api` use `connection`. The improver reaches the claim agents only through a function the service hands it, which works an evaluation through the dispatcher, so it imports neither `harness` nor `dispatcher`. The claim agent's tools and harness never import `improver_api`.

The dashboard:

- `auth.ts` (new): the only module that uses `@supabase/supabase-js`. It makes the client once from `VITE_SUPABASE_URL` and `VITE_SUPABASE_PUBLISHABLE_KEY`, and offers `signIn`, `signOut`, the session's access token and a way to follow sign-ins and sign-outs.
- `api.ts`: gains a function for each new operation and sends the access token with every request.
- `handler.ts` (new): the signed-in handler for every page, in a React context, and whether anyone is signed in. `components/RequireHandler.tsx` (new) is the guard that sends a visitor who isn't signed in to the sign-in page and loads the handler from `get_signed_in_handler`. (The plan had one `handler.tsx`; the hooks and the component are apart so fast refresh works.)
- `theme.ts` (new): the appearance, light, dark or the same as the computer, kept in `localStorage` and set as `data-theme` on the page before the first render.
- New pages: sign-in, Configuration, a version, Settings, Improvement and a recipe. New shared components: `PageHeader`, `ConfirmDialog`, `DiffView`, `StateMessage` (in place of `Message`), `NotAllowed`, `GradeChip`, `RoundProgress` and `VersionChart`.

### Sign-in

- Handlers sign in on `/sign-in` with their email and password through `signInWithPassword`. There's no sign-up: the users were added by hand in the lab, and sign-ups are off in Supabase.
- Every page but the sign-in page needs a signed-in handler. A visitor who isn't signed in goes to `/sign-in` and comes back to the page they asked for.
- The header shows the handler's name and role, and a Sign out button.
- `api.ts` sends `Authorization: Bearer <access token>` with every request. The backend checks it on every action a handler takes and on `get_signed_in_handler`. Reads stay open, since the agent's service reads without signing in until Week 3.
- The backend fetches Supabase's public keys with `PyJWKClient`, which caches them, and decodes the token with the key's own algorithm and the audience `authenticated`. No Supabase secret is needed. `uv add "pyjwt[crypto]"`.
- Seeding stores each handler's email. `data/handlers.json` sets `can_approve_over_limit` to `false` for Marcus Oyelaran and Priya Raman, so Dana Whitfield is the only senior handler.
- A sign-off records the signed-in handler: `sign_off_claim` takes no body. Signing off a payout over the limit, starting or stopping a round, approving or rejecting a proposal and changing a setting need a senior handler. Starting a dispatch or an evaluation needs any signed-in handler.
- When a handler who can't sign off over the limit looks at a held payout, an open round or the settings, the page says what they can't do and why, such as "Only a handler who can sign off payouts over $1,000.00 can approve the improver's proposals. Marcus Oyelaran can't.", and shows no button for it. The backend refuses it with a 403 as well.

### The configuration in versions

- A version holds the claim agent's instructions, model and reasoning effort, with what changed (its diff from the version before), the reason, who proposed it (the improver and its round), who approved it and when. Version 1 is seeded from `backend/instructions/claim.md` with `openai/gpt-6-luna` at `low`, proposed by "The claims team" with nobody's approval. With `MODEL_NAME` set at seeding, version 1 is that model at `default`.
- The current version is the newest one that was kept, or version 1. A version is under test while its round is open with no verdict, then kept or rolled back. A version whose round stopped before its verdict is rolled back.
- A dispatch, and an evaluation started on the Scoreboard, always uses the current version: the backend records it on the run, with its model and reasoning effort, when the service creates the run. An evaluation in a round uses the version the round is evaluating.
- The service creates the run, reads its version with `get_version`, and builds the claim agents from it: the model at its reasoning effort (`default` means none is sent) and the instructions, which end with the contents of the policy wording and the claims manual, as `get_instructions` gave them. A resume after a sign-off and `uv run -m agent CLM-1001` use the current version.
- `get_version` and `get_current_version`, which the claim agent's client uses, hold the number, the instructions, the model and the reasoning effort, and no scores.
- A version's scores are the averages, on each set, of the finished whole-set evaluations that rounds ran on it. The Scoreboard's own evaluations and any stopped evaluation don't count.

### Settings

| Setting | Starts at | Kept as |
| --- | --- | --- |
| Approval limit | $1,000.00, from `data/company.json` | dollars, above zero |
| Objectives on the held-out set | accuracy 0.6, grade 1.0 | accuracy from 0 to 1, grade from 0 to 3 |
| Noise | accuracy 0.1, grade 0.15, cost per claim 0.15, time per claim 0.15 | zero or more |
| Tolerance | accuracy 0.1, grade 0.15, cost per claim 1.0, time per claim 0.25 | zero or more |
| Spending limit for each round | $0.50 | dollars, above zero |
| Claim agents at once in the improver's evaluations | 25 | 1 to 25 |

- The starting values come from the lab, in a new file, `data/improvement.json`, apart from the approval limit, which stays in `company.json`. Accuracy and the grade are compared as differences, and cost and time as fractions of the old value, so 0.15 means 15% and 1.0 means double.
- `settings` keeps every change as a row: the values, who changed them and when. The newest row is the settings. Every part of the product reads them from there: the approval limit when a decision is recorded, so a new limit applies to the decisions recorded after it, and a round's settings by the number it recorded when it started.
- The models allowed, with their reasoning efforts and prices in dollars per million input and output tokens, are in a new file, `data/models.json`, seeded into `models_allowed`, as in the lab: `openai/gpt-6-luna` (`none`, `low`, `medium`; $0.10 in, $0.50 out), `google/gemini-3.5-flash-lite` (`minimal`, `low`; $0.30, $2.50) and `deepseek/deepseek-v4.1-flash` (`low`; $0.30, $1.20). With `MODEL_NAME` set at seeding, that model at `default` and a price of 0 is the only one. They can't be changed on the page.
- The appearance is the one setting kept in the browser.

### The judge

- `judge.py` holds Jev's id, the lab's rubric and three questions, and one function that asks Jev about one claim. Its state is the handler's decision, reason and reference beside the agent's decision, reason and section: `{"handler": {...}, "agent": {"decision", "reason", "section"}}`, with the questions naming `agent.reason` and `agent.section` where the lab's name `agent.rationale`.
- The call passes `server_url=JUDGE_URL` on each call, since the client ignores an address set on it, `timeout_ms=10_000` and `retries=RetryConfig("none", ...)`. Any error, a timeout included, leaves the claim not graded and is logged. The endpoint is in alpha, so the call is written once, there.
- The grade is Jev's `score`, from 0 to 3. The letter is the level with the highest probability, never the score rounded. The two checks, same grounds and same section, are kept as probabilities and shown as Yes from 0.5.
- `finish_run` grades an evaluation's claims before it finishes, in parallel, one thread per claim, so finishing stays under 20 seconds, well within the 30 seconds `agent/api.py` waits. A claim the agent didn't decide gets an F, with a score of 0 and both checks at 0, without asking the judge. A claim the judge couldn't grade is recorded as not graded. A stopped evaluation isn't graded.
- `grades` holds, for each graded copy, the score, the letter, the two probabilities and the judge's cost, from `usage.cost` in its response.
- An evaluation's grade is the average over its graded claims, and an evaluation with no graded claims has no grade. Its judge cost is shown apart from the claim agents' model cost.
- With `MODEL_NAME` set, the judge isn't called, and every claim shows as not graded.

### How a round works

1. A senior handler presses Start a round on the Improvement page. The backend checks the handler and that no round is open (409, "Round 2 is open. Finish or stop it first."), then asks the agent's service through `agent_service.py`, passing on its refusal.
2. The service takes the one-run lock, or refuses with what is running. In a background task it creates the round with `create_round`, which records the handler, the settings and the recipe as they stand, the current version, the improver's model, a new thread id, and which first evaluations the current version still needs: one on the evaluation set and two on the held-out set, less those it has.
3. The service works the first evaluations through the dispatcher, one at a time, reading the round with `get_round` after each. If the round has been stopped, by a handler or because the spending limit cut one of them short, the service ends the round's work there and lets go of the lock, and the improver never runs. Otherwise it runs the improver until it pauses for a handler or ends (`improver.work_stretch`).
4. When the improver calls `propose_change` with a model and reasoning effort it may use, `HumanInTheLoopMiddleware` pauses it. The service records the proposal with `record_change_proposal`, which gives it an id, and lets go of the lock. While the round waits, dispatches and evaluations can run.
5. The Improvement page shows the proposal: the change to the instructions as a diff, the model and reasoning effort before and after, and the improver's reason. A senior handler approves it, after confirming in a dialog, or rejects it with a reason. The dashboard names the proposal it shows, by its id. The backend checks the handler and that this proposal is the one waiting, refusing with a 409 when it isn't, such as one already reviewed, so a review never lands on a proposal the handler didn't see. Then it passes the review to the service with the proposal and the handler.
6. The service takes the lock, or refuses with what is running and records nothing. It records the review with `record_review`, which refuses with a 409 a proposal that isn't the one waiting, then resumes the improver. A rejection reaches the improver as the tool's answer, with the handler's reason, and it may propose again. On an approval, `propose_change` runs and calls `create_version`, which makes the approved proposal a version under test.
7. The improver calls `run_evaluation`. The tool asks for the version's evaluations one at a time with `create_round_evaluation`, once on the evaluation set and twice on the held-out set, and works each through the dispatcher. The backend refuses the first if the three could cost more than what's left of the round's limit. Then the tool calls `record_verdict`, and the backend keeps or rolls back the version by the rule and returns the verdict and the scores to the improver.
8. The improver calls `propose_recipe`, which pauses in the same way. On an approval, `create_recipe` makes it the current recipe, which the next round follows.
9. When the improver ends, the service calls `finish_round`. A version under test that the improver never evaluated is rolled back. A round in which the improver proposes nothing finishes with no version tried.

A proposal outside the models allowed never reaches a handler: the `when` predicate on `propose_change` returns false for it, so the middleware lets the call through, and the tool answers "openai/gpt-7 at high isn't allowed. Choose from the models allowed." without recording anything. The tool and the predicate share one function that checks a model and reasoning effort against the round's models allowed, and `create_version` refuses one outside them as well.

### The round's stages

The backend works out where a round has got to from its records, so the page reads one field:

| Stage | When | On the page |
| --- | --- | --- |
| `first_evaluations` | The round needs first evaluations and fewer than that have finished | First evaluations, 2 of 3 |
| `improving` | The improver is working toward a change | The improver is working |
| `change_waiting` | A change waits for a handler | A change is waiting for approval |
| `evaluating` | A version under test has no verdict yet | Evaluations, 1 of 3 |
| `verdict` | The verdict is in, and the improver is working toward its recipe | Kept, or Rolled back, with why |
| `recipe_waiting` | A new recipe waits for a handler | A new recipe is waiting for approval |

Then the round is `finished` or `stopped`. A proposal waiting comes first, then a verdict, then a version under test, then first evaluations still needed, then `improving`.

| Round status | Label | Color |
| --- | --- | --- |
| `open` | Open, with its stage | Marigold |
| `finished` | Finished | Sea Green |
| `stopped` | Stopped, with who or what stopped it | Coral |

| Verdict | Label | Color |
| --- | --- | --- |
| `kept` | Kept | Sea Green |
| `rolled_back` | Rolled back | Coral |

### The rule

`verdict.py`, as the lab's `compare` and `keep_or_roll_back`, with the round's settings:

- The new version's scores are the averages of its two held-out runs, and the old ones the current version's scores on the held-out set when the verdict is recorded.
- A version is rolled back when its evaluations were stopped, when the round couldn't afford to evaluate it, when it has no grade, or when it missed an objective. Otherwise it is rolled back when any measure got worse by more than its tolerance, or when no measure improved by more than its noise. It is kept when it meets the objectives, at least one measure improves by more than its noise and none gets worse by more than its tolerance.
- The measures are accuracy, the grade, the model cost per claim and the time per claim. Accuracy and the grade are compared as differences; cost and time as fractions of the old value. The grade is compared only when both versions have one.
- The verdict's reason is in the lab's words: "accuracy improved", "cost_per_claim got worse", "no score improved by more than the noise", "it missed the objectives on grade", "it has no grade", "its evaluations were stopped", "the round couldn't afford to evaluate it", "the round was stopped before its verdict" or "the improver didn't evaluate it".
- A kept version becomes the current version.

### Spending

- A round's spending is its improver's model calls, every model call in its evaluations, its first ones included, and the judge's calls on them.
- The improver is refused an evaluation that is likely to cost more than what's left. `create_round_evaluation` for a version under test estimates the evaluations it still needs, so the first of the three checks all three: their claims times the highest model cost per claim of any finished run on the version's model. For a model with no finished runs, it is the current model's, times the larger of the ratios of their input and output prices. First evaluations aren't estimated, since they come before the improver; the hard limit below still applies to them.
- Once a round has spent its limit, `start_claim` refuses any copy in its evaluations, so no new claim starts. Claims already started finish. `finish_run` marks an evaluation stopped when its round has spent its limit and a copy never started, or when its round was stopped.
- When the limit cuts short one of a round's first evaluations, `finish_run` also stops the round, with the reason "The spending limit cut short its first evaluations", before the improver runs.
- The credit limit on the OpenRouter key, set at the end of the lab, covers the claim agents, the judge and the improver as well.

### Stopping, restarts and one thing at a time

- A senior handler can stop an open round. The backend marks it stopped, with who stopped it and when, rolls back a version under test, and from then on refuses anything the round records: proposals, reviews, versions, recipes, evaluations, verdicts, the improver's calls and the finish, and the start of a claim in its evaluations.
- The improver checks the round before each model call, in a `before_model` hook, and ends the stretch when it is stopped. The service lets go of the lock when the work in hand ends.
- A round stopped before its verdict leaves the current version as it was. A round stopped after its verdict keeps it.
- When the agent's service starts, it marks every running run stopped, as today, and every open round that isn't waiting for a handler, with `stop_rounds`. A round waiting for a handler survives a restart: its proposal is in the backend, and the improver's progress is saved with a `PostgresSaver` on the round's own thread, `durability="sync"`.
- When a stretch fails, the service logs it and stops the round with `stop_rounds`, giving the error as the reason.
- The one-run lock stays a `threading.Lock` in `agent/service.py`, held by a dispatch, an evaluation or a stretch of the improver. The service keeps what holds it, and a start, an approval or a rejection while it is held is refused with a 409 that names it: "A dispatch is running", "An evaluation is running" or "Round 3 is running". The improver's own evaluations run inside its stretch and never take the lock.

### The improver

- `create_agent` on the round's improver model, with a 300 second timeout and 5 retries, as in the lab. `create_round` records `openai/gpt-6-luna` at `medium` reasoning effort, or with `MODEL_NAME` set, that model at `default`, through `free_models.py`. Its system prompt is `backend/instructions/improver.md` around the round's recipe, which `get_round` returns.
- `context_schema=RoundContext`: the round as `create_round` or `get_round` gave it, and `evaluate`, the function that works an evaluation through the dispatcher, which the service binds. The tools read it through `ToolRuntime`.
- Its tools are the lab's four, with the lab's names and docstrings, since the recipe names them. Each calls the backend through `improver_api.py`:
  - `read_results`: `get_improver_view` as JSON.
  - `propose_change(instructions, model, reasoning_effort, reason)`: runs only after an approval, or for a model that isn't allowed. It calls `create_version` and answers "Saved as version 2. Run the evaluation next."
  - `run_evaluation`: as in "How a round works". It answers with the verdict and the scores before and after, or with the backend's refusal.
  - `propose_recipe(recipe, reason)`: runs only after an approval. It calls `create_recipe` and answers "Saved as recipe version 2."
- Middleware:
  - `HumanInTheLoopMiddleware` on `propose_change` and `propose_recipe`, allowing `approve` and `reject`, with the `when` predicate on `propose_change`.
  - `ModelCallLimitMiddleware(thread_limit=20, exit_behavior="error")`, so a round's model calls are capped, counted across restarts, as the claim agent's 30 are.
  - A `wrap_model_call` hook that sets `parallel_tool_calls=False` in the request's model settings, so a reply never holds two proposals.
  - An `after_model` hook that records each call's tokens and cost with the round, from OpenRouter's `usage.cost`, and a `before_model` hook that ends the stretch when the round is stopped.
- Its instructions are goals: improve the claim agent's configuration so that it does better on claims it hasn't seen, within the business's objectives and the round's spending limit, by following the recipe. They say what the claim agent works from: its instructions with the contents of the policy wording and the claims manual, the claim, the policy and the customer's earlier claims, and its tools for searching and reading sections and working out a payout. They say that a change never names a claim, that the held-out claims stay out of sight, and that nothing it proposes takes effect until a handler approves it. The recipe is data the improver follows, so it may be a list of steps, as the lab's is, and `docs/CODE_STANDARDS.md` rule 14 applies to the instructions around it.
- `work_stretch(round, start, evaluate, saver)` invokes the improver on the round's thread, with the first message "Please carry out one round of your recipe." or a `Command(resume=...)` with the review, and returns the proposal it is waiting on, if any, from `__interrupt__`.
- Langfuse: each stretch is a trace named "Improver" in one session per round, `Round 3:<round_id>`. The claims of the round's evaluations are tagged with the round's id as well as their run's.

### What the improver sees

`get_improver_view` returns, as the lab's `read_results` does:

- the current version, without the documents' contents, and its scores on both sets
- from the current version's latest round evaluation on the evaluation set, the claims it got wrong and the five right ones with the lowest grades, each with its original id, the summary, the agent's decision, payout, reason and section, the handler's decision, payout, reason and reference, and the judge's grade, letter and two checks as yes or no
- the earlier rounds: the recipe version, the version tried with its model, reasoning effort and reason, the held-out scores before and after, and the verdict and why
- the objectives, the noise, the tolerance and the rule in words
- the round's spending limit, what it has spent and what's left
- the models allowed

From the held-out set it holds the scores alone: no claim id, summary, reason or decision.

### Tables

| Table | Holds |
| --- | --- |
| `settings` | One row per change: `number`, the values in the settings table above, `changed_by`, `changed_at`. Row 1 is seeded |
| `payout_rules` | One row: `plans.json` |
| `models_allowed` | `model`, `reasoning_efforts`, `input_price`, `output_price` |
| `versions` | `number`, `instructions`, `model`, `reasoning_effort`, `reason`, `proposed_by`, `round_id`, `approved_by`, `approved_at`, `created_at`, `verdict`, `verdict_reason` |
| `recipes` | `number`, `recipe`, `reason`, `proposed_by`, `round_id`, `approved_by`, `approved_at`, `created_at` |
| `rounds` | `number`, `round_id`, `thread_id`, `status`, `settings`, `recipe`, `starting_version`, `first_evaluations` (the sets it needed), `improver_model`, `improver_reasoning_effort`, `started_by`, `started_at`, `finished_at`, `stopped_by`, `stopped_because`, `held_out_before`, `held_out_after` |
| `proposals` | `proposal_id`, `round_id`, `kind` (`change` or `recipe`), the proposal as JSON, `proposed_at`, `review` (`approved`, `rejected` or empty while it waits), `reviewed_by`, `reviewed_at`, `rejection_reason` |
| `improver_calls` | `round_id`, `input_tokens`, `output_tokens`, `cost`, `created_at` |
| `grades` | `claim_id` (a copy), `run_id`, `score` and `letter` (empty when not graded), `same_grounds`, `same_section`, `cost`, `graded_at` |

`runs` gains `version` and `round_id`; `handlers` gains `email`; `handler_decisions` gains `reason` and `reference`. `npm run seed` rebuilds them all, so it takes the configuration and the recipe back to version 1, the settings back to their starting values, and empties the rounds.

### API

New and changed operations of the backend. The others are as in `docs/PLAN_SWARM.md`. Every operation keeps an `operation_id`, a one-line docstring and no optional inputs.

Signing in and claims (`main.py`):

| Operation | Route | Who | What it does |
| --- | --- | --- | --- |
| `get_signed_in_handler` | `GET /api/me` | Signed in | The signed-in handler, with `email` and `can_approve_over_limit` |
| `sign_off_claim` | `POST /api/claims/{claim_id}/sign-off` | Senior | No body. Records the signed-in handler |
| `start_claim` | `POST /api/claims/{claim_id}/start` | | Refuses a copy whose round is stopped or has spent its limit (409) |
| `record_decision` | `POST /api/claims/{claim_id}/decision` | | Holds a payout over the current settings' approval limit |

Runs (`runs.py`):

| Operation | Route | Who | What it does |
| --- | --- | --- | --- |
| `start_dispatch`, `start_evaluation` | as today | Signed in | 401 without a valid token |
| `create_dispatch` | `POST /api/runs/dispatches` | | Body `{agents}`. Records the current version, its model and reasoning effort |
| `create_evaluation` | `POST /api/runs/evaluations` | | Body `{evaluation_set, tiny, agents}`. The same |
| `create_round_evaluation` | `POST /api/runs/rounds/{round_id}/evaluations` | | Body `{evaluation_set}`. A whole-set evaluation for the round's version under test, or before it has one the version it started from, at the round's agents at once. Refuses a round that isn't open, and one that can't afford the version's evaluations, with the estimate and what's left (409) |
| `finish_run` | `POST /api/runs/{run_id}/finish` | | Grades an evaluation's claims; stops one cut short by its round |
| `list_evaluations`, `get_evaluation` | as today | | Gain the version, the round, the grade, the judge cost and each claim's grade and checks |

The configuration and the settings (`configuration.py`):

| Operation | Route | Who | What it does |
| --- | --- | --- | --- |
| `get_current_version` | `GET /api/versions/current` | | For the claim agent: number, instructions with the documents' contents, model, reasoning effort |
| `get_version` | `GET /api/versions/{number}` | | The same for any version |
| `get_configuration` | `GET /api/configuration` | | The current version's number, and every version newest first with its status, lines added and removed, model, reasoning effort, reason, who proposed and approved it, and its scores on both sets |
| `get_version_details` | `GET /api/configuration/versions/{number}` | | One version with its instructions, its diff from the one before, its scores and its round |
| `get_settings` | `GET /api/settings` | | The settings, every change with who made it and when, and the models allowed |
| `change_settings` | `PUT /api/settings` | Senior | Body: every setting. Records them as a new row with the handler |

Improvement for the dashboard (`improvement.py`):

| Operation | Route | Who | What it does |
| --- | --- | --- | --- |
| `get_improvement` | `GET /api/improvement` | | The open or newest round in full, with its stage, progress, a proposal waiting with its diff, its cost against its limit and its evaluations; the rounds newest first; each version tried with its held-out accuracy and grade; the recipe's versions |
| `get_recipe` | `GET /api/improvement/recipes/{number}` | | One recipe version with its diff from the one before |
| `start_round` | `POST /api/improvement/rounds` | Senior | Refuses while a round is open (409); asks the service; 202 |
| `stop_round` | `POST /api/improvement/rounds/{round_id}/stop` | Senior | Marks an open round stopped |
| `approve_proposal` | `POST /api/improvement/rounds/{round_id}/proposals/{proposal_id}/approval` | Senior | Refuses a proposal that isn't the one waiting (409) and one not in the round (404); passes the approval, the proposal and the handler to the service; 202 |
| `reject_proposal` | `POST /api/improvement/rounds/{round_id}/proposals/{proposal_id}/rejection` | Senior | Body `{reason}`, not empty. The same |

Rounds for the agent's service (`improvement.py`), whose writes are refused once the round is stopped:

| Operation | Route | What it does |
| --- | --- | --- |
| `create_round` | `POST /api/rounds` | Body `{handler_id}`. Records a new round, with the improver's model from `free_models.py`, refusing while one is open |
| `get_round` | `GET /api/rounds/{round_id}` | The round as the service needs it: status, thread, the improver's model and reasoning effort, its instructions with the recipe, the models allowed and the first evaluations |
| `get_improver_view` | `GET /api/rounds/{round_id}/results` | What the improver sees |
| `record_change_proposal` | `POST /api/rounds/{round_id}/proposals/change` | Body `{instructions, model, reasoning_effort, reason}`. Refuses while a proposal waits |
| `record_recipe_proposal` | `POST /api/rounds/{round_id}/proposals/recipe` | Body `{recipe, reason}`. The same |
| `record_review` | `POST /api/rounds/{round_id}/proposals/{proposal_id}/review` | Body `{review, handler_id, reason}`. Records the handler's review of the proposal; refuses one that isn't the one waiting (409) and a handler who isn't senior (403) |
| `create_version` | `POST /api/rounds/{round_id}/version` | Makes the approved change a version under test; a repeat returns it |
| `create_recipe` | `POST /api/rounds/{round_id}/recipe` | Makes the approved recipe the current recipe; a repeat returns it |
| `record_verdict` | `POST /api/rounds/{round_id}/verdict` | Keeps or rolls back the version under test and returns the verdict, why and the scores |
| `record_improver_call` | `POST /api/rounds/{round_id}/model-calls` | Body `{input_tokens, output_tokens, cost}` |
| `finish_round` | `POST /api/rounds/{round_id}/finish` | Finishes an open round with nothing waiting |
| `stop_rounds` | `POST /api/rounds/stop` | Body `{reason}`. Stops every open round that isn't waiting for a handler |

`get_instructions` goes. The agent's service gains `start_round` (`POST /api/rounds`, body `{handler_id}`) and `review_proposal` (`POST /api/rounds/{round_id}/proposals/{proposal_id}/review`, body `{review, handler_id, reason}`), each 202 or 409 naming what is running, and `review_proposal` passes on `record_review`'s 409; `start_dispatch` and `start_evaluation` refuse in the same words. `backend/agent_service.py` calls them as it calls a start, passing on a 409 and giving 503 when the service can't be reached.

No response the claim agent's client can read holds a score, a grade, a setting or anything from `handler_decisions`. `get_improver_view` holds the handlers' decisions and reasons on the evaluation set, and only scores from the held-out set.

### Dashboard

Every page follows one layout: a page header with the title, a line on what the page is for and the page's main action on the right; then panels on an 8-pixel spacing scale. Numbers in tables are right-aligned with their units, in JetBrains Mono with tabular figures. A status is a chip with a color and a word. Loading, empty and error states say what to do next, such as "No rounds yet. Start a round to have the improver propose a change." Any action that changes the agent or a setting asks for confirmation in `ConfirmDialog`, built on the `<dialog>` element with `showModal()`. Pages that refresh keep their layout: values change in place, with room kept for chips and messages.

- **Header**: UnderCover, then Queue, Scoreboard, Improvement, Configuration and Settings, with the page you're on marked (`aria-current="page"`). On the right, the handler's name and role and Sign out.
- **Sign-in** (`/sign-in`): a panel with the email and password, Sign in, and Supabase's refusal in an alert, such as "The email or password is wrong." It says there's no sign-up: a manager adds handlers.
- **Configuration** (`/configuration`, and `/instructions` redirects there): the current version's number, model, reasoning effort and held-out scores; every version newest first with its status chip (Current, Kept, Rolled back, Under test), what changed (+12 −3 lines, or the model and reasoning effort before and after), the reason, who proposed and approved it and when, and its held-out accuracy and grade. Each opens its page.
- **A version** (`/configuration/versions/:number`): its details, its diff from the version before in `DiffView`, and its instructions, read only.
- **Settings** (`/settings`): the settings in groups (approval, objectives, noise and tolerance, spending, the improver's evaluations), with "Last changed by Dana Whitfield on Oct 5 at 2:05 PM". Save asks for confirmation, listing each change from the old value to the new. Then the history of changes, the models allowed with their reasoning efforts and prices ("$0.10 in, $0.50 out per million tokens"), and the appearance: Light, Dark or Same as this computer. A handler who can't change the settings sees them read only, with why.
- **Improvement** (`/improvement`): Start a round, or Stop the round while one is open. The open or newest round: its number and status, its stages with where it has got to (`RoundProgress`), who started it, its recipe version, and its cost against its limit. A proposal waiting shows its diff, the model and reasoning effort before and after, and the reason, with Approve, which asks for confirmation, and Reject, which asks for a reason. Both name the proposal shown, and a refusal because it is no longer waiting shows in an alert. Then a chart of the held-out accuracy and grade of each version tried (`VersionChart`, in SVG: two small charts side by side, one point per version, colored by its verdict, with version 1's scores as a line), the rounds newest first (recipe version, version tried, reason, held-out accuracy and grade before and after, verdict and why, who approved or rejected what and when, cost), and the recipe's versions, each opening its page.
- **A recipe** (`/improvement/recipes/:number`): its details, its diff from the one before in the same `DiffView`, and the recipe.
- **`DiffView`**: the lines of a diff, removed lines on a tinted Raspberry background with a − sign, added lines on a tinted Sea Green background with a + sign, context lines plain, a gap between hunks, in JetBrains Mono, with a summary of lines added and removed.
- **The Scoreboard** gains the grade, shown like 2.20, or "Not graded", and the version and round of each evaluation. **An evaluation's page** gains the judge cost beside the model cost, and for each claim a `GradeChip` (A Sea Green, B Cerulean, C Marigold, F Raspberry, or "Not graded"), the score, and Same grounds and Same section as Yes or No.
- **The dispatch panel** says which version a dispatch used. **A claim page** signs off as the signed-in handler, with a Sign off button and no handler to choose.
- **Theme**: `styles.css` sets the dark colors under `:root[data-theme="dark"]` and under `@media (prefers-color-scheme: dark)` for `:root:not([data-theme="light"])`. `theme.ts` sets the attribute from `localStorage` before React renders, so the page never flashes the wrong theme.
- The new pages refresh every two seconds, as the others do, apart from the Settings page, which loads once so a refresh never overwrites what a handler is typing.

### Vite and the environment

`dashboard/vite.config.ts` sets `envDir` to the repo root in the `development` mode alone, and to `false` otherwise. `npm run dev` reads `.env` from the root; Vitest runs in the `test` mode and sets its own values in `test.env`; the end-to-end tests start the dashboard with `--mode e2e` and their own values. So `npm run check` never reads `.env`.

### End-to-end tests

- `e2e/auth_stand_in.ts` (new) stands in for Supabase Auth on its own port. It makes an EC P-256 key pair as it starts, answers `POST /auth/v1/token?grant_type=password` for the three handlers with a test password, with a session whose access token it signs (ES256, audience `authenticated`), serves its public key at `/auth/v1/.well-known/jwks.json`, answers `/auth/v1/user` and `/auth/v1/logout`, and answers the browser's cross-origin checks. It uses `node:crypto` and nothing new.
- `e2e/judge_stand_in.ts` (new) stands in for the Decisions endpoint, answering `POST /api/alpha/decisions` with a fixed answer: a score of 2.2 with B most likely, same grounds 0.8, same section 0.3, and a cost of $0.00002.
- The agent's stand-in also accepts round starts and reviews, and lists them at `/api/started` and `/api/reviews`.
- A Playwright setup project, `e2e/sign_in.setup.ts`, signs in on the sign-in page as Dana Whitfield and as Marcus Oyelaran and saves each browser's storage in `e2e/.auth/`, which git ignores. Every spec runs signed in as Dana unless it chooses Marcus. `e2e/api.ts` gets a token from the stand-in for the actions it sends.
- Playwright's backend gets `VITE_SUPABASE_URL` and `JUDGE_URL` pointing at the stand-ins, a dummy `OPENROUTER_API_KEY`, and empty `DATABASE_URL` and `MODEL_NAME`. The dashboard gets the stand-in's address and a dummy publishable key.
- Only `e2e/improvement.spec.ts` makes rounds, since one round can be open at a time.

### Following the lab

As in the lab: the judge's rubric, its three questions in one call, the score as the grade and the most likely level as its letter; a configuration of instructions, model and reasoning effort, with every change a new version; `difflib.unified_diff` for showing a change; `compare` and `keep_or_roll_back` with the objectives, the noise and the tolerance, cost and time compared as fractions; a new version run once on the evaluation set and twice on the held-out set and judged on its held-out average; the improver as a `create_agent` with `HumanInTheLoopMiddleware` allowing approve and reject, on GPT-6 Luna at medium; its four tools with the lab's names; the lab's first recipe, whose last step improves the recipe; the starting settings and the models allowed; the improver's view of the wrong claims and the five weakest right ones, with nothing from the held-out set but scores; and the rounds as a record of what each tried.

Where the brief differs, we follow the brief:

- Versions, recipes, rounds, settings and grades are records in the backend, in place of lists in the notebook, and the backend applies the rule.
- A round first runs the current version's evaluations if it lacks one on the evaluation set and two on the held-out set, and a version's scores are the averages of its rounds' whole-set evaluations.
- The judge runs in the backend, as part of finishing an evaluation, in parallel, with a 10 second timeout and no retries, and an undecided claim gets an F without asking it.
- The spending limit is for each round and covers the improver, the evaluations and the judge. The estimate uses the highest cost per claim seen for the version's model, scaled by price for a new model, and the backend stops new claims once the limit is spent.
- A proposal outside the models allowed goes back to the improver without pausing, through the middleware's `when` predicate.
- The improver saves its progress with a `PostgresSaver` on a new thread for each round, so a round waiting for approval survives a restart.
- A handler approves or rejects on the dashboard, and a rejection's reason reaches the improver.
- Each round has its own Langfuse session, and its evaluations' claims are tagged with the round.
- The improver's instructions say the claim agent reads the claims manual and the customer's history, which it does in the product.

### Checked against the code standards

- One way to call each service, with each address written once: the claim agent and the service reach the backend through `agent/api.py`, the improver through `agent/improver_api.py`, both over the client in `agent/connection.py`; the backend reaches the agent's service through `agent_service.py`, the judge through `judge.py` and Supabase's keys through `auth.py`; the dashboard reaches the backend through `api.ts` and Supabase Auth through `auth.ts`; the end-to-end tests reach the stand-ins through `e2e/api.ts`.
- Modules keep to their jobs, and helpers two modules need have a module of their own: `scoreboard.py`, `spending.py` and the new lookups in `lookups.py`, in place of routers importing each other, and `connection.py` in place of `improver_api.py` borrowing `api.py`'s client.
- Literals written once: `JUDGE_URL` and Jev's id in `judge.py`; the Supabase address in `auth.py` and `auth.ts`; `MODEL_NAME` in `backend/free_models.py` alone, since the agent takes its models from the version and the round; the stages, statuses and verdicts as `StrEnum`s in `models.py`; `default` for no reasoning effort in the backend's models and the harness, which can't share it; the improver's 20 model calls in `improver.py`.
- The framework's own way: FastAPI's `HTTPBearer` and dependencies for sign-in; PyJWT's `PyJWKClient`; `create_agent` with `context_schema` and `ToolRuntime`, `HumanInTheLoopMiddleware` with its `when` predicate, `ModelCallLimitMiddleware`, and `wrap_model_call`, `before_model` and `after_model` hooks; `PostgresSaver` and `Command(resume=...)`; `difflib`; the `openrouter` client's own timeout and retry settings; `supabase-js` for sessions and refreshing tokens; React context for the signed-in handler; a Playwright setup project and `storageState` for signing in.
- Functions do one job: `work_stretch` runs the improver; the service records what it returns; `record_verdict` reads the scores and `verdict.py` decides; `finish_run` finishes and the judge grades.
- No defensive code beyond what the brief asks: the judge's catch, so a failed grade never stops an evaluation finishing; the service's stop of a round whose stretch failed and its lock release; the tools answering the improver with the backend's refusals, as the lab's tools answer with strings.
- The rules live in the backend, whatever the agent does: the sign-off and its limit, the models allowed, approval before a version or recipe exists, one open round, the spending limit, and the refusal of a stopped round's records.
- The instructions are goals: `improver.md` gives the improver its goal, what it has to work from and what done looks like, and the recipe inside it is data.
- Rule 13 changes for the improver: the agent has six parts, with `tools.py` holding the claim agent's tools and `improver.py` the improver's four, so the claim agent's module has no way to `improver_api.py`.

### How the criteria are checked

API calls run against `npm run dev` on Supabase after `npm run seed`, with a handler's token from Supabase Auth for the actions: `curl -s "$VITE_SUPABASE_URL/auth/v1/token?grant_type=password" -H "apikey: $VITE_SUPABASE_PUBLISHABLE_KEY" -d '{"email": "...", "password": "..."}'` with `HANDLER_PASSWORD` from `.env`. Pages are checked in the browser with the Playwright MCP server at `http://localhost:5173`, signed in as a handler with `HANDLER_PASSWORD`. Tables, connections and Supabase Auth's users are checked through the Supabase MCP server, which is read-only. Tests never call a model, the judge or Supabase Auth, and need no network. Before phase 7, no criterion runs the claim agent or the improver on the real model: rounds and runs are played out through the API with curl, or the start is checked with the agent's service stopped. Phase 4 calls the real judge for its two live checks, and phase 7 runs only what the brief describes, after one `npm run seed`.

## Phase 1: Handlers sign in

Add `auth.py`, `SignedIn` and `Senior`, the handlers' emails, the new permissions in `data/handlers.json`, `get_signed_in_handler`, and the signed-in handler on every action that exists today: `sign_off_claim`, `start_dispatch` and `start_evaluation`. On the dashboard, add `auth.ts`, `handler.tsx`, the sign-in page, the guard on every page, the header's handler and Sign out, the token on every request, and the sign-off as the signed-in handler. Set up Vite's `envDir` and modes. Add the Auth stand-in and the setup project, and sign every end-to-end spec in. Start `PageHeader` and `NotAllowed` here, for the sign-in page and the claim page.

- [x] `uv add "pyjwt[crypto]"` and `npm install @supabase/supabase-js`; `pyproject.toml` and `package.json` list them
- [x] pytest: with a key pair made in the test and Supabase's key fetch replaced by its public key, `get_signed_in_handler` with Dana's token returns Dana Whitfield, Senior Claims Handler, her email and `can_approve_over_limit` true. No token, a token signed by another key, an expired token and one with another audience each return 401, and a valid token for an email with no handler returns 403
- [x] pytest: a test lists every operation that needs a handler, `get_signed_in_handler`, `sign_off_claim`, `start_dispatch` and `start_evaluation`, and checks each returns 401 without a valid token and does nothing; later phases add theirs to the same list
- [x] pytest: `sign_off_claim` as Dana on a held payout records "Dana Whitfield" and the time and asks the service to resume the claim. As Marcus Oyelaran it returns 403 with "Marcus Oyelaran can't sign off payouts over $1,000.00" and changes nothing
- [x] pytest: `start_dispatch` and `start_evaluation` as Marcus are passed to the agent's service, as before
- [x] `uv run -m backend.seed`, then pytest reads the handlers: Dana's `can_approve_over_limit` is true and Marcus's and Priya's are false, each with their email from `data/handlers.json`
- [x] `grep -rn "VITE_SUPABASE_URL\|jwks" backend --include=*.py` finds them only in `backend/auth.py` and its tests, and `grep -rn "supabase-js" dashboard/src` only in `dashboard/src/auth.ts`
- [x] The shared OpenAPI test passes
- [x] vitest, with `auth.ts` stubbed: a visitor who isn't signed in goes from `/scoreboard` to `/sign-in`, and after signing in comes back to `/scoreboard`; a refused sign-in shows the refusal in an alert; the header shows the handler's name and role and Sign out signs out
- [x] vitest: every request `api.ts` sends carries `Authorization: Bearer` and the session's token
- [x] vitest: a held payout shows "Sign off" for Dana and posts no body; for Marcus it shows no button and says "Only a handler who can sign off payouts over $1,000.00 can sign this off. Marcus Oyelaran can't."
- [x] e2e: the setup project signs in as Dana and as Marcus on the sign-in page; every existing spec passes signed in, the sign-off test now signs off as Dana with no handler to choose, and a new test signs out and lands on the sign-in page
- [x] e2e: as Marcus, a held payout shows the explanation and no Sign off button
- [x] `npm run check` passes with `.env` moved out of the way
- [x] Supabase MCP: `select email from auth.users` lists the three handlers' emails, and `curl -s "$VITE_SUPABASE_URL/auth/v1/settings" -H "apikey: ..."` shows `"disable_signup": true`
- [x] With `npm run dev` running after `npm run seed`: `curl -s -X POST localhost:8000/api/dispatches -H 'Content-Type: application/json' -d '{"agents": 3}'` with no token returns 401, and with Marcus's token from Supabase Auth and the agent's service stopped it returns 503
- [x] Browser: `/` goes to the sign-in page; signing in as Dana Whitfield with `HANDLER_PASSWORD` shows the queue with "Dana Whitfield" and "Senior Claims Handler" in the header; a wrong password shows the alert; Sign out returns to the sign-in page
- [x] Browser: with `CLM-1003` approved for 1,350.00 with curl, Marcus Oyelaran sees the explanation on its page, and Dana Whitfield signs it off and sees "Signed off by Dana Whitfield". `npm run seed` afterwards
- [x] Browser: screenshots of the sign-in page in light and dark mode show a rounded panel with no outlines, no one-edge borders and no gradients, and `browser_console_messages` shows no errors

As built:

- `Senior` comes with its first use in phase 3, as `senior(action)`. Until then `sign_off_claim` checks the signed-in handler itself, with the message this phase's criterion names; in phase 3 it moves to `senior(action)`, so seniority is checked one way.
- `get_settings` comes early, with the approval limit alone, so `NotAllowed` can name the limit. Phase 3 gives it the rest.
- `list_handlers` is gone: nothing used it once the sign-off took the signed-in handler, and it would have handed out every handler's email to anyone.
- The backend allows 30 seconds of difference between Supabase's clock and its own, and a Supabase that can't be reached raises its own error rather than a 401.
- The one console entry in the browser checks was the browser's own log of Supabase's 400 for the deliberately wrong password.

## Phase 2: The configuration in versions

Add `versions` and seed version 1, `get_current_version`, `get_version`, `get_configuration` and `get_version_details` in `configuration.py`, `diffs.py`, `free_models.py`, the version on every run, and the claim agents built from the run's version. Remove `get_instructions`. On the dashboard, the Configuration page and a version's page take the place of the Instructions page, with `DiffView`. Scores stay empty until rounds exist.

- [x] `uv run -m backend.seed` prints the counts as today, and "and version 1 of the configuration"
- [x] pytest: version 1 holds the text of `backend/instructions/claim.md`, `openai/gpt-6-luna` and `low`; with `MODEL_NAME=openrouter/free` at seeding it is `openrouter/free` at `default`
- [x] pytest: `get_current_version` and `get_version` for 1 return exactly `number`, `instructions`, `model` and `reasoning_effort`, with the instructions ending in the contents of the policy wording and the claims manual. `get_version` for 9 returns 404
- [x] pytest, `diffs.py`: one line changed in a long text gives one removed and one added line with two lines of context either side; two changes far apart give two hunks; the same text gives no lines
- [x] pytest: with a version 2 kept, added by a test helper, `get_current_version` is 2; a version 3 under test leaves it at 2; `get_configuration` lists 3, 2 and 1 with their statuses and lines added and removed; `get_version_details` for 2 holds its diff from 1
- [x] pytest: `create_dispatch` and `create_evaluation` record the current version with its model and reasoning effort, and `get_latest_dispatch`, `list_evaluations` and `get_evaluation` show it
- [x] Stub model test, through the agent's service: with version 2 current, on another model and with other instructions, a dispatch's claim agents get version 2's instructions as their system message and the run records version 2's model; `uv run -m agent CLM-1001` (with the pool and the claim stubbed) uses the current version, and so does a resume after a sign-off
- [x] pytest: a version with reasoning effort `default` builds a model with no reasoning effort, and one with `medium` builds one with `medium`; with `MODEL_NAME` set in the agent's environment, the harness still builds the version's model
- [x] `grep -rn MODEL_NAME agent --include=*.py` finds nothing outside `agent/tests/`, and in `backend` only `backend/free_models.py` and the tests
- [x] `grep -rn "get_instructions\|getInstructions\|InstructionsPage" backend agent dashboard/src e2e` finds nothing
- [x] The test that `agent/api.py` can't read the scoreboard also checks it has no function for `get_configuration` or `get_version_details`
- [x] The shared OpenAPI test passes for the backend and the agent's service
- [x] vitest: the Configuration page shows the current version's number, model and reasoning effort, and a table of versions with status chips; a version's page shows a stubbed diff with removed and added lines marked; `/instructions` lands on `/configuration`; the header links to Configuration and marks it as the current page
- [x] e2e: the header's Configuration link opens the page, which shows version 1 as Current and its instructions, including "10. How we work out your payment"
- [x] `npm run seed`, then Supabase MCP: `versions` has one row, and `runs` has `version` and `round_id`
- [x] Browser: the Configuration page and version 1's page in light and dark mode, with no errors in `browser_console_messages`, and the dispatch panel says a dispatch played out with curl used version 1. `npm run seed` afterwards
- [x] `npm run check` passes

As built:

- Each version records `based_on`, the version that was current when it was proposed, and its diff and "what changed" are from that version. After a version is rolled back, the next one is proposed against the current version, not the one rolled back.
- Version 1 is seeded with the verdict "kept", so the current version is simply the newest kept one.
- `scoreboard.py` comes in this phase, since the Configuration page reads a version's scores; with no rounds yet they stay empty.
- `agent/openrouter.py` builds a model on OpenRouter at a reasoning effort, with `default` meaning none is sent. The harness uses it now and the improver will too, so the address and `default` are written once in the agent.
- `StateMessage` takes the place of `Message` on every page now, rather than in phase 7. An error the backend refused, such as a sign-in that isn't a handler's, isn't offered a reload.

## Phase 3: Settings

Rework `settings` as a history and move the plans to `payout_rules`. Add `data/improvement.json`, `data/models.json`, `models_allowed`, `get_settings` and `change_settings`, and read the approval limit from the current settings. On the dashboard, add the Settings page with `ConfirmDialog`, and the appearance with `theme.ts` and the theme attribute in `styles.css`.

- [x] pytest: seeding makes settings row 1 with the approval limit from `company.json` and the rest from `data/improvement.json`, with no one as its author, and the three models allowed from `data/models.json` with their prices as numbers; with `MODEL_NAME=openrouter/free`, `openrouter/free` at `default` and a price of 0 is the only model allowed
- [x] pytest: `change_settings` as Dana records row 2 with "Dana Whitfield" and the time, and `get_settings` returns it with the history and the models allowed. As Marcus it returns 403 with "Only a handler who can sign off payouts over $1,000.00 can change the settings. Marcus Oyelaran can't." and records nothing. Without a token it returns 401
- [x] pytest: an approval limit of 0, an accuracy floor of 1.5, a grade floor of 4, a negative noise, a spending limit of 0 and 26 agents at once each return 422
- [x] pytest: with the limit raised to $1,500.00, an approval of 1,350.00 recorded afterwards is paid without a sign-off, while one recorded before the change stays waiting for sign-off; with it lowered to $500.00, an approval of 600.00 waits, and `pay_claim` refuses it with "A payout over $500.00 needs a handler's sign-off"
- [x] `grep -rn "payout_approval_limit" backend --include=*.py` finds it only in seeding and its tests, and `grep -rn 1000 backend --include=*.py` still finds nothing outside the tests
- [x] The shared OpenAPI test passes, and `change_settings` is in the list of operations that need a handler
- [x] vitest: the Settings page shows each setting with its unit and "Last changed by"; Save opens the dialog listing each change from old to new, Cancel sends nothing, Confirm sends every setting; a refusal shows its detail; Marcus sees the settings read only with why; the models allowed show their prices right-aligned; the appearance choice sets `data-theme` and keeps it in `localStorage`, and Same as this computer removes it
- [x] vitest: `ConfirmDialog` is a modal `<dialog>` with a title, the changes and two buttons, and closes on Cancel and Escape, with `showModal` stood in for in jsdom
- [x] e2e: as Dana, changing the spending limit to $0.75 and confirming shows $0.75 and "Last changed by Dana Whitfield" after a reload; as Marcus, the page has no Save button and says why
- [x] e2e: choosing Dark sets `data-theme="dark"` on the page and the background to `#04232E`, which stays after a reload; Light sets `#F0F4F5` under a dark system setting (`page.emulateMedia`)
- [x] `npm run seed`, then Supabase MCP: `settings` has one row with the starting values, `payout_rules` one row, and `models_allowed` three rows
- [x] Browser: as Dana, raise the approval limit to $1,500.00 with the dialog, then with curl approve `CLM-1004` for 1,350.00: it is paid without a sign-off. `npm run seed` afterwards
- [x] Browser: the Settings page in light, dark and Same as this computer, with no errors in `browser_console_messages`
- [x] `npm run check` passes

As built:

- Dark mode uses CSS `light-dark()`, with `color-scheme` set to `light dark` for the computer's choice and to one of them by `data-theme`, so each color is written once rather than twice under two selectors.
- Save sits in a bar at the top of the form, beside "Last changed by", since it needs the form's state.
- `sign_off_claim` now uses `senior(action)` like every other senior action, so its refusal reads "Only a handler who can sign off payouts over $1,000.00 can sign this off. Marcus Oyelaran can't.", as the dashboard says.
- `dollars()` moved to `backend/money.py`, since `main.py` and `dependencies.py` both need it.
- Each decision records the approval limit in force when it was recorded, so a payout held under $1,000.00 is still refused as "A payout over $1,000.00 needs a handler's sign-off" after the limit is raised.
- The Settings page checks each setting in the browser before it asks (required, with its range and step), keeps a setting the handler didn't touch exactly as it was, and shows FastAPI's own reason when the backend refuses one.

## Phase 4: The judge

Seed the handlers' reasons and references. Add `judge.py`, `grades`, grading in `finish_run`, the grade and the judge cost in the measures, and the judge's stand-in. On the dashboard, the grade on the Scoreboard, and each claim's grade and checks on an evaluation's page.

- [x] pytest: seeding stores a reason and a reference for all 50 handlers' decisions, and `get_claim` and every response the claim agent's client can read still hold neither
- [x] pytest, with the judge's client on an httpx `MockTransport` answering like the Decisions endpoint: the request goes to `JUDGE_URL` plus `/api/alpha/decisions` with Jev's id, the handler's decision, reason and reference, the agent's decision, reason and section, and the three questions, and a 10 second timeout
- [x] pytest: a score of 1.5 with probabilities 0.4, 0.05, 0.2 and 0.35 for F, C, B and A gives the letter F, not the B the score would round to; the two checks keep their probabilities, and 0.5 or more shows as yes
- [x] pytest: a judge that times out, answers 500 or answers without the grade leaves the claim not graded after one request, and the evaluation still finishes
- [x] pytest: an evaluation of 25 copies with a judge that takes 0.3 seconds a call finishes in under 2 seconds, and each graded copy has its grade and cost in `grades`
- [x] pytest: an undecided copy gets F, a score of 0 and both checks at 0 without a call to the judge; an evaluation's grade averages its graded copies and leaves out a copy not graded; with none graded it has no grade; its judge cost is the sum of its grades' costs and isn't in its model cost
- [x] pytest: with `MODEL_NAME` set, finishing an evaluation makes no call to the judge and every copy is not graded
- [x] pytest: a stopped evaluation isn't graded
- [x] `grep -rn "typesafe/jev\|JUDGE_URL\|alpha.decisions" backend agent --include=*.py` finds them only in `backend/judge.py` and its tests
- [x] The shared OpenAPI test passes
- [x] vitest: the Scoreboard shows the grade as 2.20 or "Not graded"; an evaluation's page shows each claim's grade chip and score, Same grounds and Same section as Yes or No, and the judge cost
- [x] e2e: the evaluation played out through the API in `e2e/scoreboard.spec.ts` shows the stand-in's grade, 2.20 with B on each decided copy and F on the undecided one, and the judge cost
- [x] Live, judge only: `uv run --env-file .env python -c` calling the judge on the lab's four explanations for CLM-1001 gives the handler's own reason a B or an A, the reason from CLM-1003 an F, the vague one a C or an F, and the clearer one an A, for under $0.001 in all
- [x] `npm run seed`, then Supabase MCP: `handler_decisions` has 50 rows with a reason and a reference, and `grades` is empty
- [x] Live, judge only: an evaluation of the held-out set's tiny claims, played out with curl with one copy left undecided, finishes in under 20 seconds with four copies graded by Jev and the undecided one an F, and the Scoreboard and its page show the grade and the chips in light and dark mode. `npm run seed` afterwards
- [x] `npm run check` passes

As built:

- Live, on the lab's four explanations for CLM-1001, Jev gave the handler's own reason B (2.02), the reason from CLM-1003 F (0.01), the vague one C (0.77) and the clearer one A (2.92), for $0.0001 in all.
- Live, the held-out set's tiny claims, played out with curl with four copies referred and one left undecided, finished in 0.5 seconds: Jev graded the four (all F, since the handlers decided otherwise) and the undecided one got an F without a call, with a judge cost of $0.0001.
- A column of panels now keeps a wide table scrolling inside its panel, which the evaluation page needed at 1280 pixels.

## Phase 5: The improver

In the backend: `recipes` and version 1 of the recipe, `rounds`, `proposals`, `improver_calls`, the verdict on `versions`, `scoreboard.py`, `verdict.py`, `spending.py`, the service's operations under `/api/rounds`, `create_round_evaluation`, the refusals for a stopped or spent round in `start_claim` and `finish_run`, and `start_round`, `stop_round`, `approve_proposal`, `reject_proposal` and `get_improvement` for the dashboard. In the agent: `connection.py`, `improver_api.py`, `improver.py`, `start_round` and `review_proposal` in the service, the lock that names what is running, `stop_rounds` at startup, and the round's tag on its claims. The improver's tests run on a stub model that keeps a script of tool calls, and a stub judge.

- [x] `uv run -m backend.seed` also makes version 1 of the recipe from `backend/instructions/recipe.md`
- [x] pytest, `verdict.py`, with the old version at accuracy 0.60, grade 1.50, $0.0010 and 20 seconds a claim, and the lab's noise and tolerance: 0.72, 1.50, $0.0019 and 24 s is kept, "accuracy improved"; 0.72, 1.50, $0.0021 and 24 s is rolled back, "cost_per_claim got worse"; 0.60, 1.50, $0.0008 and 20 s is kept, "cost_per_claim improved"; 0.68, 1.60, $0.0010 and 20 s is rolled back, "no score improved by more than the noise"; 0.72, 0.90, $0.0010 and 20 s is rolled back, "it missed the objectives on grade"; 0.72 with no grade is rolled back, "it has no grade"
- [x] pytest: a version's scores average only the finished whole-set evaluations its rounds ran: with a round's evaluations at 0.6 and 0.7 on the held-out set, a Scoreboard evaluation at 0.2 and a stopped round evaluation at 0.0, its held-out accuracy is 0.65; a run with no graded claims leaves the grade to the others
- [x] pytest: `get_improver_view` holds the current version, its scores, the wrong claims and the five right ones with the lowest grades with the handlers' reasons, the earlier rounds, the settings, the rule, the spending and the models allowed; nothing in it names a held-out claim or holds a held-out reason, reference, decision or summary
- [x] pytest: a recorded change proposal changes nothing: the current version and `get_configuration` are as before, and `create_version` returns 409. After an approval `create_version` makes version 2, under test, with the improver's reason, "Round 1" as its proposer and Dana as its approver, and the current version is still 1; a second call returns version 2 again
- [x] pytest: `create_version` refuses a model outside the models allowed with 422, and `record_review` refuses Marcus with 403
- [x] pytest: with a change proposal rejected and a second one waiting, `approve_proposal` and `reject_proposal` naming the first return 409, ask nothing of the agent's service and leave the second waiting; naming a proposal of another round returns 404; `record_review` naming the first returns 409 and records nothing
- [x] pytest: `create_round` records `openai/gpt-6-luna` at `medium` as the improver's model, and with `MODEL_NAME=openrouter/free` that model at `default`; `get_round` returns it
- [x] pytest: `create_round` refuses while a round is open; `start_round`, `stop_round`, `approve_proposal` and `reject_proposal` are in the list of operations that need a handler, and each returns 403 for Marcus with what he can't do and why
- [x] pytest, spending: with the highest cost per claim on GPT-6 Luna at $0.002, a round with $0.10 of its $0.50 left is refused its version's evaluations with "The evaluations could cost about $0.15, and $0.10 of the round's limit is left", and the verdict then rolls the version back, "the round couldn't afford to evaluate it". A version on `google/gemini-3.5-flash-lite`, with no runs, is estimated at 5 times Luna's cost per claim
- [x] pytest, spending: once a round's improver calls and its evaluation's model calls reach its limit, `start_claim` on another copy in its evaluation returns 409 and the copy stays waiting; `finish_run` marks the evaluation stopped, and the verdict rolls the version back, "its evaluations were stopped"
- [x] Stub model test, through the agent's service: a round with a spending limit that one first evaluation's claims use up has that evaluation stopped and the round stopped, "The spending limit cut short its first evaluations"; the round's other first evaluations aren't created, the improver makes no model call, and the next dispatch starts
- [x] pytest: a round started with settings row 1 keeps its spending limit and agents at once after a change makes row 2
- [x] pytest: stopping a round with version 2 under test leaves version 1 current and version 2 rolled back, "the round was stopped before its verdict"; the round's proposals, reviews, versions, evaluations, verdict and improver calls are refused with 409 afterwards, and so is the start of a claim in its evaluation. A round stopped after its verdict kept version 2 leaves version 2 current
- [x] pytest: `get_improvement` gives each stage of the table in the design at the point a round reaches it, with the progress "2 of 3" during evaluations
- [x] Stub model test, through the agent's service: a round started on a fresh database runs the first evaluations, one on the evaluation set and two on the held-out set, and the improver reads its results and proposes a change. The service records the proposal and lets go of the lock, and the round waits at `change_waiting` with the diff
- [x] Stub model test: a rejection with the reason "Keep each rule general" reaches the improver as the answer to `propose_change`; it proposes again, and an approval makes version 2. `run_evaluation` runs it once on the evaluation set and twice on the held-out set at the round's agents at once, and the verdict keeps it, so version 2 is current. The recipe proposal is approved, recipe 2 is current, and the round finishes with its cost the sum of the improver's calls, the evaluations' model calls and the judge
- [x] Stub model test: a proposal of `openai/gpt-7` goes back to the improver with "isn't allowed" and records no proposal, and the improver's next, allowed proposal waits for a handler
- [x] Stub model test: an approval while a dispatch runs returns 409 with "A dispatch is running", records no review, and leaves the proposal waiting; a start of a round while an evaluation runs returns 409 with "An evaluation is running"; a dispatch while a round waits for a handler starts
- [x] Stub model test: a round waiting for approval survives the service's lifespan running again, and its approval resumes the improver from its saved progress; a round in its first evaluations when the lifespan runs is stopped
- [x] Stub model test: stopping a round during its evaluations starts no more of its claims, makes no more improver calls, and lets the next dispatch start once the claims in hand finish
- [x] Stub model test: the improver stops after 20 model calls in a round, counted across an approval, and the round is stopped with the reason
- [x] Stub model test: a round whose improver proposes nothing finishes with no version tried
- [x] Stub model test: the claims of a round's evaluations have `langfuse_tags` with their run and the round, and each stretch of the improver is traced as "Improver" in the session `Round 1:<round_id>`
- [x] Stub model test: the improver is built from the round's model and reasoning effort, with `MODEL_NAME` unset in the agent's environment
- [x] `grep -rn MODEL_NAME backend agent --include=*.py` finds it only in `backend/free_models.py` and the tests
- [x] A pytest test checks that `agent/api.py` has no function for any operation under `/api/rounds`, `/api/improvement`, `/api/configuration` or `/api/settings`, or for `list_evaluations` or `get_evaluation`; that `agent/tools.py` and `agent/harness.py` don't import `improver_api`; and that `improver.py` imports neither `harness` nor `dispatcher`
- [x] `grep -rn "BACKEND_URL\|UNDERCOVER_API" agent --include=*.py` finds them only in `agent/connection.py`
- [x] `grep -rn "held_out" agent --include=*.py` finds no read of the held-out set's decisions
- [x] The shared OpenAPI test passes for the backend and the agent's service
- [x] With `npm run dev` running after `npm run seed`: a round created with curl (`create_round`) shows in `curl -s localhost:8000/api/improvement` at `first_evaluations`, `start_round` with Dana's token returns 409 while it's open, and after `stop_rounds` the round is stopped. With the agent's service stopped, `approve_proposal` naming a proposal recorded with curl returns 503, and naming a made-up proposal id returns 404. `npm run seed` afterwards
- [x] `npm run seed`, then Supabase MCP: `rounds`, `proposals`, `improver_calls` and `grades` are empty, and `recipes` and `versions` have one row each
- [x] `npm run check` passes

As built:

- The averaging test has the round's held-out evaluations at 0.60 and 0.72 (15 and 18 of 25 right), so its accuracy is 0.66: 0.7 can't be reached on 25 claims. The stopped evaluation is round 1's last first evaluation, and round 2 runs the held-out evaluation version 1 still needs.
- The held-out set's references, such as "Policy wording, section 5", are the same words as the evaluation set's, so the test that the improver reads nothing from the held-out set looks for its claims' ids and summaries and the handlers' reasons. A decision is one of three words, so it can't be looked for either.
- A round runs only the evaluations its versions need: its starting version's first evaluations, then three of its version under test until the verdict. Any other is refused with a 409, so a version's scores never change after its verdict, and an improver that calls `run_evaluation` twice is told "Round 1 has no version under test".
- A proposal the backend refuses, such as a second change after the verdict, goes back to the improver as a rejection with the backend's reason, in place of stopping the round.
- A model call answered just as a handler stops the round can't be recorded, since a stopped round records nothing more, so the stretch ends there quietly. That one call is missing from the round's cost, which `docs/STATUS.md` lists as a known gap.
- A copy's `start_claim` in a stopped round is refused with "Round 1 is stopped", the same words as the round's other refusals, and in a round that has spent its limit with "Round 1 has spent its limit of $0.50".
- The agent's round tests set the noise and tolerance on time far wider than any run's time, since the stub claim agents' time is real and once counted as an improvement under load.
- Live, with `npm run dev` after `npm run seed`: round 1, created with curl, showed at `first_evaluations` with "0 of 3"; `start_round` with Dana's token returned 409 "Round 1 is open. Finish or stop it first."; `stop_rounds` stopped it with its reason. With the agent's service stopped, `approve_proposal` returned 503 for a proposal recorded with curl and 404 for a made-up one. After `npm run seed`, `rounds`, `proposals`, `improver_calls` and `grades` were empty and `recipes` and `versions` had one row each.

## Phase 6: The Improvement page

Add the Improvement page and a recipe's page, with `RoundProgress`, `VersionChart` and the shared `DiffView` and `ConfirmDialog`, and the round starts and reviews to the agent's stand-in.

- [x] vitest: with no rounds, the page says "No rounds yet." with what Start a round does; Start a round posts once and shows a refusal's detail; Stop the round shows while a round is open
- [x] vitest: a round at each stage shows where it has got to, with "First evaluations, 2 of 3" and "Evaluations, 1 of 3"; a finished round shows its verdict chip and why; a stopped one says who or what stopped it
- [x] vitest: a change waiting shows its diff, the model and reasoning effort before and after and the reason; Approve opens the dialog and Confirm posts the approval to the proposal shown, by its id; Reject needs a reason and posts it to the same proposal; a 409 such as "A dispatch is running" or one for a proposal no longer waiting shows in an alert; a recipe waiting shows the recipe's diff in the same `DiffView`
- [x] vitest: as Marcus, a waiting proposal shows no Approve or Reject, and Start a round is replaced by what he can't do and why
- [x] vitest: the rounds table shows the held-out accuracy and grade before and after, right-aligned, the verdict, who approved or rejected what and when, and the cost against the limit; the chart draws one point per version tried in each of its two charts, colored by verdict, with version 1's line, and labels its axes
- [x] e2e: a round created through the API, with a change proposal recorded, shows "A change is waiting for approval" and its diff; approving it as Dana, with the dialog, reaches the agent's stand-in at the round's and the proposal's review path with `{"review": "approved", "handler_id": "HND-01", "reason": ""}`; once the test records the review and the version as the service would, the page moves on to "Evaluations, 0 of 3" without a reload
- [x] e2e: rejecting a recipe proposal with a reason reaches the stand-in with the reason; as Marcus the proposal shows no buttons
- [x] Browser: with a round played out with curl to a waiting change, the page in light and dark mode at 1280 by 800 and 1440 by 900, with the diff readable, the chart's labels clear and no horizontal scroll outside its tables, and no errors in `browser_console_messages`. `npm run seed` afterwards
- [x] `npm run check` passes

As built:

- The browser check played two rounds out against the dev backend with a script sending the agent's service's requests, as curl would: round 1 ran its first evaluations and version 2's, which was rolled back ("it missed the objectives on accuracy, grade"), and round 2 waited with a change to Gemini 3.5 Flash Lite. Most copies were left undecided, so the judge graded only the 18 decided ones, for $0.0005.
- Each chart is drawn at 520 by 220 pixels and shrinks on a narrow screen: drawn to its panel's width, its labels came out too big.
- The rounds table has no column of its own for the status: the chip sits beside the round's number, with the stage under it while the round is open, so the table fits at 1280 pixels without scrolling.
- A refusal of a review is kept by the page, so it stays on screen once the proposal it was for is no longer waiting, and a quiet button on a panel takes the inset color, so Reject keeps its shape.

## Phase 7: The whole dashboard, the live runs and the docs

Bring the existing pages up to the standard of the new ones: the same `PageHeader` and spacing on every page, `StateMessage` for loading, empty and error states with what to do next, tables that line up with their units, buttons that look alike, and nothing that moves as a page refreshes. Nothing on the existing pages changes how it works. Then run the live checks the brief describes, have a fresh subagent review the screenshots as a senior product designer, fix what it finds, and bring the docs up to date.

- [x] vitest: every page has a `PageHeader` with a title and a line on what the page is for; every table's numeric columns have the `num` class; every loading, empty and error state on the existing pages uses `StateMessage` and says what to do next
- [x] Browser, with `browser_evaluate`: on the queue, a claim in progress, the Scoreboard, an evaluation and the Improvement page, a `PerformanceObserver` collects no `layout-shift` entries over three refreshes
- [x] Browser, with `browser_evaluate`: every button on every page has the same height, radius and font, and the page header's title, the panels' left edges and the tables' first columns line up at 1280 by 800
- [x] Live: the OpenRouter key has a credit limit (`curl -s https://openrouter.ai/api/v1/key`), and after one `npm run seed`, with `npm run dev` running and the default model, signed in as Dana Whitfield: round 1, started on the Improvement page, runs its first evaluations and shows each as it happens; the first proposal is rejected with a reason, the next is approved, and its evaluations, verdict and recipe proposal show as they happen; the recipe is approved and the round finishes
- [x] Live: round 2 runs on recipe 2; its change and recipe are approved, and it finishes
- [x] Live: the rounds show the held-out scores before and after, the verdict and why, who approved or rejected what and when, and the cost; the Configuration page shows the versions with their diffs and held-out scores; the Improvement page shows the recipe's versions and their diffs
- [x] Live: through Langfuse's API, each round's improver traces are in its own session, and `trace.list(tags=[round_id])` finds its evaluations' claims
- [x] Live: report how far version 1's two held-out runs differed on each measure, beside the noise and the tolerance
- [x] Live: a dispatch at N=25 started on the queue page runs on the current version and finishes; signed in as Marcus Oyelaran, a payout waiting for sign-off can't be signed off and the settings can't be changed, each saying why; signed in as Dana Whitfield, the same payout is signed off and shows paid within five seconds
- [x] Live: report what the live checks spent, from the backend's records and the OpenRouter key's usage; on GPT-6 Luna it comes to under $1
- [x] Screenshots of every page in light and dark mode at 1440 by 900: the sign-in page, the queue, a claim, a held payout as Dana and as Marcus, the Scoreboard, an evaluation, the Improvement page with a round, a recipe, the Configuration page, a version and the Settings page. A fresh subagent reviews them once as a senior product designer against `docs/BRAND.md` and point 8 of the brief; every finding is fixed or, where I disagree, explained in the report, and the fixed pages are shot again
- [x] `docs/SPEC.md`: the approval limit is a setting; the improver reads the handlers' decisions and reasons on the evaluation set, while the claim agent never sees them, nothing in the agent reads the held-out set's, and the dashboard shows both sets' decisions as it does today; handlers sign in; the improver, its rounds and the spending limit; and what the team needs to see, with the Improvement, Configuration and Settings pages
- [x] `docs/TECH_STACK.md`: Supabase Auth with `supabase-js` and PyJWT, the judge through the `openrouter` package, the improver as a sixth part of the agent, the configuration's versions, and `VITE_SUPABASE_URL`, `VITE_SUPABASE_PUBLISHABLE_KEY`, `HANDLER_PASSWORD` and `JUDGE_URL`
- [x] `docs/PROCESS.md`: signing in for browser checks with `HANDLER_PASSWORD`, the stand-ins, and these live runs in place of the swarm's
- [x] `docs/CODE_STANDARDS.md`: rule 7 names `agent/improver_api.py` for the improver, `agent/connection.py` as the one place with the backend's address, and `dashboard/src/auth.ts` for Supabase Auth; rule 13 gives the agent six parts with the improver and its tools in `improver.py`; rule 10 names the improver's middleware
- [x] `data/README.md`: the handlers' emails and who can sign off over the limit, `improvement.json` and `models.json`, and that `MODEL_NAME` must be set before `npm run seed`, since seeding chooses version 1 and the models allowed from it
- [x] `docs/STATUS.md` describes what's built, how to sign in and run a round, that `MODEL_NAME` must be set in `.env` before `npm run seed`, the live rounds and their verdicts, the spread of version 1's held-out runs, what the live checks cost, and the known gaps
- [x] `npm run check` passes, both with `.env` in place and with it moved out of the way

As built:

- Every page has a `PageHeader` whose lead says what the page is for; a version's and a recipe's reason moved from the lead into their details. Empty states use `StateMessage` with what to do next, and not-found pages say where to choose one. `dashboard/src/Pages.test.tsx` checks every page's header, that every column of numbers is right-aligned (a bare whole number, such as a version's, counts as an id), and every empty state.
- Nothing moves as a page refreshes, measured with a `PerformanceObserver` over seven seconds on each page while the live runs worked: the queue during the dispatch at N=25, a copy in progress (12 steps arrived), the Scoreboard and a running evaluation, and the Improvement page during round 1. Three causes were found and fixed: numbers in tables were in the body font, so a changing value changed its column's width (now JetBrains Mono with tabular figures); an evaluation's claims table sized its columns to their contents (now a fixed layout, one line a cell and two for the agent's reason, which a screen reader reads whole and the copy's own page shows in full; the table scrolls inside its panel, as it did before); and the claim page's sections read and policy panels sat above or below the growing steps (the right column now holds only the decision and the steps, which grow at its end). The one entry left was a running copy's own cost and time growing in place in their right-aligned cells, a score of 0.00001. A decision arriving moves the steps below it once; keeping room for it would leave a large empty panel on every claim, so `docs/STATUS.md` lists it as a known gap.
- Every button measured 35 pixels high, fully rounded, in Instrument Sans at 600; on every page at 1280 by 800 the title and the panels start at 24 pixels, the panels' contents at 48 and the tables' first columns at 60.
- The live runs are in `docs/STATUS.md`. A claim in progress for the check above needed a run of its own: two evaluations of the held-out set's five tiny claims at one claim agent at once, for under a cent.
- The designer's review found eight things to fix and thirteen to polish. Fixed: money cut off in an evaluation's claims; the version's and recipe's reason squeezed into one column; the rounds table's reason, now on a line of its own under each round; the claim page's breadcrumb and the Queue marked in the header; the agent's steps, with § and ’ shown as themselves rather than as escapes, since the agent now writes its JSON that way; numbers set one way, mono inside a number's cell no smaller, and "1 min" in place of "1 min 0 s"; disabled buttons on a neutral surface; the queue's claims under a heading with short fields kept to one line; the held payout tinted Marigold; Save kept in reach as the settings scroll; the nav's place fixed whatever the name beside it; "Grade (of 3)"; model names kept whole; the measures in two rows of four; links reading "Version 3" and "Recipe 2"; the instructions on the same tinted block as the diff; zero counts in gray and one wording for "Nobody needed to"; leads without one-word last lines; the units inside the settings' fields; the dispatch's summary headed "When it finished"; and the chart's axes fitted to the scores. Not changed, with why: the chip colors, since `docs/BRAND.md` gives Sea Green, Marigold and Coral to a claim's states; the approval limit's "1,000.00", since a number input can't hold a separator; the sign-off box's place, which stays after the decision's reasoning so a handler reads it before signing off; the dispatch's and evaluation's start forms, which stay in their panels with the choices they come with; dates and times in the body font, since they read as words; the step results' raw JSON, which is the tool's answer as the agent got it, folded until opened; and the steps panel's length, since a panel that scrolled on its own would put each new step out of sight, and the left column now holds the policy, the earlier claims and the sections read beside it.

## Not in this plan

- Signing in for the agent's service. Its calls to the backend stay open until Week 3 brings an API key.
- Rejecting a held payout, choosing the model of a dispatch on the dashboard, and editing a proposal before approving it.
- Sending the judge's grades to Langfuse as scores.
- Clearing old checkpoints, evaluations' copies and rounds. Reseeding clears them.
- Running rounds on free models, which need more requests than the free models allow in a day. Students on free models build and test everything.
- Real payments, messages to customers, and sign-up.
