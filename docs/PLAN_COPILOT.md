# Plan: the UnderCover Copilot

This plan builds the Copilot in `docs/COPILOT.md` in six phases, each building on the last. Each phase leaves `npm run check` green and is committed before the next one starts. The live checks run once, last, in phase 6, after one reseed.

SIDENOTE: For consistency with the course, please build the Copilot the way the course has built its agents. Its agent loop is a LangGraph `StateGraph` written by hand: a node that calls the model, LangGraph's `ToolNode`, and the loop between them, with a `PostgresSaver` checkpointer, as in `labs/week2day3.ipynb` and the claim agent's graph. Please don't use LangChain's `create_agent` for it. The pause before a sign-off is an `interrupt()` in a node of its own, resumed with `Command(resume=...)`, since LangGraph runs an interrupted node again from the top when it resumes, as the claim agent's wait for a handler is a node of its own. The handler's sign-in reaches the graph and its tools in the graph's context (`context_schema`, read through `ToolRuntime`), never in the config, whose values LangGraph saves with each checkpoint. The Copilot is an AgentCore app of its own, made with `BedrockAgentCoreApp`, with one entrypoint and each turn's work registered as an async task, as the claim agent's AgentCore app does, and it is synchronous throughout, as the claim agent is. `labs/week3day4_lab1.ipynb` and `labs/undercoverlab/` show a pause in one Runtime session resumed in another. Its memory is `AgentCoreMemoryStore` as a LangGraph store, as the claim agent's memory is, with the Memory itself made as in `labs/week3day3.ipynb`. It reaches the context layer over MCP with `MultiServerMCPClient`, as in `labs/week2day2.ipynb`, and through the Gateway as in `labs/week3day2_lab2.ipynb` and `labs/week3day3.ipynb`. `labs/week3day4_lab2.ipynb` deploys the claim agent and points the app at it, and `labs/week3day5_lab1.ipynb` deploys the Copilot beside it, so please match the names that notebook uses. Read these notebooks without running them. Where a notebook and this document differ, follow this document. Include this sidenote in your plan too.

When it's done, every signed-in page has the Copilot in a sidebar on the right. A handler asks in plain English, and the Copilot looks things up in the app and the context layer, starts dispatches and evaluations and waits for them in code, sends held decisions back, and signs off a held payout once the handler has confirmed on a card in the sidebar. It works as the handler who asked: the dashboard sends the handler's sign-in to the app with each message, the app passes it to the Copilot, and every call the Copilot makes to the app carries it, never the agent's key. Each tool call shows as a card as it happens. Conversations are saved after every step in Supabase, so a handler picks one up after a restart or on another day, a paused sign-off included. With its setting, the Copilot remembers each handler's preferences and facts in an AgentCore Memory of its own. It answers "Are we meeting the success criteria we agreed?" from an evaluation it runs, the settings and the app's count of payouts over the limit, every figure worked out in code. The Copilot is a second AgentCore app, `agent/copilot/entrypoint.py`, which `npm run dev` serves on 127.0.0.1:8081 and `runtime/copilot.py` runs on Runtime as the platform team's second runtime, `copilot`.

SIDENOTE: Make sure the Copilot sidebar looks stunning, elegant, enterprise-grade - an interactive and compelling UX, fitting for a capstone project. Take the time to design and implement this UI to be outstanding. Take screenshots of it and iterate until you're very satisfied.

Phases 1 to 5 are checked with tests, local commands and a SQLite backend, and none of them uses the real model, AWS or Supabase. Phase 6 brings the docs up to date and runs the live checks on the default model, on the direct route, with memory off.

## Design

### Modules

The agent, shared parts moved out of the claim agent's modules so both agents use them, with no change to what the claim agent does (phase 2, apart from `agentcore_app.py` in phase 4):

- `checkpoints.py` (new, from `harness.py`): `Pool`, `SCHEMA`, `open_checkpoint_pool()` and `checkpoint_pool()`, as they are today. It uses nothing else in the agent.
- `tool_route.py` (new, from `harness.tool_route()`): `from_environment()`, the Gateway when `UNDERCOVER_GATEWAY_URL` is set, read now, or else the direct route. It is the one module that imports both `gateway.py` and `direct.py`; the harness and the Copilot use it.
- `context_tools.py` (new, from `tools.py`): the context layer's seven lookups and `looked_up`, unchanged, reading the route from any context with a `route` (`RouteContext`, a `Protocol`), so `ClaimContext` and the Copilot's context both serve. `tools.py` keeps the claim agent's other tools, and `CLAIM_TOOLS` is still the app's five plus these seven. If LangChain checks a tool's `ToolRuntime` type against the graph's context, the module gives each agent the same seven tools through one function instead, and the step reports which.
- `agentcore_memory.py` (new, from `memory.py`): `store_at(memory_id)`, `AgentCoreMemoryStore` in the AWS CLI's region, and `UNREACHABLE`, what it raises when AgentCore can't be reached. `memory.py` keeps `UNDERCOVER_MEMORY_ID` and the customers' namespaces.
- `agentcore_app.py` (new, phase 4, from `entrypoint.py`): what the two AgentCore apps share. `Ready`, which gets ready once in a process behind a lock and answers a 503 that says what went wrong, so the next request tries again; `read(adapter, payload)` with `what_is_wrong`, which names each problem without echoing a value; `is_the_health_check`; `in_background(app, name, work)`, which registers the work as an async task and runs it on a thread of its own; `Refusal`; and the `ACCEPTED` and `HEALTHY` answers.
- `identity.py` (phase 4): `fetch_credentials(*settings)` fetches only the settings named. The claim agent's entry point names `OPENROUTER_API_KEY`, `UNDERCOVER_API_KEY` and `DATABASE_URL`; the Copilot names the first and the last.
- `connection.py` (phase 2): `call_as(sign_in, method, path, **request)` sends one request with `Authorization: Bearer <sign-in>` and no `X-API-Key`. `call` and `call_as` share one way of sending a request and reading its answer or its `Refused`.

The Copilot, a package of its own, `agent/copilot/`, beside the claim agent's modules:

- `app_api.py` (phase 2): the Copilot's API on the app, one function per backend operation it uses, named after it, each taking the handler's sign-in first and sending it with `connection.call_as`. It is the Copilot's only way to the app and has no function for `get_evaluation`, the rounds or anything for the agent's key.
- `tools.py` (phase 2): the Copilot's tools, `CopilotContext` (the sign-in, the handler as the app gave them, the conversation, the turn and the route) and each tool's kind for its card. `sign_off_claim` is a schema the model can ask for (a Pydantic model bound as a tool), which the graph answers itself; no tool pays.
- `cards.py` (phase 2): a card for each step: recorded with the app as a tool starts and again when it ends, its kind, the tool's own name and its main input, its status and its trimmed text, and the files and owners of a context layer answer from the tool's artifact. The `ToolNode`'s `wrap_tool_call`, the sign-off and the memory's lookup record their cards through it.
- `graph.py` (phase 2): the Copilot's graph, `copilot_graph(llm, saver, store)`, its state and its nodes (below).
- `instructions.md` and `instructions.py` (phase 2): the instructions, and `instructions_for(handler, remembered)`, which puts in who the Copilot works for, what they may do and what it remembers of them.
- `turns.py` (phase 2): works a turn and an answer to a confirmation: builds the turn's model, graph and context, closes any tool call a stopped turn left open, runs the graph on the conversation's thread, and tells the app how the turn ended: answered, paused or failed.
- `waiting.py` (phase 3): waits on a dispatch or an evaluation in code, reading it from the app every `POLL` seconds (5) for up to `WAIT` (15 minutes).
- `needs_a_handler.py` (phase 3): what needs a handler, worked out in code from the queue.
- `criteria.py` (phase 3): the three success criteria, their targets, and the table of figures, worked out in code.
- `memory.py` (phase 3): the Copilot's memory of each handler, the one place with `UNDERCOVER_COPILOT_MEMORY_ID` and the handlers' namespaces: the store, a search of one handler's memories, and the save of a message and its answer.
- `entrypoint.py` (phase 4): the Copilot's AgentCore app, `app = BedrockAgentCoreApp()` with one `@app.entrypoint`. It gets ready on its first request, reads each payload, checks the sign-in and the conversation with the app before it answers, keeps one turn at a time for each conversation in its process, and hands the turn to `turns.py` in the background. It asks for no key.

Two more shared modules came from the whole-branch review: `app_terms.py`, the app's words for its records that `api.py` and `app_api.py` had each written, and `refusals.py`, how a model is told a refusal, which `connection.py`, the harness and the Copilot's graph had each written. Neither imports anything else in the agent.

The Copilot's modules use `connection.py` only through `app_api.py`, and of the claim agent's modules only the shared ones above, `routes.py`, `openrouter.py`, `json_text.py`, `console.py` and `root_run.py`. Nothing in the claim agent imports the Copilot.

`runtime/` (phase 4): `copilot.py` (new), which imports `app` from `agent.copilot.entrypoint` and calls `app.run()`, as `main.py` does for the agent; and `copilot_policy.json` (new), the Copilot's role: `bedrock-agentcore:InvokeGateway` on `gateway/undercover-gateway-*` and the six Memory actions `policy.json` lists, on `memory/undercover_copilot_memory-*` only.

The backend:

- `asking.py` (new, phase 1, from `agent_work.ask_the_agent`): commit what the app did for the work, ask an AgentCore app to take it, and undo it when it didn't, which the runs, the rounds and the Copilot's conversations share.
- `runtime_calls.py` (new, phase 1, from `agent_service.py`): calling an AgentCore app, which the agent's and the Copilot's services share: posting a payload to `/invocations` on the laptop, invoking a runtime with `invoke_agent_runtime` in a session given, retrying a conflict, and reading the answer, with `NotTaken` and `MayHaveStarted` worded for the service. The one place with `/invocations` and the `bedrock-agentcore` client.
- `agent_service.py` (phase 1): the agent's settings and its four operations on `runtime_calls.py`, a new session for each call, as today.
- `copilot_service.py` (new, phase 1): the Copilot as the app calls it. `take_turn(conversation_id, turn_id, sign_in)` and `answer_confirmation(conversation_id, turn_id, sign_in)`, posted to `/invocations` at `UNDERCOVER_COPILOT`, or `http://127.0.0.1:8081`, with no key, or sent to `UNDERCOVER_COPILOT_RUNTIME` with the conversation's id as the session id. The one place with both settings.
- `conversations.py` (new, phase 1): the Copilot's records: conversations, their turns and each turn's cards; where a turn stands, `stopped` included; one turn at a time; the confirmation card filled in from the claim; and a conversation found only for its own handler.
- `copilot.py` (new, phase 1): an `APIRouter` with the conversations' operations, for the dashboard and for the Copilot, and `get_copilot_model`. `COPILOT_MODEL` is `("openai/gpt-6-luna", "low")`, through `free_models.model_or_free`.
- `customers.py` (new, phase 1): an `APIRouter` with `find_customers` and `get_customer`.
- `main.py` (phase 1): `count_payouts_over_limit`, and the two new routers.
- `runs.py` (phase 1): `get_run` takes the agent's key or a signed-in handler; `start_dispatch` and `start_evaluation` answer with the run they started.
- `dependencies.py` (phase 1): `SignIn`, the request's own access token, for the three routes that pass it to the Copilot; `signed_in_handler` refuses a request that carries the agent's key with a 403, so the key never stands in for a handler, whatever else the request carries.
- `database.py` and `models.py` (phase 1): the tables and models below. Seeding builds them afresh with everything else.

The dashboard (phase 5):

- `PageFrame.tsx`: the page and the sidebar side by side, or the sidebar over the page on a narrow window.
- `components/Copilot.tsx` (new): the sidebar: open or collapsed to a slim tab with `BotMessageSquare`, the conversation's turns, the message box and "Signed in as ...". `components/CopilotConversations.tsx` (new): New conversation and the earlier conversations. `components/CopilotTurn.tsx` (new): a turn: the handler's message, its cards, the working indicator, the confirmation card, the answer and its small print. `components/StepCard.tsx`, `components/ConfirmationCard.tsx`, `components/CopilotGreeting.tsx` and `components/MessageBox.tsx` (new). `components/Markdown.tsx` (new): an answer formatted with `react-markdown` and `remark-gfm`, with claim ids as links to their pages.
- `copilot.ts` (new): what the browser remembers, the sidebar open or collapsed and the conversation open, and each card kind's icon and label.
- `useLoad.ts`: an optional `keepAsking(data)`, so the sidebar asks again only while a turn is working.
- `api.ts`: the Copilot's five operations, with its types in `conversation.ts` and, to keep `api.ts` under 500 lines, how a request is sent and its refusal read in `connection.ts`, which only `api.ts` uses, as `agent/connection.py` serves `agent/api.py`. `auth.ts`: `freshAccessToken()`, which renews the sign-in when it has less than 20 minutes left; the message and the answer to a confirmation are sent with it.
- `package.json`: `react-markdown` and `remark-gfm`.

The rest:

- `package.json` (phase 4): `dev:copilot`, `uv run --env-file .env uvicorn agent.copilot.entrypoint:app --host 127.0.0.1 --port 8081 --reload --reload-dir agent`, joins `dev`; `check:runtime` imports `runtime.main` and `runtime.copilot`.
- `agentcore/agentcore.json` (phase 4): a second runtime, `copilot`, as `agent` is but with `copilot.py` as its entry point and `copilot_policy.json` as its policy. `agentcore/cdk/lib/cdk-stack.ts`: `UNDERCOVER_COPILOT_MEMORY_ID` joins `SETTINGS`. Nothing else in either folder changes.
- `conftest.py`: no test sees `UNDERCOVER_COPILOT`, `UNDERCOVER_COPILOT_RUNTIME` or `UNDERCOVER_COPILOT_MEMORY_ID` (phase 1).
- `e2e/copilot_stand_in.ts` (new, phase 5), on port 8007, and `playwright.config.ts` pointing the test backend at it with `UNDERCOVER_COPILOT_RUNTIME` blank.

### A turn

```
START -> begin -> recall -> agent --(a tool)--> tools -> agent
                              |                   |
                              |                   +--(success criteria checked)--> report_criteria -> remember -> END
                              |
                              +--(sign_off_claim)--> check_sign_off --(may not)--> agent
                              |                            |
                              |                            +--(may)--> confirm --(sign off)--> sign_off -> agent
                              |                                           |
                              |                                           +--(cancel)--> cancelled -> remember -> END
                              |
                              +--(an answer)--> remember -> END
```

- The state: `messages`, the turn's `model_calls` and `cost` (each adding up), the claim a sign-off asks about (`confirming`, which stays set for the rest of the turn), the handler's answer to its confirmation (`confirmation`), what the memory found (`remembered`), and the success criteria's answer, the table and its verdict line, once `check_success_criteria` has built it this turn (`criteria`). The thread is the conversation's id, and the graph saves after every step with `durability="sync"`, on a `PostgresSaver` of its own on the process's checkpoint pool.
- `begin` starts the turn's counts again from zero with `Overwrite(0)` and empties `confirming` and `criteria`. With a memory, `recall` searches the handler's memories for the message, records a `search_memory` card with what it found, and keeps it in `remembered`; with none, `recall` and `remember` aren't in the graph.
- `agent` asks the model, with the instructions for this handler and what it remembers of them as the system message, built for each call and never saved, up to 25 model calls a turn, and records each call's tokens and cost into the state. Parallel tool calls are off, and the graph runs with `max_concurrency: 1`, as the claim graph does, so a reply that still asks for several tools has them run one at a time, in order. A reply with no tool call is the answer.
- `tools` is a `ToolNode` whose `wrap_tool_call` records each card and returns the app's, the Gateway's and a tool's own refusals, bad inputs included, to the model, the card keeping the bare reason; `handle_tool_errors` is off, so a sign-in the app no longer accepts (a 401) and any other error mark the card failed and fail the turn. (As built, a 401 stops the turn at once: the app refuses everything sent with that sign-in, the card and the turn's failure included, so the turn shows as working until it reads as stopped; `docs/STATUS.md` lists it as a known gap.)
- `check_sign_off`, in code: the call's inputs must be the `SignOffClaim` schema's, or it is refused with what's wrong; the claim must be waiting for sign-off and not an evaluation's copy, and the handler, as the app gave them, must be able to sign off over the limit. If not, it records a refused `sign_off_claim` card with the reason and answers the call with it, and the model tells the handler; the app's sign-off is never called. Otherwise it keeps the claim in `confirming`. Should a reply ask for the sign-off beside another tool, the other is answered "Refused: one step at a time". One sign-off a turn: once `confirming` is set, another `sign_off_claim` in the same turn is refused with "One sign-off a turn. Please ask me again for the next one.", with a refused card and no second pause, so a turn has one confirmation at most.
- `confirm` holds only `answer = interrupt({"claim_id": ...})`, since a resume runs it again from the top. Everything before it is saved and isn't done again.
- `sign_off` records a `sign_off_claim` action card and signs the claim off through the app with the handler's sign-in, which pays it and asks the claim agent to finish its work, and answers the tool call with the app's answer. Run again after a restart, a claim already signed off by this handler counts as done.
- `cancelled` answers the tool call with "Canceled. Nothing was signed off or paid." and ends the turn, written in code, with no model call: after the handler's Cancel, "I haven't signed off CLM-1008. What would you like to do instead?"; after a Sign off the app turned into a Cancel because the claim changed (below), "The claim changed since the card was shown, so I canceled this sign-off without making a payment. Please ask again."
- After `tools`, a turn whose `criteria` is set goes to `report_criteria`, which ends it with `criteria` as its whole answer, a reply written in code, with no model call, and then to `remember`, as `cancelled` does. Every figure in that answer, and every explanation of a figure it can't give, is the code's.
- The turn's answer is always the last reply's text: the model's, or one written in code by `cancelled` or `report_criteria`.
- With a memory, `remember` saves the handler's message as a `HumanMessage` and the turn's answer as an `AIMessage` to the handler's memory, with the handler as the actor and the conversation as the session, and nothing else. A memory that can't be reached is logged as a warning and the turn is still answered.
- `turns.py` runs the graph, then reads its state. With an interrupt waiting, it tells the app the turn paused, naming the claim; otherwise it tells the app the turn's answer, with the model calls and their cost. A turn that raises is failed with the error in one line (`describe`). The app hears of the pause only once the interrupt is saved.
- A new turn first closes any tool call a stopped turn left open with "This step stopped before it finished", in the same input as the new message, so the model never sees a tool call without its answer.
- The Copilot's model comes from `get_copilot_model`, built with `openrouter.chat_model`, at the start of each turn and answer.

### Who the Copilot works for

- The dashboard sends the message, or the answer to a confirmation, with the handler's access token, renewed first when it has less than 20 minutes left. The app's route checks it as it checks every route, and passes the token on to the Copilot in the payload. The app never writes it to the database or a log.
- Before it answers the app, the Copilot asks `get_signed_in_handler` with the sign-in, and reads the conversation with it, which the app finds only for its own handler. A sign-in the app doesn't accept, another handler's conversation, or a turn that isn't the conversation's latest working one is refused at once, before any model call, and the app records the refusal on the turn.
- The handler from `/api/me` is the Copilot's handler for the turn: their id is the memory's actor, and their name, role and whether they can sign off over the limit go into the instructions. Nothing the model writes or the message says changes them.
- The sign-in lives only in the payload, in `CopilotContext`, which LangGraph passes to the nodes and the tools and never saves, and in each request's `Authorization` header. It is never in the config, the state, an interrupt, a resume, a card, the memory or a log, and a payload error names the input without its value.
- The Copilot never sends the agent's key: its only way to the app is `app_api.py` on `call_as`. Its context layer tools call only the context layer's target, so on the Gateway it uses only `undercover-context___<tool>` and on the direct route never the app through `api.py`. The app treats any request that carries the agent's key as the agent's, and a handler's route refuses it.

### The pause and the confirmation card

- The app fills in the card from its own records when the Copilot says it paused on a claim: the claim, the customer's name, the payout held and the agent's reason, refusing a claim that isn't waiting for sign-off or is a copy. It also keeps the held decision's `decided_at`, which the card doesn't show. Nothing the model wrote reaches it.
- The turn waits as `waiting_for_confirmation`, with its card, until the handler answers. While it waits, the app refuses a new message in the conversation, "Answer the confirmation first", and the message box says so.
- The answer names the turn whose card was shown, `{turn_id, answer}`, and the app refuses it with a 409 unless that turn is the one waiting, so a stale tab can't answer a newer card or answer a card twice.
- Cancel is always taken for the waiting turn. For Sign off, the app first checks the claim against the card: if it is no longer waiting for sign-off, or its held decision isn't the card's, by when it was made, its payout and its reason (a send back and a new decision, even with the same payout), it records the answer as a Cancel with `canceled_because` "The claim changed since the card was shown", and carries on as for a Cancel. Nothing is paid and the conversation is free for a new message once the turn ends.
- Then the app records the answer and when it came, moves the turn back to working, commits, and asks the Copilot to carry the conversation on. The Copilot reads the answer from the app's record of the turn, never from the request, as the claim agent reads a handler's answer, and resumes the graph with `Command(resume={"answer": "sign_off"})`, `{"answer": "cancel"}` or `{"answer": "cancel", "changed": true}`, in whatever process or Runtime session gets it. When the Copilot doesn't take the answer, the app undoes it, so the card waits again.
- After the answer, the card shows what actually happened, read from the turn's `sign_off_claim` action card: "Signing off" while it works, "Signed off and paid" only once it's done, and the reason when it's refused or failed; or "Canceled", with the reason when the claim changed. An answer of Sign off on its own never shows "Signed off and paid".

### Waiting for the agent's work

- `start_dispatch(agents)` and `start_evaluation(evaluation_set, tiny, agents)` take the number of claim agents the handler asked for, or `null` for the `agents` in the settings, which the tool reads. The app's answer names the run it started, its id and number, which the tool gives the model; the app's refusal, such as "A dispatch is running", goes back as a refusal.
- `wait_for_run(run_id)` reads the run with `get_run`, which a signed-in handler may now use, every 5 seconds, with no model call, until it isn't running. A finished dispatch answers with its summary from the app's record, its time and cost, and what needs a handler; a finished evaluation with its measures from `list_evaluations`; a stopped run with why. After 15 minutes it answers that the work is still going and where to follow it: the queue page for a dispatch, the Scoreboard for an evaluation.
- What needs a handler, from the queue, in code: the payouts held for sign-off with their amounts, the claims referred and the claims left for a handler, and any claim sent back that the agent hasn't taken up. The `what_needs_a_handler` tool gives the same at any time.

### The success criteria

`check_success_criteria()`, with no inputs, does it all in code:

1. It reads the settings and starts an evaluation of the whole held-out set with their `agents`.
2. It waits for it, as `wait_for_run` does.
3. It reads the evaluation's measures, and `count_payouts_over_limit`.
4. It builds the table, with one line on whether all three are met, and returns a `Command` that answers the tool call with them and keeps them in the state's `criteria`. The graph then ends the turn with them as its whole answer, through `report_criteria` and the memory, with no model call after the tool:

| Criterion | Target | Figure | Met |
| --- | --- | --- | --- |
| Straight through | At least 70% | The evaluation's straight-through share | Yes or No |
| Accuracy | At least the accuracy objective in Settings (60% to start) | The evaluation's accuracy | Yes or No |
| Over the limit | Every payout over the approval limit signed off by a handler | "2 of 2 signed off", or "None paid over the limit yet" | Yes or No |

- The model writes nothing in this answer, so no figure in it can come from the model, and the sidebar, the saved conversation and the memory all get exactly what the code wrote.
- Percentages are shown as the Scoreboard shows them. The 70% is `STRAIGHT_THROUGH_TARGET` in `criteria.py`, the one place it's written.
- `count_payouts_over_limit` counts the queue's claims, never a copy, whose payment is more than the approval limit recorded on their decision, and how many of those have a handler's sign-off. With none paid over the limit, the third is met, and the figure says why; with one paid over its decision's limit and no sign-off, it isn't.
- If the app refuses to start the evaluation, the table gives its reason for the first two; if it fails, stops partway or is still going after 15 minutes, it says so and gives no figures for the first two. Either way the third is reported.

### Conversations and turns in the app

Three new tables:

- `conversations`: `conversation_id` (`conversation-` and a UUID, 49 letters, digits and hyphens, which works as a Runtime session id and as the Memory's session), `handler_id`, `title` (the first question, up to 120 characters), `turns` (how many, for the conditional update) and `created_at`.
- `copilot_turns`: `turn_id`, `conversation_id`, `number`, `message`, `status` (`working`, `waiting_for_confirmation`, `done` or `failed`), `started_at`, `paused_at`, `answered_at`, `finished_at`, `answer`, `model_calls`, `cost`, `failure`, `confirmation` (the card, with the held decision's `decided_at`), `confirmation_answer` and `canceled_because`.
- `copilot_steps`: the cards: `step_id`, `turn_id`, `tool`, `kind` (`claims`, `customers`, `context`, `work`, `memory` or `action`), `input`, `asked`, `status` (`working`, `done`, `refused` or `failed`), `answer`, `reason`, `sources`, `started_at` and `finished_at`.

- A turn reads as `stopped` while it is working and its start, or the answer to its confirmation, was more than 20 minutes ago. A turn waiting for a confirmation is never stopped. A turn's seconds leave out the wait for the handler; a working card's seconds are counted by the app at each read.
- One turn at a time: a new turn moves the conversation's `turns` from n to n + 1 with a conditional update that checks its row count, so of two messages at once one is refused. A message is refused while the latest turn is working and not stopped, or waiting for a confirmation; after a done, failed or stopped turn it goes ahead.
- The Copilot's records of a turn (`start_copilot_step`, `finish_copilot_step`, `finish_turn`, `pause_turn` and `fail_turn`) take the handler's sign-in like everything else it does, and change only that handler's own conversation, and only its latest turn while it is working and not stopped, by the same rule the reads use. A stopped turn stays stopped: a late card, pause, answer or failure is refused with a 409 and changes nothing, even while it is still the latest turn. Nothing in them pays or decides.
- Asking the Copilot goes through `asking.commit_and_ask`, as asking the agent does: commit, ask, and when it didn't take the work, record why. A message the Copilot didn't take fails its turn with the reason; an answer it didn't take is undone. A timeout leaves the turn working.

| Operation | Route | Who |
| --- | --- | --- |
| `list_conversations` | `GET /api/copilot/conversations` | A signed-in handler: their own, newest first |
| `start_conversation` | `POST /api/copilot/conversations`, body `{message}`, 202 | A signed-in handler |
| `get_conversation` | `GET /api/copilot/conversations/{conversation_id}` | The conversation's handler (a 404 for anyone else) |
| `send_message` | `POST /api/copilot/conversations/{conversation_id}/messages`, body `{message}`, 202 | The conversation's handler |
| `answer_confirmation` | `POST /api/copilot/conversations/{conversation_id}/confirmation`, body `{turn_id, answer}`, 202 | The conversation's handler |
| `get_copilot_model` | `GET /api/copilot/model` | A signed-in handler |
| `start_copilot_step` | `POST /api/copilot/turns/{turn_id}/steps`, body `{tool, kind, input, asked}` | The turn's handler |
| `finish_copilot_step` | `POST /api/copilot/turns/{turn_id}/steps/{step_id}/finish`, body `{status, answer, reason, sources}` | The turn's handler |
| `finish_turn` | `POST /api/copilot/turns/{turn_id}/finish`, body `{answer, model_calls, cost}` | The turn's handler |
| `pause_turn` | `POST /api/copilot/turns/{turn_id}/pause`, body `{claim_id}` | The turn's handler |
| `fail_turn` | `POST /api/copilot/turns/{turn_id}/failure`, body `{reason}` | The turn's handler |
| `find_customers` | `GET /api/customers?name=...` | A signed-in handler |
| `get_customer` | `GET /api/customers/{customer_id}` | A signed-in handler |
| `count_payouts_over_limit` | `GET /api/payouts/over-limit` | A signed-in handler |
| `get_run` (changed) | `GET /api/runs/{run_id}` | The agent's key or a signed-in handler |

- A message is required, up to 4,000 characters; a blank one or a longer one is a 422. An answer to a confirmation names the turn whose card was shown, and its `answer` is `sign_off` or `cancel`.
- `find_customers` finds customers whose name holds the words given, ignoring case, with their ids. `get_customer` gives who they are, without their email, phone, address or date of birth, as `get_claim_history` leaves them out, their policies, their earlier claims and their claims in the queue.
- `start_dispatch` and `start_evaluation` answer 202 with `{status, run_id, number}`; the dashboard reads only the status, as now.
- Every operation keeps an `operation_id`, a one-line docstring and no optional inputs (`reason` is required and may be `null`), and `backend/tests/gates.py` lists each new one under its gate, `get_run` among the shared reads. The claim agent's API document keeps its six operations.

The Copilot's tools, each a card of its kind:

| Kind | Tools |
| --- | --- |
| Claims | `list_claims`, `get_claim`, `list_steps`, `what_needs_a_handler` |
| Customers and policies | `find_customers`, `get_customer`, `get_policy` |
| The context layer | `lookup_term`, `describe_fields`, `get_plan`, `get_claim_rules`, `search_reference_data`, `search_documents`, `read_section` |
| The agent's work | `get_latest_dispatch`, `list_evaluations`, `get_settings`, `wait_for_run` |
| Memory | `search_memory` (the lookup at the start of a turn, in code) |
| Actions | `start_dispatch`, `start_evaluation`, `send_back_claim`, `sign_off_claim`, `check_success_criteria` |

A card's main input is its inputs' values, such as `get_claim CLM-1012` or `start_dispatch 10`, and its text is trimmed to 2,000 characters.

### From the app to the Copilot

| What happened | Laptop route (httpx) | Runtime route (boto3) | The handler gets | The turn |
| --- | --- | --- | --- | --- |
| Accepted | 200 `{"accepted": true}` | the same, read from `response["response"]` | 202 with the conversation | working |
| Refused | 200 `{"refused": ...}` | the same | 409 with the reason | failed with the reason |
| Never reached | `ConnectError` and the rest of today's list | botocore's `ConnectionError` | 503 "The Copilot isn't running" | failed |
| A conflict | (none) | `ConflictException`, retried after 1, 2 and then 4 seconds while the retry can still end within the call's budget, then as never reached | 503, as above | failed |
| Error answer | a status of 400 or more, or neither answer | `ClientError`, a `statusCode` of 400 or more, or neither answer | 502 "The Copilot couldn't take the message: ..." | failed |
| Sent, then a timeout or a cut-off answer | any other `httpx.TransportError` | any other exception | 503 telling the handler to reload | left working |

- For an answer to a confirmation, the four failures undo the answer rather than failing the turn.
- Laptop: `POST {UNDERCOVER_COPILOT}/invocations` with the payload, no `Authorization` and a 10-second timeout. Runtime: `invoke_agent_runtime(agentRuntimeArn=UNDERCOVER_COPILOT_RUNTIME, runtimeSessionId=conversation_id, payload=...)`, one attempt each try, 2 seconds to connect and 15 to read, so a turn soon after the last one reaches the same session and a later one starts a new session under the same id. (Built with 20 to read at first; the whole-branch review found that only one retry then fits once conflicts take any time to come back, so the read is 15.)
- The call's budget is 25 seconds, inside the app's 30 on Lambda: a conflict is retried only while the time spent, the wait and a whole try (2 seconds to connect and 15 to read) still fit it, so a start makes four tries at most: at once, after 1 second, after 2 more and after 4 more. The agent's calls to Runtime share the same client, so they now wait 2 seconds to connect too. A conflict comes back before the call reaches the Copilot, so it is known not to have started; an answer lost once sent is still "may have started".
- `runtime_calls.py` keeps botocore's logger at INFO or above, whatever the app's own logging, since botocore's DEBUG lines hold a request's payload, and the Copilot's payload holds the handler's sign-in.
- Payloads: `{"operation": "health"}`, `{"operation": "take_turn", "conversation_id", "turn_id", "sign_in"}` and `{"operation": "answer_confirmation", "conversation_id", "turn_id", "sign_in"}`, read with a Pydantic discriminated union, strict, with extra inputs forbidden.
- The Copilot answers `{"accepted": true}` once its checks pass and the turn is registered with `app.add_async_task` and started on a thread of its own, so `/ping` says `HealthyBusy` until it ends; `{"refused": "..."}` for a sign-in the app refuses, a conversation it doesn't find, a turn that isn't the latest working one, a turn already working in that conversation in its process, or an answer with no interrupt waiting or no answer recorded; and `{"healthy": true}` for the health check.

### Getting ready

- Importing `agent.copilot.entrypoint` or `runtime.copilot` reads no setting a missing value would break, opens no connection, fetches nothing and starts no thread.
- The first request, the health check included, gets ready once in the process: on Runtime it reseeds `random` and fetches `OPENROUTER_API_KEY` and `DATABASE_URL` from AgentCore Identity, and nothing else; then it sets up the report lines and opens the checkpoint pool. A failure answers 503, "The Copilot couldn't get ready: ...", and the next request tries again.
- It checks no key, on the laptop or on Runtime: everything it does carries the handler's sign-in, which the app checks on every call. On the laptop it listens only on 127.0.0.1.

### The memory of each handler

- On only when `UNDERCOVER_COPILOT_MEMORY_ID` is set, read as a turn is built. The Copilot works the same without it.
- The search covers `("handlers", <handler id>)`, which reaches `/handlers/<handler id>/preferences/` and `/handlers/<handler id>/facts/`, the namespaces the notebook's two strategies write. A memory's text is taken from its value, as the claim agent's search does.
- The save is two events after the turn's answer, a message and an answer, with the handler as the actor and the conversation as the session. AgentCore makes notes from them in about a minute and a half, so they show in the next conversation.

### The sidebar

- On the right of every signed-in page, about 400 pixels wide, open the first time. Collapsed, it's a slim tab with its own icon; the browser remembers the choice, and the conversation open, for each handler. The page beside it stays usable, its own layouts answering to the width they have (container queries), not the window's. Below 1,100 pixels the sidebar opens over the page.
- Top: New conversation, and the earlier conversations, newest first, each titled with its first question. Foot: the message box, "Ask the Copilot", where Enter sends and Shift+Enter starts a new line, disabled while a turn works or a confirmation waits, then "Signed in as Dana Whitfield".
- An empty conversation greets the handler by first name and offers four questions to click: "What needs me today?", "How did the latest dispatch go?", "Are we meeting the success criteria we agreed?" and "What does the policy wording say about baggage delays?".
- A turn: the handler's message on the right; its cards, each arriving with a short fade and rise (none with reduced motion); a small working indicator below the last card while the turn works and no card does; the confirmation card while one waits; then the answer on the left, formatted, with claim ids linking to their pages, and a line in small print: "4 model calls, $0.0021, 12 seconds". A failed turn says what went wrong; a stopped turn says it stopped.
- A card: the kind's icon (Lucide's `FileText` for claims, `Users` for customers and policies, `BookOpen` for the context layer, `Bot` for the agent's work, `Brain` for memory, `Zap` for actions), the tool's own name and its main input in JetBrains Mono, and its state: a spinner and the seconds so far, a check and the time it took, or a Raspberry Refused or Failed chip with the reason. Action cards have a tinted Marigold fill. A click opens what was asked and what came back, and for a context layer answer each file with its system, owner and review date.
- The confirmation card: the claim with a link, the customer, the amount and the agent's reason, with Sign off and pay, and Cancel, which send the card's own turn id. Once answered it shows the outcome described above, from the sign-off's actual result.
- The sidebar reads the conversation about once a second while a turn works, and not while it's done, failed, stopped or waiting for a confirmation. It reads the earlier conversations when their list opens.
- Light and dark mode, the fonts, the colors and the icons follow `docs/BRAND.md`: panels with no outline and a faint shadow, no one-edge borders, no gradients.

### The platform team's folders

`agentcore/agentcore.json` gets a second runtime, `copilot`, built as a zip from `runtime/` like `agent`, with `copilot.py` as its entry point, Python 3.12, HTTP, a 60-second idle timeout, no instrumentation and `copilot_policy.json` as its additional policy. `cdk-stack.ts` already stages `runtime/` with `agent/` once for every runtime and puts every runtime on V2; `UNDERCOVER_COPILOT_MEMORY_ID` joins its `SETTINGS`, so the deploy hands both runtimes the four settings from `agentcore/.env.local`; each reads only its own. The project's three credentials stay as they are, and the Copilot fetches two of them. One `agentcore deploy` deploys both as `undercover_default_agent` and `undercover_default_copilot`. `git diff c84d998 -- agentcore runtime` shows only these changes.

### The tests

- The Copilot's tests live in `agent/tests/` beside the claim agent's, so they share its fixtures: the backend through `TestClient`, the real context layer on a local port, the Gateway stand-in, the memory stand-in and stub models. Handlers sign in with tokens from `backend/tests/sign_in.py`. Their helpers go in modules of their own.
- A stub model plays each turn's replies, with usage and a cost. The graph runs on an `InMemorySaver`; "a freshly built Copilot" is a new graph, context and model on the same saver.
- The backend's tests use a stand-in for the Copilot that keeps each payload and answers as a test asks: accepted, refused, an error answer, never reached, a timeout or, on the Runtime route, a conflict.
- `waiting.POLL` and `waiting.WAIT` are module constants the tests shorten; the conflict's waits run on a clock of the test's own. A stopped turn is made by setting `started_at` 21 minutes back.
- The sign-in never saved: a test plays a whole turn and a confirmation, then looks for the token in every table, in every checkpoint and write the saver holds, in the memory stand-in's events and in the logs at DEBUG, and finds it nowhere.
- The Runtime route's log test uses the real boto3 client, with fake AWS credentials and a fake token, and stubs only the network send with a `before-send` handler that returns the answer, so botocore serializes and handles the request as it would on Lambda. It makes no AWS request.
- `e2e/copilot_stand_in.ts` answers `/ping`, the health check, `take_turn` and `answer_confirmation`, and plays a scripted turn through the test backend with the handler's sign-in it was given: it checks the sign-in with `/api/me`, reads the turn's message, records its cards and answers.

### Following the notebooks

`labs/week3day5_lab1.ipynb` expects what the brief does, and the plan uses its names: a second runtime `copilot` beside `agent` in `agentcore/agentcore.json`, both from one package with the `runtime` group, deployed by one `agentcore deploy` as `undercover_default_copilot`; `UNDERCOVER_COPILOT_MEMORY_ID` written to `agentcore/.env.local` beside the other three settings; the Memory `undercover_copilot_memory` with `handler_preferences` on `/handlers/{actorId}/preferences/` and `handler_facts` on `/handlers/{actorId}/facts/`, the actor the handler's id (`HND-01` for Dana Whitfield) and the session the conversation; `UNDERCOVER_COPILOT_RUNTIME` on the app's function; `{"operation": "health"}` answering `{"healthy": true}` once the Copilot has fetched its secrets and opened its pool; the conversation's id as the session id; and only the context layer's tools on the Gateway. `labs/week3day4_lab1.ipynb` and `labs/undercoverlab/` resume a pause from a thread in Supabase in a new session, as an answer to a confirmation does. Nothing in them differs from the brief, and the plan runs none of them.

### Checked against the code standards

- One way to call each service: the Copilot reaches the app only through `copilot/app_api.py` on the one client in `connection.py`, the context layer only through `tool_route.py`'s route, the memory only through `copilot/memory.py`, Identity only through `identity.py` and the checkpoints only through `checkpoints.py`. The backend reaches the Copilot only through `copilot_service.py`, where its two settings are written, on `runtime_calls.py`, where `/invocations` and the `bedrock-agentcore` client are written.
- Each module has one job, and no module borrows another's helpers: what both agents need, the checkpoints, the route, the context tools, the AgentCore store and the AgentCore app's plumbing, moves into a module of its own, and so does what both services in the backend need.
- The framework's own way: a hand-written `StateGraph` with `ToolNode`, conditional edges, `interrupt()` in a node of its own, `Command(resume=...)`, `get_state().interrupts`, `Overwrite`, `context_schema` with `ToolRuntime`, a store passed at compile, a Pydantic model bound as the sign-off's schema; `BedrockAgentCoreApp`'s entrypoint, async tasks and `/ping`; a Pydantic discriminated union for the payloads; FastAPI dependencies; SQLAlchemy conditional updates for one turn at a time and each move of a turn; `react-markdown` rather than a formatter of our own; React hooks and `useLoad`.
- Functions do one job: getting ready, checking the sign-in, reading a payload and starting the turn are separate in the entry point; running the graph and telling the app how it ended are separate in `turns.py`; starting, waiting and building the table are separate in `criteria.py`.
- Instructions as goals: they give the Copilot its goal, who it works for, what it can see and do, the success criteria and how to answer, and script no steps. What must always happen is code: the check of the sign-in first, the memory's lookup and save, the check before the pause, the pause itself, the answer after Cancel, the wait, and the whole answer on the success criteria.
- `docs/CODE_STANDARDS.md` gets the Copilot as a part of its own, with the same rules as the other parts (phase 4).

### How the criteria are checked

pytest, vitest and Playwright run with `npm run check` and never read `.env`. Grep checks run from the repo root. The live checks in phase 6 run against Supabase with `npm run dev`, on the default model, on the direct route with no `UNDERCOVER_GATEWAY_URL`, `UNDERCOVER_MEMORY_ID`, `UNDERCOVER_COPILOT_MEMORY_ID`, `UNDERCOVER_AGENT_RUNTIME` or `UNDERCOVER_COPILOT_RUNTIME`, after one `npm run seed`, through the Playwright MCP server.

## Phase 1: The app keeps the Copilot's conversations

Add the three tables and their models, `conversations.py`, the `copilot.py` and `customers.py` routers and `count_payouts_over_limit`. Split `runtime_calls.py` out of `agent_service.py` and add `copilot_service.py`. Let a handler read a run, have the starts name their run, add `SignIn`, refuse the agent's key on a handler's routes, and keep botocore's logger above DEBUG in `runtime_calls.py`.

- [x] pytest: Dana's `start_conversation` with "What needs me today?" creates a conversation whose id is `conversation-` and a UUID, titled with the message, with one working turn; it commits, then posts `{"operation": "take_turn", "conversation_id": ..., "turn_id": ..., "sign_in": <Dana's token>}` to `http://127.0.0.1:8081/invocations`, or `UNDERCOVER_COPILOT`'s, with no `Authorization` or `X-API-Key` and a 10-second timeout; the stand-in, reading through a fresh connection, finds the turn; the answer is 202 with the conversation
- [x] pytest: `send_message` adds turn 2 the same way; it's refused with a 409 while turn 1 is working, and while it waits for a confirmation, "Answer the confirmation first"; it goes ahead after a done, failed or stopped turn; a blank message and one of 4,001 characters get a 422
- [x] pytest: two messages released together from a `threading.Barrier`: one gets a 202 and the other a 409, and the conversation has one new turn
- [x] pytest, Runtime route: with `UNDERCOVER_COPILOT_RUNTIME` set, the stand-in client gets the ARN, the payload and the conversation's id as the session id on every turn of that conversation; a `ConflictException` is retried after 1, 2 and 4 seconds and then gives a 503 (after 1 and 2 seconds in the first build, with 20 seconds to read); any other `ClientError` is tried once
- [x] pytest, Runtime route: with conflicts that each come back after a delay, the tries and waits stop once another would pass the 25-second budget, whatever the count, and a 503 says the Copilot isn't running; the test keeps the real waits and budget and runs them on a clock of its own
- [x] pytest, each route: a refusal gives a 409 with the reason and fails the turn with it; never reached a 503 "The Copilot isn't running"; an error answer a 502; each of those fails the turn; a timeout gives the 503 to reload and leaves the turn working
- [x] pytest: the Copilot's records, as Dana: `start_copilot_step` makes a working card whose seconds grow between reads; `finish_copilot_step` makes it done, refused or failed with its answer, reason and sources; `finish_turn` makes the turn done with its answer, model calls, cost and seconds; `fail_turn` failed with its reason; each gets a 409 for a turn that isn't working or isn't the latest
- [x] pytest (late updates): a working turn aged past 20 minutes reads as stopped; then a card, a finished card, a pause, an answer and a failure for it each get a 409, and it still reads as stopped; the same after a newer turn has begun, whose cards and status are untouched
- [x] pytest: `pause_turn` on CLM-1003 held for sign-off makes the turn wait with a card of CLM-1003, its customer, $3,750.00 and the agent's reason, all from the app's records, keeping the decision's `decided_at`; a claim not waiting for sign-off and an evaluation's copy get a 409
- [x] pytest: `answer_confirmation` with the waiting turn's id and `sign_off` records the answer and when, moves the turn back to working and sends `answer_confirmation` with Dana's token; when the Copilot doesn't take it the turn waits again with no answer; with nothing waiting it gets a 409; `cancel` is recorded the same way
- [x] pytest (a stale tab): an answer naming an older turn while a newer one waits, and an answer to a turn already canceled, each get a 409, send nothing to the Copilot and pay nothing
- [x] pytest (a changed claim): after the card was shown, CLM-1003 is sent back and decided again with the same payout and another reason, or signed off elsewhere: Cancel is taken as usual; Sign off is taken as a Cancel with "The claim changed since the card was shown", the Copilot is asked to carry on, nothing is paid, and once the turn ends a new message goes ahead
- [x] pytest: a turn working 21 minutes after its start, or after the answer to its confirmation, reads as `stopped`; one waiting for a confirmation never does; a turn paused for 10 minutes counts its seconds without them
- [x] pytest: Marcus Oyelaran gets a 404 for Dana's conversation on every conversation and turn route; `list_conversations` gives each handler their own, newest first, each with its title
- [x] pytest: after a turn played through every route, no row of any table holds Dana's token, and no log line at DEBUG does
- [x] pytest (the Runtime route's logs): with the app's logging at DEBUG, a turn sent on the Runtime route through the real boto3 client, with fake credentials and a fake token and only the send stubbed by a `before-send` handler, leaves botocore's logger at INFO or above and no log line holding the token; no AWS request is made
- [x] pytest: a request with the agent's key and Dana's token gets a 403 on `get_settings` and is the agent's on `list_claims`; with Dana's token alone, `get_settings` answers
- [x] pytest: `find_customers` with "maya" finds Maya Patel with her id; a blank name gets a 422; `get_customer` on CUS-3001 gives her name, her policies, CLM-0412 among her earlier claims and CLM-1001 among her claims in the queue, and no `email`, `phone`, `address` or `date_of_birth`; an unknown customer gets a 404
- [x] pytest: `count_payouts_over_limit` gives 0 and 0 after seeding; after Dana signs off a held payout of $1,350.00, 1 and 1; with a payment of $1,200.00 over its decision's $1,000.00 limit and no sign-off written into the tables, 2 and 1; a paid approval within the limit and an evaluation's copy aren't counted
- [x] pytest: `get_run` answers a signed-in handler; `start_dispatch` and `start_evaluation` answer 202 with the run's id and number; `get_copilot_model` gives `openai/gpt-6-luna` at `low`, or the model in `MODEL_NAME` at `default`
- [x] pytest: the agent's four operations send the same payloads on the same routes as before the split, a new session for each call
- [x] pytest: seeding empties the conversations, turns and cards
- [x] The gates test and the API rules test pass with every new operation listed under its gate and `get_run` among the shared reads
- [x] `grep -rln "UNDERCOVER_COPILOT" backend --include='*.py'` finds only `backend/copilot_service.py` and tests; `grep -rln "invocations\|invoke_agent_runtime" backend --include='*.py'` finds only `backend/runtime_calls.py` and tests
- [x] `npm run check` passes with `.env` moved out of the way

## Phase 2: The Copilot's graph, its lookups and actions, and the pause

Move the shared parts out of the claim agent's modules: `checkpoints.py`, `tool_route.py`, `context_tools.py` and `agentcore_memory.py`. Add `connection.call_as`, and in `agent/copilot/` the API on the app, the tools, the cards, the graph with its pause, the instructions and the turns, run as functions; the AgentCore app comes in phase 4.

- [x] Stub test (the loop): Dana asks "Why does CLM-1003 need me?"; the stub calls `get_claim`, `list_steps` and `read_section`, then answers; the turn has three cards in order, each recorded working and then done with its time, the lookup's card with its file, system, owner and review date; the turn is done with the answer, 4 model calls and their cost
- [x] Stub test: the model sees the handler's name, role and that she can sign off over the limit in its system message; Marcus Oyelaran's says he can't
- [x] Stub test (a refusal passed on): `start_dispatch` while a dispatch is running records a refused action card, "A dispatch is running", and the model's next input holds the refusal
- [x] Stub test: `start_dispatch` with 10 starts a dispatch of 10 and gives the model its id and number; with `null`, the settings' 25; `start_evaluation` with the held-out set's tiny claims and `null` starts it with 25
- [x] Stub test: `send_back_claim` on CLM-1008 as Dana sends it back with the note, "Sent back by Dana Whitfield", and the agent's stand-in gets the resume; as Marcus it records a refused card with the app's reason
- [x] Stub test (the pause): Dana's `sign_off_claim` on CLM-1003 pauses the graph with one interrupt and pays nothing; the app's turn waits with the card of CLM-1003, its customer, $3,750.00 and the agent's reason, though the stub's message named $1.00
- [x] Stub test: a freshly built Copilot on the same saver, given Dana's answer `sign_off`, signs CLM-1003 off once as Dana Whitfield, which pays it; records a done action card; and the model answers; no node before the pause runs again: the model calls before it and the cards before it are as they were
- [x] Stub test: answered `cancel`, nothing is paid, the turn answers "I haven't signed off CLM-1003. What would you like to do instead?", and the model isn't called after the answer
- [x] Stub test: answered with a Cancel the app made because the claim changed, nothing is paid, the turn answers "The claim changed since the card was shown, so I canceled this sign-off without making a payment. Please ask again.", with no model call after the answer, and the conversation takes a new message
- [x] Stub test (one sign-off a turn): after a confirmed sign-off of CLM-1003, the stub asks to sign off CLM-1008 in the same turn; it gets a refused card and "One sign-off a turn. Please ask me again for the next one.", there's no second pause and no second payment, and the turn ends with the model's answer
- [x] Stub test: Marcus asks to sign off CLM-1003: no pause and no call to the app's sign-off; a refused `sign_off_claim` card says he can't sign off over the limit, and the model's next input says why; a claim that isn't waiting for sign-off is refused the same way for Dana
- [x] Stub test: `sign_off` run again after the app has paid the claim for Dana counts it as done, with one payment and no refusal
- [x] Stub test (one tool at a time): a stub reply asking for `get_claim`, `get_policy` and `lookup_term` at once runs them in that order, each card finished before the next starts, and none overlapping
- [x] Stub test: the 26th model call of a turn fails it, "The Copilot made 25 model calls without finishing"; the next turn's count starts from zero
- [x] Stub test (a failed turn and a message after it): a tool that raises marks its card failed and fails the turn with the error in one line; the next message closes the open tool call, and the stub's next input has an answer for every tool call before the new message
- [x] Stub test (who's signed in first): a sign-in the app refuses ends the turn before any model call, and another handler's conversation is refused
- [x] Stub test (the sign-in): every request a turn sends the app carries `Authorization: Bearer <Dana's token>` and no `X-API-Key`, with `UNDERCOVER_API_KEY` set; the token is in none of the saver's checkpoints or writes, the interrupt, the resume or the cards
- [x] Stub test, Gateway route: with the stand-in Gateway, `read_section` goes to `undercover-context___read_section`, signed for `bedrock-agentcore`; its card names `read_section`; the Copilot calls no `undercover-app___` tool
- [x] pytest: the Copilot's tools are the table's but for `wait_for_run`, `what_needs_a_handler` and `check_success_criteria`, which phase 3 adds, each with its kind and a one-line description
- [x] pytest: the claim agent's behavior tests pass unchanged after the shared parts moved; only its boundary tests change, to the new modules, and the tests of the moved checkpoint pool and AgentCore store, which now name `checkpoints` and `agentcore_memory`
- [x] The boundaries test, updated for the shared modules: the harness imports `checkpoints` and `tool_route` where it imported `gateway` and `direct`, and `tools` imports `context_tools`; the Copilot's modules import none of `api`, `improver_api`, `harness`, `dispatcher`, `work`, `entrypoint`, `memory` and `tools`; only `copilot/app_api.py` imports `connection`, and the Copilot's other modules catch the app's refusal as `app_api.Refused`; the claim agent's modules import nothing in `agent/copilot/`; `tool_route` alone imports `gateway` and `direct`; `checkpoints`, `context_tools` and `agentcore_memory` use nothing else in the agent but `routes` and `json_text`, and the claim agent's `memory` uses only `agentcore_memory`
- [x] `grep -rn "create_agent" agent/copilot` finds nothing; `grep -rln "get_evaluation\|/rounds\|/improvement" agent/copilot` finds nothing
- [x] `npm run check` passes with `.env` moved out of the way

## Phase 3: Waiting, the success criteria and the memory of each handler

Add `waiting.py`, `needs_a_handler.py`, `criteria.py` and `copilot/memory.py`, the tools `wait_for_run`, `what_needs_a_handler` and `check_success_criteria`, the state's `criteria`, and the `report_criteria`, `recall` and `remember` nodes. Add the three criteria to `docs/SPEC.md`.

- [x] Stub test (the wait for a dispatch): "Work the queue with 10 agents and tell me what needs me": the stub calls `start_dispatch` with 10, then `wait_for_run` with the id it got; a thread plays the dispatch out through the app as the agent, holding CLM-1003, referring CLM-1018 and finishing the run; the wait reads `get_run` with Dana's sign-in each interval, makes no model call, and answers with the summary and what needs a handler: CLM-1003's held payout, the referral and nothing else; its card is working until then
- [x] Stub test: a sent-back claim the agent hasn't taken and a claim left for a handler are in what needs a handler; a decided approval isn't
- [x] pytest: the Copilot's tools are now exactly the table's, each with its kind and a one-line description
- [x] Stub test: a run still going after `WAIT` gets "still going" and where to follow it, and a stopped run gets why
- [x] Stub test (the success criteria): `check_success_criteria` starts one evaluation of the whole held-out set with the settings' 25 claim agents; a thread finishes it with copies decided so its straight-through share is 80% and its accuracy 88%; with one payout over the limit signed off, the table says 80% against at least 70%, 88% against the 60% objective in Settings, "1 of 1 signed off", Yes three times, and "All three are met"
- [x] Stub test (the answer written in code): after `check_success_criteria`, the turn's answer is exactly the table and its verdict line as `criteria.py` built them; the stub isn't called after the tool, its calls stopping at the one that asked for it; the app records that answer, and the memory stand-in saves the same answer; a later turn in the conversation that doesn't check the criteria answers from the model as usual
- [x] Stub test: with none paid over the limit, the third is met and says "None paid over the limit yet"; with a payment over its decision's limit and no sign-off written into the tables beside one signed off, it says "1 of 2 signed off", "No", and the line says two of the three are met
- [x] Stub test: an evaluation that fails gives no figures for the first two and says why, and still reports the third; so does one still going after `WAIT`; so does a start the app refuses, with its reason
- [x] Stub test: with the accuracy objective changed in Settings to 90%, the same evaluation fails the second, "No", and the line says two of the three are met
- [x] Stub test (the memory): with the memory stand-in holding "Dana likes amounts first, in short bullet points" under `/handlers/HND-01/preferences/`, the turn's first card is `search_memory` with what it found, and the model's system message holds it; after the turn the stand-in has two events for actor HND-01 in the conversation's session, the message and the answer, and no tool call, tool result or token
- [x] Stub test: Marcus's turn searches only `("handlers", "HND-02")` and finds nothing of Dana's
- [x] Stub test: a turn paused for a confirmation saves to memory once, after its answer
- [x] Stub test: with memory off there's no `search_memory` card and no save; a memory that can't be reached gives a refused card, and the turn is still answered, with the save's failure logged as a warning
- [x] The boundaries test: `copilot/memory` uses only `agentcore_memory`, and `grep -rln "UNDERCOVER_COPILOT_MEMORY_ID" agent` finds only `agent/copilot/memory.py` and tests
- [x] `docs/SPEC.md` holds the three success criteria and what the Copilot does
- [x] `npm run check` passes with `.env` moved out of the way

## Phase 4: The Copilot as an AgentCore app, on the laptop and on Runtime

Move the AgentCore apps' shared parts to `agentcore_app.py` and have `identity.fetch_credentials` take the settings to fetch. Write `agent/copilot/entrypoint.py`, `runtime/copilot.py` and `runtime/copilot_policy.json`, add the `copilot` runtime to `agentcore/agentcore.json` and its setting to `cdk-stack.ts`, and serve the Copilot with `npm run dev`. Update `docs/CODE_STANDARDS.md`, `docs/TECH_STACK.md` and `docs/PROCESS.md`.

- [x] pytest: in a subprocess with no settings but `PATH` (and the credentials' names, as on Runtime) and sockets that refuse to connect, `import runtime.copilot` succeeds, and `runtime.copilot.app` is `agent.copilot.entrypoint.app`
- [x] pytest: on Runtime, with all three credentials named, the Copilot's first request asks Identity for `OPENROUTER_API_KEY` and `DATABASE_URL` only, reseeds `random` and opens the pool before it answers; a second request fetches nothing; the claim agent still fetches its three
- [x] pytest: when getting ready fails, the request gets a 503 with the error and the next is answered; `{"operation": "health"}` answers `{"healthy": true}` once ready
- [x] pytest: `take_turn` reads `/api/me` and the conversation with the sign-in before it answers; accepted, the turn runs in the background, `/ping` says `HealthyBusy` until it ends and `Healthy` after, and after a turn that raised
- [x] pytest: `take_turn` refuses a sign-in the app refuses, another handler's conversation, a turn that isn't the latest working one, and a second turn in a conversation whose turn is still working in the process; a turn in another conversation is accepted beside it
- [x] pytest: an unknown operation, a missing input, an extra input and a `sign_in` that isn't a string each get a 400 that says what's wrong, without the payload's values
- [x] pytest: `answer_confirmation` resumes a paused conversation with the answer the app recorded; it refuses a conversation with no interrupt waiting and a turn with no answer recorded
- [x] pytest (the laptop, end to end): the backend's `start_conversation`, with `UNDERCOVER_COPILOT` at the Copilot's app on a local port, has the stub model's turn recorded and answered; then a turn that pauses on CLM-1008, answered with `answer_confirmation`, pays it as Dana Whitfield; no request to the Copilot carries a key
- [x] pytest (across sessions): a turn paused by one Copilot app is answered by another, freshly imported with nothing ready, on the same saver, and the claim is paid once
- [x] pytest: over a whole turn and its answer through the app, no log line at DEBUG holds the sign-in
- [x] `npm run check:runtime` imports `runtime.main` and `runtime.copilot` with only the `runtime` group
- [x] `npm run dev` serves the Copilot on 127.0.0.1:8081 with reload: `curl 127.0.0.1:8081/ping` answers, and nothing listens on 8081 on another address
- [x] `agentcore/agentcore.json` has the runtimes `agent` and `copilot`; `git diff c84d998 -- agentcore runtime` shows only the `copilot` runtime, `UNDERCOVER_COPILOT_MEMORY_ID` in `SETTINGS`, `runtime/copilot.py` and `runtime/copilot_policy.json`
- [x] `grep -rln "AGENTCORE_CREDENTIAL_\|requires_api_key" agent --include='*.py'` finds only `agent/identity.py` and tests; `grep -rn "fastapi" agent --include='*.py'` finds only tests
- [x] `docs/CODE_STANDARDS.md` has the Copilot as a part of its own and the shared modules; `docs/TECH_STACK.md` describes the Copilot, its two routes from the app and its deployment; `docs/PROCESS.md` has the Copilot on port 8081 and the runtime check of both files
- [x] `npm run check` passes with `.env` moved out of the way

## Phase 5: The sidebar

Build the sidebar and its parts, `freshAccessToken()`, `keepAsking` in `useLoad`, and the Copilot's calls in `api.ts`. Add `e2e/copilot_stand_in.ts` and the Copilot's end-to-end tests.

SIDENOTE: Make sure the Copilot sidebar looks stunning, elegant, enterprise-grade - an interactive and compelling UX, fitting for a capstone project. Take the time to design and implement this UI to be outstanding. Take screenshots of it and iterate until you're very satisfied.

- [x] vitest: the sidebar is open the first time; collapsed, it shows the tab with its icon, and it stays collapsed after a reload; it opens again from the tab
- [x] e2e, since jsdom lays nothing out: on a narrow window the sidebar opens over the page (the e2e check at 800 wide below)
- [x] vitest: an empty conversation greets Dana by first name with the four questions; clicking one sends it
- [x] vitest: Enter sends and Shift+Enter starts a new line; the box is disabled while a turn works; while a confirmation waits it asks for the answer first; the foot says "Signed in as Dana Whitfield"
- [x] vitest, with fake timers: the conversation is read about once a second while a turn works, and not once it's done, failed, stopped or waiting
- [x] vitest: a card shows its kind's icon, its tool and main input, a spinner with its seconds while working, a check with its time when done, and a Refused or Failed chip with the reason; an action card has its fill; a click opens what was asked and came back, with a context layer answer's file and owner
- [x] vitest: the working indicator shows while the turn works and no card does
- [x] vitest: an answer with a paragraph, a list and a table shows them formatted, CLM-1003 links to its page, and the small print gives the model calls, the cost and the seconds
- [x] vitest: the confirmation card shows the claim, the customer, the amount and the reason, and its buttons send its own turn id with `sign_off` or `cancel`
- [x] vitest: after Sign off, the card says "Signing off" while the `sign_off_claim` card works and "Signed off and paid" only once it's done; an accepted answer alone, a refused or failed sign-off, a Cancel and a Cancel because the claim changed never say it, and each shows its own outcome and reason
- [x] vitest: a failed turn shows what went wrong and a stopped turn that it stopped, and the box is enabled after either
- [x] vitest: the earlier conversations are listed newest first by their first questions, and New conversation empties the sidebar
- [x] vitest: a message and an answer renew a sign-in with 19 minutes left before they're sent, and not one with 21
- [x] e2e: the sidebar is open beside the queue, a claim, the Scoreboard, and the Improvement, Configuration and Settings pages at 1280 wide; collapsed, it stays collapsed after a reload
- [x] e2e: at 800 wide the sidebar opens over the page
- [x] e2e: Dana asks a question; the stand-in's turn shows a lookup card, an action card with its fill, a refused card with the app's reason, and a formatted answer with a table and a claim link, which opens the claim's page; the page beside the sidebar shows the action's change without a reload
- [x] e2e: Dana asks to sign off a held claim; the card shows the claim, customer, amount and reason from the app; the box asks for the answer first; after a reload the card is still there; Sign off and pay shows "Signed off and paid" once the stand-in's sign-off is done, and the claim's page shows "Paid $1,350.00, signed off by Dana Whitfield"
- [x] e2e: Cancel leaves the claim held, and the answer says nothing was signed off
- [x] e2e: the earlier conversations list holds the conversations by their first questions, and opening one shows its turns
- [x] e2e: every existing spec passes with the sidebar open
- [x] `npm run check` passes with `.env` moved out of the way

## Phase 6: The docs and the live checks

Bring `docs/SPEC.md`, `docs/TECH_STACK.md`, `docs/CODE_STANDARDS.md`, `docs/PROCESS.md` and `docs/STATUS.md` up to date, with the known gaps: a turn that works past its sign-in's hour is refused partway and fails (as built, it stops and shows as working until it reads as stopped, since the app can't be told either); a turn stopped partway shows as stopped only after 20 minutes; the Copilot's records take the handler's sign-in, so a handler could write to their own conversation's records through the API, though nothing in them pays or decides; the memory's notes take about a minute and a half to appear; a Copilot that stops after saving its pause and before telling the app leaves the graph waiting for an answer while the app shows the turn working, with no card, until it shows as stopped; a Copilot that stops after saving its result and before telling the app leaves the sidebar without an answer or a confirmation's outcome the saved graph already has, though a sign-off may have paid or the memory saved, and the turn shows as working and then stopped, with nothing to put the two together. Then run the live checks, after one reseed, with Lab 1's `agentcore dev` stopped.

- [x] `npm run check` passes with `.env` moved out of the way
- [x] `npm run seed` prints the 26 claims seeded into the `undercover` schema on Postgres
- [x] With `npm run dev` stopped, `uv run --env-file .env --isolated --only-group runtime python -m runtime.copilot` serves the Copilot on port 8080, and `{"operation": "health"}` posted to `/invocations` answers `{"healthy": true}`
- [x] With `npm run dev` running, through the Playwright MCP server, signed in as Dana with no message sent: the sidebar's greeting, open and collapsed, beside the queue and over a narrow window, in light and dark mode, with no console errors, no one-edge borders and no gradients
- [x] With `npm run dev` running and Dana Whitfield signed in, in one conversation, with the queue page beside it: "Work the queue with 10 agents and tell me what needs me." starts a dispatch at N=10, the queue fills in while the wait's card counts, and the answer lists the held payouts, referrals and anything left, matching the queue
- [ ] "Why does CLM-... need me?", about one of the held payouts, answers from the claim, the agent's steps and the context layer, with the cards showing each lookup's file and owner (not met as written: the answers came from the claim, the agent's steps, the policy and the settings, naming the approval limit, but the Copilot looked up the context layer only when asked to check a section, whose card showed its file and owner; see `docs/STATUS.md`)
- [x] "Send it back with a note", asking the agent to look again at something in that claim: the claim's page shows the note "Sent back by Dana Whitfield", and the claim agent decides it again
- [x] "Sign off on another one" (the Copilot asked which of the two still held, and was told CLM-1011): the Copilot picks another held payout, the card shows its claim, customer, amount and reason, and Sign off and pay pays it; its page says "Paid $..., signed off by Dana Whitfield"
- [x] "Are we meeting the success criteria we agreed?" runs an evaluation of the whole held-out set at the settings' 25 and answers with the table and its verdict line, written in code; the straight-through share and the accuracy match that evaluation on the Scoreboard, the objective matches Settings, and the payouts over the limit match the claims' pages
- [x] After restarting `npm run dev`, the same conversation, picked from the earlier conversations, answers a follow-up about an earlier answer
- [x] Signed in as Marcus Oyelaran, a request to sign off a held payout is declined with the reason, and nothing is paid
- [x] Through the Playwright MCP server, the sidebar with these turns in light and dark mode, with no console errors
- [x] Supabase: no run is left running; the conversation's turns are done; no table holds a sign-in; and the connections as `postgres`, counted through the Supabase MCP server while the Copilot waits for the dispatch and again for the evaluation, are noted in `docs/STATUS.md` with the live results
- [x] What it cost: each turn's model calls and cost, the dispatch, the resume, the evaluation and the judge from the backend's records, beside the rise in the OpenRouter key's usage over the same time, in `docs/STATUS.md`'s "Last live run"

## Not in this plan

- Streaming answers word by word, stopping a turn partway, sharing, renaming or deleting conversations, and Langfuse tracing for the Copilot, as the brief says.
- The Copilot reading the claim agent's memory of customers, and changing settings, the configuration or improvement rounds through it; it says where on the dashboard to do those.
- Creating anything on AWS: `labs/week3day5_lab1.ipynb` creates the Copilot's Memory, deploys both runtimes and points the app at them, and checks the memory on the deployed product.
- Declining a held payout outright, real payments and messages to customers, as `docs/SPEC.md` says.
