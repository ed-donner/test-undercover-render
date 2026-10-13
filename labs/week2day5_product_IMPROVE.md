# An improver for the claim agent, and handlers who sign in

From the head of claims operations, with our IT team.

SIDENOTE: For consistency with the course, please read `labs/week2day5.ipynb` and build the judge, the configuration's versions and the improver in the same style as the lab. Where the lab and this brief differ, follow the brief. Include this sidenote in your plan too.

## Where we're heading

The scoreboard tells us how often the claim agent agrees with our handlers, what each claim costs and how long it takes. Improving the agent is still slow work for our team. Someone reads the misses, edits the instructions, runs the evaluations again and decides whether the change helped.

Our team's experiment in `labs/week2day5.ipynb` handed that loop to a second agent, the improver. It follows a recipe: read the results, propose a change, wait for a person to approve it and run the evaluations. The recipe's last step is to improve the recipe. Code keeps or rolls back each change on the held-out claims, and a judge grades each of the agent's explanations against the handler's reason.

We want that loop in the product, run from the dashboard by our handlers, who now sign in. The dashboard goes into production for the whole claims team, and our managers will judge the improver by these pages, so it has to look and work like the enterprise software our team already uses.

## What we want

1. **The claim agent's configuration, in versions.** The claim agent's instructions, model and reasoning effort make up one configuration, kept in versions. Version 1 is the claim agent as it is today. Each version records what changed, the reason, who proposed it, who approved it and when. A dispatch and an evaluation each record the version they used. A dispatch always uses the current version, and so does an evaluation started on the Scoreboard. A Configuration page takes the place of the Instructions page. It shows the current version, every version with its held-out scores, and what any version changed from the one before.

2. **A judge for the explanations.** Each claim in an evaluation is graded against the handler's reason and reference, as in the lab: a grade from F to A with a score from 0 to 3, and whether the agent gave the same grounds and the same section. The scoreboard adds the average grade beside our other measures, and an evaluation's page shows each claim's grade with the two checks. The judge's cost is recorded with the evaluation, apart from the claim agent's cost.

3. **The improver.** On a new Improvement page, a handler starts a round, and can stop a round that's open. Only one round is open at a time, and a round works to the improvement settings as they stood when it started.
   - A version's scores are the averages of the whole-set evaluations that rounds ran on it. If the current version doesn't yet have one on the evaluation set and two on the held-out set, the round runs them first.
   - The improver then follows its recipe. The first recipe is the lab's, which adds a rule for each mistake and ends by improving the recipe.
   - The improver reads the current version and its scores on both sets; from the current version's latest evaluation on the evaluation set, the wrong claims and the five right ones it explained least well, with our handlers' decisions and reasons beside the agent's and the judge's grade, along with its two checks on whether the agent gave the same grounds and the same section; the earlier rounds; the business objectives, the noise, the tolerance and our rule; what's left of the round's spending limit; and the models allowed. From the held-out set it sees the scores only.
   - It proposes a new version with its reason. The round waits until a handler approves or rejects it on the Improvement page, which shows the change to the instructions as a diff, with the model and reasoning effort before and after. A rejection carries the handler's reason back to the improver, which may propose again. A proposal outside the models allowed goes back to the improver without reaching a handler.
   - Once a change is approved, the improver asks for the new version's evaluations, once on the evaluation set and twice on the held-out set. The backend then keeps it or rolls it back by our rule, comparing the average of its held-out runs with the current version's scores. A new version is kept when it meets the objectives, at least one measure improves by more than its noise and none gets worse by more than its tolerance. A run with no graded claims has no grade, and a version without a grade is rolled back. A kept version becomes the current version.
   - The improver then proposes a new recipe, which a handler approves or rejects in the same way, shown as a diff.

   Each round records the recipe version it followed, the settings it worked to, the version it tried, the improver's reason, the held-out scores before and after, the verdict and why, who approved or rejected what and when, and what the round cost. The Improvement page shows where a round has got to as it happens: the first evaluations (1, 2 or 3 of 3), the improver working, a change waiting for approval, the evaluations (1, 2 or 3 of 3), the verdict, a recipe waiting for approval, and finished or stopped. It also shows the rounds so far, newest first, a chart of the held-out accuracy and grade of each version tried, and the recipe's versions, with one diff view for both versions and recipes. A round in which the improver proposes nothing finishes with no version tried. A round stopped before its verdict, by a handler or a restart, leaves the current version as it was, and a round stopped after its verdict keeps it.

4. **What the improver can't change.** The improver has no way to change the business objectives, the noise and tolerance, the spending limit, the models allowed, the approval limit, the evaluation sets or the judge. Nothing it proposes takes effect until a handler approves it.

5. **A spending limit for each round.** A round's spending limit covers the improver's own model calls, all of the round's evaluations, its first ones included, and the judge. The improver is refused an evaluation that is likely to cost more than what's left of it, and once a round has spent its limit, no new claim starts in its evaluations. An evaluation cut short by the limit shows as stopped. A version whose evaluations were stopped, or that the round can't afford to evaluate, is rolled back. The credit limit on our OpenRouter key, set at the end of the lab, covers everything as well.

6. **Handlers sign in.** Our handlers sign in to the dashboard with their email address and password through Supabase Auth, as set up at the end of the lab. There's no sign-up. Every page needs a signed-in handler, and the header shows who is signed in, with a way to sign out. The backend checks the handler on every action a handler takes: signing off a payout, starting a dispatch, an evaluation or a round, stopping a round, approving or rejecting a proposal and changing a setting. A sign-off records the signed-in handler, in place of choosing a name from a list. Dana Whitfield is our senior handler. Marcus Oyelaran and Priya Raman can't sign off payouts over the limit, so set `can_approve_over_limit` to `false` for them in `data/handlers.json`. Only a handler who can sign off over the limit may start or stop a round, approve or reject the improver's proposals or change a setting. When anyone else looks at a held payout, a round or the settings, the page says what they can't do and why, and the backend refuses it as well.

7. **A Settings page.** Every signed-in handler can see the platform's settings on a new Settings page, and a handler who can sign off payouts over the limit can change them:
   - the approval limit, $1,000 to start with
   - the business objectives: floors on held-out accuracy and on the judge's grade
   - the noise and the tolerance for accuracy, the grade, cost per claim and time per claim
   - the spending limit for each round
   - how many claim agents work at once in the improver's evaluations

   These start with the values in the lab, and the agents at once with 25. Each change records who made it and when. A new approval limit applies to the decisions recorded after it. The page also lists the models the claim agent may use, with their reasoning efforts and prices, which are set in a file in `data/` and can't be changed on the page. It also sets the appearance, light, dark or the same as the computer, which each browser remembers.

8. **A dashboard that looks like enterprise software.** This is as important as the improver itself. The new pages need a clear page header that says what the page is for, consistent spacing and alignment, numbers right-aligned in tables with their units, statuses shown with a color and a word, a diff that's easy to read with additions and removals in color, loading, empty and error states that say what to do next, a confirmation in the dashboard's own dialog before any action that changes the agent or a setting, and nothing that jumps about as the page refreshes. Bring the existing pages up to the same standard with small improvements: the same header and spacing on every page, navigation that shows where you are, tables that line up and buttons that look alike. Nothing on the existing pages changes how it works. Everything follows `docs/BRAND.md` in light and dark mode and works on a laptop screen.

## Our IT team's choices

- **The configuration and the recipe** are versioned records owned by the backend. Seeding makes version 1 of each: the configuration from the claim agent's instructions file with `openai/gpt-6-luna` at low reasoning effort, and the recipe from the lab's first recipe, in a file beside the instructions. The agent's service builds each run's claim agents from the version the run uses, and an evaluation in a round uses the version under test. The operation the claim agent uses to fetch its version holds no scores. The backend works out each diff with Python's `difflib`, as the lab does, and applies the rule that keeps or rolls back a version.
- **The judge** is Jev, `typesafe/jev-1.13`, called through OpenRouter's Decisions endpoint with the `openrouter` package and the lab's three questions. It runs in the backend, in a module of its own, because the backend holds the handlers' decisions, so the held-out set's reasons never leave it.
  - Its state is the handler's decision, reason and reference beside the agent's decision, reason and section. The score is Jev's `score`, and the letter is the level with the highest probability, never the score rounded. Keep the two checks as probabilities and show them as yes or no.
  - The backend grades an evaluation's claims in parallel as part of finishing it, each call timing out after 10 seconds with the SDK's retries turned off, so finishing stays under 20 seconds. A claim the agent didn't decide gets an F without asking the judge, and a claim the judge couldn't grade shows as not graded and is left out of the average.
  - The endpoint is in alpha, so the call is written once, in that module. The client ignores an address set on it, so pass the address as `server_url` on each call, read once from the environment: an origin such as `https://openrouter.ai`.
- **The improver** is a sixth part of the agent, `agent/improver.py`: a LangChain `create_agent` on GPT-6 Luna at medium reasoning effort, with its model calls capped for each round as the claim agent's are, and parallel tool calls turned off (`parallel_tool_calls=False` in its model settings), so a reply never holds two proposals.
  - Its instructions wrap the recipe and are written as goals. They tell it what the claim agent works from (its instructions with the contents of the policy wording and the claims manual, the claim, the policy and the customer's earlier claims, and its tools for searching and reading sections and working out a payout), and that a change never names a claim. The recipe is data the improver follows, so it may be a list of steps, and `docs/CODE_STANDARDS.md` rule 14 applies to the instructions around it.
  - Its tools are the lab's four, with the lab's names, since the recipe names them: `read_results`, `propose_change`, `run_evaluation` and `propose_recipe`. They reach the backend through a client module of their own, so the claim agent's client still has no way to the scores or the handlers' decisions. `run_evaluation` works the evaluations in the agent's service through the dispatcher, in a fresh `contextvars.Context` as the harness runs each claim graph, since a graph compiled without a checkpointer otherwise saves into its caller's thread.
  - `HumanInTheLoopMiddleware` on the two propose tools pauses it for approval, with a `PostgresSaver` of its own on Supabase as its checkpointer, saving with `durability="sync"` as the claim agent does. Each round gets a new thread id, so a reseed never meets an old round's checkpoints. A round waiting for approval survives a restart.
  - The service records a round's state with the backend, including a proposal waiting for approval, and the dashboard reads it from there. An approval or a rejection goes to the backend, which passes it to the agent's service with the handler, as it does a start, and passes on a refusal. The service records the decision and the handler before it resumes the improver, and the backend records nothing of its own.
  - Stopping a round marks it stopped in the backend, which then refuses anything the round records. The service starts no more claims or model calls for it, and lets go of the one-run rule when the work in hand ends.
- **One thing at a time:** only one dispatch, evaluation or stretch of the improver's work runs at a time, and the improver's evaluations are part of its own work, never refused because of it. A start, an approval or a rejection while something else is running is refused, saying what is running. While a round waits for a handler, dispatches and evaluations can run.
- **The spending estimate:** prices in the models allowed are numbers, in dollars per million input and output tokens. An evaluation's estimate is its claims times the highest cost per claim seen so far for its model. For a model with no runs yet, it is the current model's, scaled by the larger of the ratios of their input and output prices.
- **Sign-in:** the dashboard signs in with `@supabase/supabase-js` and `signInWithPassword`, reading `VITE_SUPABASE_URL` and `VITE_SUPABASE_PUBLISHABLE_KEY`. The dashboard sends the session's access token with each action. The backend checks it against the project's public keys at `/auth/v1/.well-known/jwks.json` under `VITE_SUPABASE_URL`, with PyJWT's `PyJWKClient` and the audience `authenticated` (add it with `uv add "pyjwt[crypto]"`), then finds the handler by the token's email. Seeding stores each handler's email. No Supabase secret is needed, since the project signs with asymmetric keys. The agent's calls to the backend need no sign-in until Week 3 brings an API key. Claude Code signs in as a handler with `HANDLER_PASSWORD` for its browser checks.
- **The tests:** the end-to-end tests use stand-ins for Supabase Auth and the judge, as they do for the agent's service. The Auth stand-in signs tokens with a key of its own, serves its public keys and answers the browser's cross-origin checks. The addresses of Supabase and of the judge's endpoint are each read once from the environment, so the tests point them at the stand-ins. Vite reads `.env` from the repo root for `npm run dev` only, and the unit and end-to-end tests set their own values.
- **Cost:** the improver's model calls are recorded with its round, with OpenRouter's `usage.cost` as for the claim agent, and the judge's calls with the evaluation, from the cost in the judge's response.
- **Settings** are kept by the backend in the database, seeded from `data/company.json` for the approval limit and from a new file in `data/` for the rest, and every part of the product reads them from there. The appearance is the one setting kept in the browser.
- **Students on free models:** with `MODEL_NAME` set, the claim agent and the improver use that model, which is then the only model allowed, at reasoning effort `default` and a price of 0. The judge isn't called, so claims show as not graded. A round needs far more requests than the free models allow in a day, so these students build and test everything but don't run rounds.
- **Langfuse:** the improver's work in a round goes in one Langfuse session named after the round, and the claims of its evaluations are tagged with the round as well as their run.
- **The chart** is drawn in SVG, with no new library.
- **Windows:** everything `npm run dev` starts must work on Windows too (`docs/PROCESS.md`).

## Notes from our last build

These notes come from our own build of the swarm, on the `week2day4-end` branch. If your build took a different path, a note may not match your code: follow its intent where it applies and skip it where it doesn't.

- **The baseline:** version 1 scored 80% `decision_accuracy` on the evaluation set, and every miss was an approval of a claim our handlers declined or referred. Luna also ended its turn without recording a decision on about one claim in fourteen. That gives the improver something to fix in its first round.
- **The handlers' reasons:** the `handler_decisions` table holds the decision, the payout and `tiny` only. Seeding needs to store each label's `reason` and `reference` from `data/evals/` too, for the judge and for the improver's view of the evaluation set. You may open `data/evals/` for this change.
- **The claim agent's client:** `agent/api.py` has no function for the evaluation reads or for starting runs, and `test_the_agent_cant_read_the_scoreboard` checks the function names. Keep it that way, and put the improver's calls in a module of their own.
- **The one-run rule** is a `threading.Lock` in `agent/service.py`, with the claims being resumed after a sign-off in a set beside it, and every refusal gives the same message. Keep the lock in the service: a round's stretch of work holds it and runs its evaluations in the same process, and a refusal names what is running.
- **Finishing a run:** `agent/api.py` waits 30 seconds for the backend, and a dispatcher that fails marks its run stopped, so grading inside `finish_run` must finish well within that.
- **The model:** the service builds the model from `MODEL_NAME` for each request and records its name on the run. With versions, it builds the model from the run's version. It records no reasoning effort as `none`, which Luna also has as a real level, so record it as `default`, as the free lab does.
- **The sign-off:** `SignOffForm.tsx` chooses a handler from a list and `sign_off_claim` takes a `handler_id`. Both give way to the signed-in handler. The `handlers` table has no email column yet.
- **The routes that need a signed-in handler:** `start_dispatch` (`POST /api/dispatches`), `start_evaluation` (`POST /api/evaluations`) and `sign_off_claim`, with the new ones. The service's own writes under `/api/runs` stay open until Week 3.
- **The end-to-end tests:** `playwright.config.ts` starts the backend, the agent's stand-in and the dashboard, and every spec will need to sign in. `dashboard/vite.config.ts` is Vitest's config as well, so `envDir` there reaches the tests too.
- **The theme:** `styles.css` sets dark mode from `prefers-color-scheme` alone, so the switch needs the colors set from an attribute on the page as well.
- **Time per claim** depends on waiting for database connections: claims took 12.4 seconds at N=3 and 21.4 at N=25. The lab's tolerance on time was measured without a database.

## What stays the same

- The rules in `docs/SPEC.md`, with two changes. The approval limit is now a setting. The improver reads our handlers' decisions and reasons on the evaluation set, while the claim agent still never sees them, nothing in the agent reads the held-out set's, and the dashboard shows both sets' decisions as it does today. Update SPEC.md for these, the sign-in, the improver and what the team needs to see.
- The policy wording and the claims manual stay as written, though the manual mentions the $1,000 limit.
- The claim agent's graph and tools.
- The API rules in `docs/TECH_STACK.md`: every operation has an `operation_id`, a one-line docstring and no optional inputs.
- Tests never call a model, the judge or Supabase Auth, `npm run check` never reads `.env`, and the code follows `docs/CODE_STANDARDS.md`.
- `npm run seed` rebuilds everything, as it does today, so it also takes the configuration and the recipe back to version 1 and empties the rounds. Evaluations and rounds work their own copies and need no reseed.

## What done looks like

- `npm run check` is green with `.env` moved out of the way. Tests on a stub model and a stub judge cover each new behavior:
  - a version kept and one rolled back by our rule, with measures worked out by hand, cost and time compared as fractions of the old value and accuracy and the grade as differences, and a version with no grade rolled back
  - a version's scores counting only the whole-set evaluations its rounds ran
  - the improver's view holding nothing from the held-out set but its scores
  - a proposal changing nothing until it is approved, a rejection's reason reaching the improver, a proposal outside the models allowed going back to the improver, and an approval refused while a dispatch runs, with nothing recorded
  - an evaluation refused when it would go over the round's limit, and one cut short by the limit shown as stopped
  - a stopped round leaving the current version as it was, and a round keeping its settings when they change
  - a dispatch and an evaluation recording their version
  - the letter as the most likely level, an undecided claim graded F, and an ungraded claim left out of the average
  - every handler action refused without a valid sign-in, and a sign-off over the limit, an approval and a settings change refused for Marcus Oyelaran
  - a new approval limit applying to the next decision
  - the claim agent still unable to reach the scores or the handlers' decisions

  The end-to-end tests sign in, approve a proposal that the test plays out through the API, change a setting and switch the theme.
- After one `npm run seed`, with `npm run dev` running and the default model, checked through the Playwright MCP server:
  - Signed in as Dana Whitfield, run two rounds from the Improvement page. Reject the first proposal with a reason, then approve the next one, and approve the rest. Each round shows on the page as it happens, and afterwards the rounds show the scores before and after, the verdict and the cost. The Configuration page shows the versions and their diffs, and through Langfuse's API each round's improver traces are found in one session. Report how far version 1's two held-out runs differed on each measure, beside the noise and tolerance.
  - Then start a dispatch at N=25 on the current version. Signed in as Marcus Oyelaran, a payout waiting for sign-off can't be signed off and the settings can't be changed. Signed in as Dana Whitfield, the same payout is signed off and paid.
  - Take screenshots of every page in light and dark mode. A fresh subagent reviews them once, as a senior product designer would, against `docs/BRAND.md` and point 8 above, and you fix what it finds.
  - Report what the live checks spent. On GPT-6 Luna they should come to under $1.
- `docs/SPEC.md`, `docs/TECH_STACK.md`, `docs/PROCESS.md`, `docs/CODE_STANDARDS.md` (rules 7 and 13 for the improver and its client and the dashboard's Supabase client), `docs/STATUS.md` and `data/README.md` describe the product as it now is.

## Planning

Follow `docs/PROCESS.md`, but write this plan to `docs/PLAN_IMPROVE.md` and tick it off there. Start with the sign-in, so every later page is built signed in. Then the configuration's versions and the Settings page, then the judge, then the improver and its page, and last the look of the whole dashboard and the live runs. For the live runs with the real model, reseed once first and keep to the runs above.
