# The UnderCover Copilot

From the head of claims operations, with our IT team and our platform team.

SIDENOTE: For consistency with the course, please build the Copilot the way the course has built its agents. Its agent loop is a LangGraph `StateGraph` written by hand: a node that calls the model, LangGraph's `ToolNode`, and the loop between them, with a `PostgresSaver` checkpointer, as in `labs/week2day3.ipynb` and the claim agent's graph. Please don't use LangChain's `create_agent` for it. The pause before a sign-off is an `interrupt()` in a node of its own, resumed with `Command(resume=...)`, since LangGraph runs an interrupted node again from the top when it resumes, as the claim agent's wait for a handler is a node of its own. The handler's sign-in reaches the graph and its tools in the graph's context (`context_schema`, read through `ToolRuntime`), never in the config, whose values LangGraph saves with each checkpoint. The Copilot is an AgentCore app of its own, made with `BedrockAgentCoreApp`, with one entrypoint and each turn's work registered as an async task, as the claim agent's AgentCore app does, and it is synchronous throughout, as the claim agent is. `labs/week3day4_lab1.ipynb` and `labs/undercoverlab/` show a pause in one Runtime session resumed in another. Its memory is `AgentCoreMemoryStore` as a LangGraph store, as the claim agent's memory is, with the Memory itself made as in `labs/week3day3.ipynb`. It reaches the context layer over MCP with `MultiServerMCPClient`, as in `labs/week2day2.ipynb`, and through the Gateway as in `labs/week3day2_lab2.ipynb` and `labs/week3day3.ipynb`. `labs/week3day4_lab2.ipynb` deploys the claim agent and points the app at it, and `labs/week3day5_lab1.ipynb` deploys the Copilot beside it, so please match the names that notebook uses. Read these notebooks without running them. Where a notebook and this document differ, follow this document. Include this sidenote in your plan too.

## Where we're heading

The UnderCover Agent works our queue on AgentCore Runtime, and our handlers spend their day on the dashboard: starting dispatches, reading what the agent did on a claim, signing off large payouts, sending decisions back and checking the scoreboard. Each of those takes a few pages and a few clicks. Some questions take longer than that: what needs me today, why did the agent decide this, what does the wording say, and how are we doing against what we agreed at the start of the pilot.

We'd like our handlers to ask in plain English and get the answer, with the work done for them when they ask for it. The UnderCover Copilot is an agent for our handlers, in a sidebar on every page of the dashboard. It looks things up in our records and the context layer, starts the agent's work, sends decisions back and signs them off. It does all of this as the handler who asked, with their permissions, and it shows each step as it takes it.

This document says what the Copilot does and how it should feel to use. The design is yours, apart from our IT team's choices and the names in Deployment, which our deployment depends on.

## What we want

### 1. A copilot on every page

- A sidebar on the right of every signed-in page, open the first time a handler signs in. They can collapse it to a slim tab with an icon of its own and open it again, and the dashboard remembers their choice in that browser.
- The page beside the sidebar stays fully usable, and it shows the changes the Copilot makes as it shows any other change. On a narrow window the sidebar opens over the page instead of beside it. The existing end-to-end tests pass with the sidebar open.

### 2. It acts as the handler who asked

- The Copilot works with the handler's own sign-in. Every call it makes to our app carries that sign-in, so it can see and do exactly what the handler can on the dashboard, and our records name the handler, as if they had pressed the button themselves.
- It knows who it's working for and what they may do. A handler who can't sign off over the limit can't sign off through the Copilot either, and the Copilot tells them so rather than trying. Our app still checks every action.
- Each turn, and each answer to a confirmation, starts by asking our app who is signed in. If our app doesn't accept the sign-in, it ends there, before any call to the model.
- It never sends the agent's API key, which would let it record a decision or pay a claim as the agent. Our app treats any request that carries the key as the agent's, whatever else it carries.
- The sign-in goes from the dashboard to our app to the Copilot with each message and each answer to a confirmation. It is never saved: not in the conversation's saved state, its steps, the memory or any log. Supabase's sign-ins last an hour, so before sending either, the dashboard renews the handler's sign-in when it has less than 20 minutes left.
- A conversation belongs to the handler who started it. Nobody else can see it or carry it on.

### 3. What it can look up

- Claims: the queue with where each claim stands, a claim in full with its decision, its payout and any decision sent back with its note, and the agent's steps on a claim.
- Policies, and customers by name or by id: who they are, their policies, their earlier claims and their claims in our queue. Finding a customer by name is new to our app.
- The latest dispatch with its summary, and the evaluations with their measures. Like the claim agent, the Copilot never sees our handlers' decisions on the labeled sets.
- Our settings: the approval limit and our objectives.
- The context layer's seven lookups, the same ones the claim agent has, on the same route the claim agent takes: through our AgentCore Gateway when it's set up, or straight to the context layer when it isn't. On the Gateway the Copilot uses only the context layer's tools, since the app's tools there act as the agent.

Our app already has most of these reads for the dashboard. Add what's missing, following the API rules in `docs/TECH_STACK.md`.

### 4. What it can do

- Start a dispatch with the number of claim agents the handler asks for, or the number in our settings when they don't say.
- Start an evaluation on either of our labeled sets, whole or its five tiny claims, with the number of claim agents in our settings unless the handler says otherwise.
- Send a held decision back to the agent with a note.
- Sign off a held payout, which pays it, once the handler has confirmed (item 5).

For anything else the dashboard can do, such as changing a setting or starting an improvement round, the Copilot says it can't do that yet and where on the dashboard to do it.

### 5. It asks before it pays

- Before the Copilot signs off a claim, the conversation pauses and the sidebar shows a confirmation card: the claim, the customer, the amount it will pay and the agent's reason, with two buttons, Sign off and pay, and Cancel. Nothing is paid until the handler presses Sign off and pay.
- The Copilot checks in code that the handler may sign off that claim before it pauses, so the card never shows for a handler who can't. The card's claim, customer, amount and reason are read from our records, never taken from what the model wrote.
- The pause is saved, so the handler can answer it later, after a reload or on another day, and the Copilot carries on from where it stopped. Nothing it did before the pause is done again when the handler answers. After Cancel, the Copilot says it hasn't signed off and asks what they'd like instead.
- While a confirmation waits, the message box asks the handler to answer it first.
- Only the sign-off pauses. Everything else happens when the handler asks for it.

### 6. Waiting for the agent's work

- When a handler starts a dispatch or an evaluation and wants to know how it went, as in "work the queue and tell me what needs me", the Copilot waits for the work to finish before it answers. Starting a dispatch or an evaluation tells the Copilot which one it started, and it waits on that one through a read a handler may use. It waits in code, checking our app every few seconds, never by calling the model again and again. After 15 minutes it stops waiting and says the work is still going and where to follow it.
- While it waits, the dashboard behind the sidebar shows the claims moving as usual.
- If our app refuses to start the work, because a dispatch is already running for example, the Copilot passes on the reason.
- After a dispatch, what needs a handler is the payouts held for sign-off, the claims referred or left for a handler, and any claim sent back that the agent hasn't worked yet.

### 7. The sidebar shows its work as it goes

The sidebar should look polished.

- The handler's messages sit on the right and the Copilot's answers on the left, as in any chat. Answers are written in markdown and shown formatted, with short paragraphs, lists and small tables. Claim ids link to the claim's page.
- Each step appears as it happens, not at the end of the turn. Each tool the Copilot calls is a compact card with an icon for its kind (claims, customers and policies, the context layer, the agent's work, memory, or an action that changes something), the tool's name and its main input, such as `get_claim CLM-1012`, and its state: working, with a spinner and the seconds so far; done, with the time it took; or refused or failed, with the reason. Cards arrive with a short, subtle animation.
- Clicking a card opens it to show what was asked and what came back, trimmed to a readable length, with the file and owner of a context-layer answer. Cards for actions that change something (a dispatch, an evaluation, a send back or a sign-off) stand out from the lookups.
- While the Copilot works between steps, a small working indicator shows below the last step.
- The answer appears in full once the turn is done, with a line in small print giving the turn's model calls, their cost and the time it took.
- An empty conversation greets the handler by first name and offers a few suggested questions to click.
- At the top of the sidebar: New conversation, and the handler's earlier conversations, newest first, each titled with its first question. At the foot: the message box, "Ask the Copilot", where Enter sends and Shift+Enter starts a new line, disabled while the Copilot works on a turn, and "Signed in as" with the handler's name.
- Light and dark modes, fonts, colors and icons follow `docs/BRAND.md`.
- The sidebar checks for new steps about once a second while the Copilot works on a turn, and not while the conversation is idle. Answers aren't streamed word by word: our app on Lambda can't stream, and the cards already show the Copilot's progress.

### 8. Conversations are kept

- Each conversation's state is saved after every step in our Supabase database, so a handler can pick up any earlier conversation and the Copilot still has all of it, after a restart on the laptop and across Runtime sessions.
- The steps the sidebar shows are kept in our app with their conversation, as the claim agent's steps are kept with their claim.
- Our app knows where each turn stands: working, waiting for a confirmation, done or failed. It keeps a waiting confirmation with its conversation until the handler answers it, so the card is still there after a reload.
- One turn at a time in a conversation: our app refuses a second message while the Copilot is still working on one. A turn that fails ends with a short message in the sidebar saying what went wrong. A turn still working 20 minutes after it started, or after the handler answered its confirmation, is shown as stopped. In both cases the handler can carry on with a new message, even when the turn stopped partway through a step. A turn waiting for a confirmation isn't working, so it's never shown as stopped.

### 9. It remembers each handler

- The Copilot has a memory of its own in AgentCore Memory, apart from the claim agent's memory of customers, with a namespace for each handler. It remembers each handler's preferences, such as how they like answers set out, and facts they tell it, such as the claims they're keeping an eye on.
- The handler is whoever the sign-in says: the Copilot asks our app who is signed in and uses that handler's id, never a name from the model or the message. One handler's memories are never used for another.
- At the start of each turn the Copilot looks up what it remembers about the handler that bears on their message, and uses it. The lookup shows in the sidebar as a card like any other, with what it found.
- After each turn it saves the handler's message and its answer to the handler's memory, and nothing else: no tool calls, no tool results and never the sign-in. AgentCore Memory turns them into notes in about a minute and a half, so a preference shows in the handler's next conversation rather than the same turn.
- The memory is on only when its setting is there (Deployment), and the Copilot works the same without it.

### 10. The success criteria we agreed

When we started the pilot we agreed three success criteria. The Copilot knows them and checks them when asked:

1. **Straight through:** at least 70% of claims handled straight through on the whole held-out set, measured by the straight-through share our evaluations already record.
2. **Accuracy:** at least as accurate as we agreed, with the accuracy our evaluations already record on the whole held-out set at or above our accuracy objective in Settings.
3. **Over the limit:** every payout over the approval limit approved by a person. Every claim in our queue paid more than the approval limit has a handler's sign-off on its payment. When none has been paid over the limit yet, this one is met, and the answer says why.

To answer "Are we meeting the success criteria we agreed?", the Copilot starts an evaluation of the whole held-out set, not its five tiny claims, with the claim agents in our settings. It waits for the evaluation as in item 6, then answers with a small table giving each criterion, its target, its figure and whether it's met, and one line on whether all three are.

- **Every figure in that answer comes from our records, worked out in code, never by the model.** The first two come from that evaluation's own measures, and the accuracy target from Settings. For the third, our app counts the claims in our queue paid over the approval limit and how many of those carry a handler's sign-off, and gives the Copilot both numbers in one read. The model writes the answer around these figures.
- If the evaluation fails, stops partway, or is still going after 15 minutes, the Copilot says so and gives no figures for the first two criteria. If our app refuses to start it, the Copilot passes on the reason. In either case it still reports the third.
- Add the three criteria to `docs/SPEC.md`.

## The handover conversation

At our handover meeting, our head of claims will have this conversation with the Copilot on the deployed dashboard, signed in as Dana Whitfield, in one conversation, after a reseed:

1. "Work the queue with 10 agents and tell me what needs me."
2. "Why does CLM-... need me?", about one of the payouts held for sign-off.
3. "Send it back with a note", asking the agent to look again at something in that claim.
4. "Sign off on another one", meaning one of the other payouts held for sign-off. The Copilot picks one, shows the confirmation card for it, and pays once she confirms.
5. "Are we meeting the success criteria we agreed?"

Each question gets its answer in one turn, with every figure taken from our records or the context layer. Afterwards she tells the Copilot how she likes her answers, starts a new conversation a few minutes later, and sees it remember.

## Our IT team's choices

- **The agent loop** is a LangGraph graph written by hand: a node that calls the model, a node that runs the tools, and the loop between them, with the pause before a sign-off as a LangGraph interrupt. A turn makes at most 25 model calls.
- **The model** is GPT-6 Luna (`openai/gpt-6-luna`) through OpenRouter with low reasoning effort, or the model in `MODEL_NAME` when it's set. Our app names the Copilot's model, as it names the security check's.
- **The Copilot's instructions** give it its goal, who it works for, what it can see and do, the success criteria and how to answer: briefly, in plain business English and US dollars, with every figure from a tool. They don't script its steps.
- **The Copilot is an AgentCore app of its own,** built the same way as the claim agent's: one entrypoint, each payload naming its operation, nothing happening at import, getting ready on its first request (fetching its credentials from AgentCore Identity on Runtime), and answering at once while the turn goes on as an async task, so its Runtime session lasts as long as the turn. It answers a health check, `{"operation": "health"}`, with `{"healthy": true}`. On Runtime it serves on port 8080, like the claim agent. On the laptop it listens only on 127.0.0.1:8081 and asks for no key, since everything it does carries the handler's sign-in, which our app checks on every call.
- **A Runtime session for each conversation.** Our app starts each turn, and each answer to a confirmation, with the conversation's id as the Runtime session id, then replies to the dashboard at once. A conversation's id works as a Runtime session id and as the Memory's session: at least 33 characters, and at most 100 letters, digits and hyphens. A turn soon after the last one goes to the same session, and a later one starts a new session from the saved state.
- **Steps go through our app.** The Copilot records each step with our app as it takes it, and the sidebar reads them from our app. It also tells our app when a turn ends, with its answer, its model calls and their cost; when it pauses, with what the confirmation card shows; and when it fails, with why.
- **Reuse what we have.** The Copilot's code lives in the `agent` package beside the claim agent's, since our platform team's project packages only `runtime/` and `agent/`, and Runtime starts it from a file of its own in `runtime/`. It reaches our app through the same connection as the claim agent, with the handler's sign-in in place of the key. Both runtimes can read the project's three credentials, but the Copilot fetches only `OPENROUTER_API_KEY` and `DATABASE_URL`. For OpenRouter, the Gateway, the context layer, AgentCore Identity, AgentCore Memory and its checkpoints in Supabase, it uses the claim agent's code where it fits. Add the Copilot as a part of its own to `docs/CODE_STANDARDS.md`, with the same rules as the other parts.

## Deployment

`docs/TECH_STACK.md`'s Deployment section gets the Copilot:

- Our platform team has agreed that the Copilot joins their AgentCore project in `agentcore/` as a second runtime, `copilot`, beside `agent`. One `agentcore deploy` deploys both, on Runtime's platform version V2, from one package built the way the claim agent's is. Make only the changes to `agentcore/` and `runtime/` that this needs, and keep the rest as the platform team wrote it.
- The Copilot's settings on Runtime: `OPENROUTER_API_KEY` and `DATABASE_URL` (Supabase's transaction pooler, port 6543) from AgentCore Identity, which the project already holds; `UNDERCOVER_API`, `UNDERCOVER_GATEWAY_URL` and `UNDERCOVER_COPILOT_MEMORY_ID` from `agentcore/.env.local` when `agentcore deploy` runs. On Runtime its context layer tools always go through the Gateway. Its runtime's role may call the Gateway and use the Copilot's Memory.
- The Copilot's Memory is created by our deployment notebook, not by the code: `undercover_copilot_memory`, with a User Preference strategy on `/handlers/{actorId}/preferences/` and a Semantic strategy on `/handlers/{actorId}/facts/`. The actor is the handler's id and the session is the conversation.
- On the laptop, `npm run dev` also serves the Copilot's AgentCore app on 127.0.0.1:8081 with reload, and our app reaches it at `UNDERCOVER_COPILOT`, `http://127.0.0.1:8081` by default. With `UNDERCOVER_COPILOT_RUNTIME` set to the ARN of the Copilot's runtime, our app sends each turn there instead, and its role may invoke that runtime.

## What stays the same

- The rules in `docs/SPEC.md`: the approval limit, the sign-off that pays, the Gateway's Policy and the security check.
- The API rules in `docs/TECH_STACK.md`. Every route the Copilot calls takes the handler's sign-in, as the dashboard's routes do, and the claim agent's API document for the Gateway keeps its six operations.
- The claim agent, the dispatcher and the improver.
- Tests never call a model, AWS, Supabase Auth or the Gateway, `npm run check` never reads `.env`, and the code follows `docs/CODE_STANDARDS.md`.
- `npm run seed` rebuilds everything, the Copilot's conversations included.
- Everything `npm run dev` starts, `npm run build` and `npm run check` work on Windows too.
- Nothing in this change creates anything on AWS. Our deployment notebook does that.

## How we'll know it's done

- `npm run check` is green with `.env` moved out of the way. Tests with a stub model and stand-ins cover the loop, the pause answered by a freshly built Copilot on the same saved state, the sign-in passed through and never saved, a refusal passed on, the wait for a dispatch, the success criteria answered from an evaluation's measures, Settings and our app's count of payouts over the limit (with none paid yet, and with an evaluation that failed), the memory lookup and saves, one turn at a time, a failed turn and a message after it, a stopped turn, a Cancel, the agent's key never sent, and another handler refused a conversation. End-to-end tests drive the sidebar against a stand-in Copilot, which plays a scripted turn through our app with the handler's sign-in: a lookup, an action, a refusal, a confirmation and a formatted answer.
- The Copilot's AgentCore app answers its health check through the file Runtime starts, with only the `runtime` dependency group installed.
- After one `npm run seed`, with `npm run dev` running on the default model, on the direct route and with memory off: the five questions of the handover conversation, signed in as Dana Whitfield, with every figure in the last answer checked against the Scoreboard and the claims' pages, then the same conversation picked up after restarting `npm run dev`. Our deployment notebook checks the memory on the deployed product. Signed in as Marcus Oyelaran, a request to sign off is declined with the reason. Check the sidebar in light and dark mode through the Playwright MCP server, and report what the runs spent.
- `docs/SPEC.md`, `docs/TECH_STACK.md`, `docs/CODE_STANDARDS.md`, `docs/PROCESS.md` and `docs/STATUS.md` describe the product as it now is.

## Not for now

- Streaming answers word by word.
- Stopping a turn partway.
- The Copilot reading the claim agent's memory of customers.
- Sharing, renaming or deleting conversations.
- Changing settings, the configuration or improvement rounds through the Copilot.
- Langfuse tracing for the Copilot.

## What our team learned

- Runtime keeps a session's id after the session stops: the next call with that id starts a new session under it.
- While Runtime is starting or stopping a session, a call to it gets a conflict that is safe to retry, since the call hasn't reached the agent. Our app retries it a few times over a few seconds.
- On V2, every session starts from one snapshot taken after import, which is why nothing may happen at import.
- The Gateway names each tool after its target, as in `undercover-context___lookup_term`. A card shows the tool's own name.

## Planning

Follow `docs/PROCESS.md`, but write this plan to `docs/PLAN_COPILOT.md` and tick it off there. Plan five or six phases and commit at the end of each. Do the live checks last, after reseeding once.
