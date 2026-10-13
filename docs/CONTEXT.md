# The context layer, memory and the Gateway for the claim agent

From our IT team, with claims operations and data governance.

SIDENOTE: For consistency with the course, please read `labs/week3day3.ipynb`, which deploys the app and the context layer, creates the Gateway and the memory, and runs the agent against them, without running it. Where the notebook and this document differ, follow this document. Include this sidenote in your plan too.

## Where we're heading

The app runs on AWS Lambda, and an AgentCore Gateway with a Policy sits in front of the claim agent's operations. The claim agent itself still calls the app directly, so the Policy only covers calls that happen to go through the Gateway. This change moves the claim agent onto the Gateway's tools, puts the business's definitions and rules behind the same Gateway as a context layer of their own, makes every decision record complete, and gives the agent a memory of each customer. The agent stays on the laptop until we deploy it.

The agent works from three sources of data, each with a different owner:

- **The context layer** is the business's data from other systems: what the data means, how the work is done and where each file came from. Data governance owns it, and the agent only reads it, through the Gateway.
- **Memory** is the agent's own notes on each customer, kept in AgentCore Memory. The agent reads and writes it directly, outside the Gateway, limited by its AWS credentials.
- **The database** is the system of record: claims, policies, customers, decisions and payments, with the agent's saved progress beside them. The agent reaches the records only through the app.

Each step below says what has to be true when it's finished and how we'll check it. The requirements describe what the product does rather than how its code is organized, and the notes at the end say where things are in our last build.

## What we found

- The claim agent's tools call the app directly, so the Gateway's Policy, which refuses any payment over $1,000, never sees what the agent does.
- What the agent needs to know is spread across systems. The plans sit in the app's payout rules, the claim rules in company settings, the defined terms inside the wording, and the outside facts claims turn on, such as named storms, strikes and product prices, are nowhere the agent can reach. Data governance has gathered them into `context/`: seven files, each naming the system it comes from, its owner and when it was last reviewed. Treat these files as theirs and don't change their content.
- Our decision records fall short of claims manual section 14. They have no calculation, they don't say who or what made the decision, and they don't carry the manual's version, which section 13 asks for.
- The agent forgets each customer between claims. Oliver Grant (CUS-3005) has two claims in the queue, CLM-1005 and CLM-1006, and his second opens "Yes, it is me again", but nothing tells the agent what happened the first time.
- A handler can see the sections the agent read, but not the other things it looked up, and nothing on a claim says where the information came from.

## Step 1: Tools from the Gateway

This step sets up the app's tools on both routes, and step 2 adds the context layer's through the same two routes.

1. When `UNDERCOVER_GATEWAY_URL` is set, the claim agent calls its tools as the Gateway's MCP tools, over streamable HTTP, signing every request with AWS Signature Version 4 for the `bedrock-agentcore` service, with the credentials and region the AWS CLI uses. The Gateway names each tool `<target>___<operation>`, and the targets are `undercover-app` for the app and `undercover-context` for the context layer (step 2).
2. When it isn't set, the agent calls the app directly with its API key, as it does today, and the context layer at `UNDERCOVER_CONTEXT`, or `http://127.0.0.1:8006/mcp` when that isn't set, over MCP without signing.
3. Both routes give the model the same tools with the same names and inputs. The agent's own tools stay as thin layers over the Gateway's, and fill in what the agent already knows: the claim's id, its policy and its customer. The model can then act only on its own claim and read only its own customer's data (claims manual section 11), so `get_claim`, `get_policy`, `get_claim_history` and `calculate_payout` take no id from the model. Recording a decision still ends the agent's work through the graph's state.
4. The model's tools and the payment go through the Gateway, so the Policy covers both. Everything else goes straight to the app with the key, as it does today: the agent's bookkeeping (starting a claim, its steps, model calls, work times and failures), the security check's read of the claim and its referral, the runs, the versions and the improver. These aren't the model's tools, and the agent's API document leaves them out.
5. `get_claim` gives the model the same text on both routes, which is also what the security check reads.
6. On both routes, when the app or the context layer refuses a tool call the model sees a refusal with its reason, as it does today, never an answer that looks like a success.
7. When the Gateway refuses a tool call, which the MCP client raises as an error rather than returning as a result, the refusal is recorded on the claim as the Gateway's and the model gets it as a refusal, so the claim's work goes on.
8. When the Gateway refuses the payment, which the graph makes rather than the model, the refusal is recorded on the claim and the claim waits for a handler's sign-off, as an approval over the limit does, so a handler can still pay it. The app gets an operation for this that only the agent's key can call, and that only moves an approved, unpaid claim in progress to waiting for sign-off. It's bookkeeping, so it stays off the Gateway. This happens only when the approval limit setting has been raised above the Gateway's Policy, and the sign-off panel then says that the Gateway refused the payment, rather than that the payout is over the approval limit.
9. The agent reads `UNDERCOVER_GATEWAY_URL`, `UNDERCOVER_CONTEXT` and `UNDERCOVER_MEMORY_ID` when it builds a claim graph rather than when it's imported, so the command line, which loads `.env` after its imports, sees them.
10. The agent stays synchronous, and works on Windows.

Done when:

- Tests cover both routes with stand-ins: the model's tools and the payment through a stand-in Gateway that names its tools as the Gateway does, the same tools on the direct route, a refusal by the app on each route, a refusal by the Gateway recorded on the claim for a tool, and a payment the Gateway refused that leaves the claim waiting for sign-off, which a handler's sign-off then pays.
- With `npm run dev` running and no `UNDERCOVER_GATEWAY_URL`, `uv run -m agent CLM-1001` decides the claim as before.

## Step 2: The context layer

The context layer is its own service, an MCP server that serves the files in `context/`. It runs on Lambda behind the Gateway as the `undercover-context` target, and on the laptop for development.

The files:

| File | What it holds | Where it comes from |
|---|---|---|
| `data_dictionary.yaml` | The meaning of each field the agent sees in a claim, a policy and a previous claim | The data catalog |
| `glossary.yaml` | The terms the policy wording defines | The policy wording |
| `plans.yaml` | Each plan's limits, waiting periods and deductible, and the add-ons | Policy administration |
| `claim_rules.yaml` | The filing window, the pre-existing look-back, repeat claims and meals without receipts | Claims operations |
| `reference_data.yaml` | Outside events, places and products | Outside data providers |
| `policy_wording.md` | The contract with the customer, by section | Legal |
| `claims_manual.md` | How handlers work a claim, by section | Claims operations |

The server:

1. It serves MCP over streamable HTTP at `/mcp`, stateless, with JSON responses, and every tool is read-only. Each tool has a one-line docstring as its description and no optional inputs.
2. Its tools:
   - `lookup_term(term)`: a term's definition and the sections of the wording it comes from, matching the term whatever its case. An unknown term gets the list of terms the glossary defines.
   - `describe_fields(record)`: the data dictionary's fields for a `claim`, a `policy` or a `previous_claim`.
   - `get_plan(plan)`: one plan's limits, waiting periods and deductible, the benefits the deductible applies to, and the add-ons, for `economy`, `premium` or `first`.
   - `get_claim_rules()`: the claim rules.
   - `search_reference_data(query)`: the facts that contain every word of the query, whatever its case, each with its topic.
   - `search_documents(query)` and `read_section(document, number)`: as the app's operations of the same names do today, with the same inputs.
3. Every answer also names the file it came from with that file's source: its system, owner and review date. A search of the documents names the file of each section it finds.
4. The files are read and the documents prepared once, when the process starts, never for each request: each document is split at its numbered headings into sections, and each section is tagged with its document, its number and its title. A document's front matter is its source and version, never part of a section.
5. On the laptop, `uv run -m context` serves it at `http://127.0.0.1:8006/mcp`, and `npm run dev` starts it beside the backend, the agent's service and the dashboard.
6. On Lambda, it runs behind a Function URL with AWS IAM auth, so only callers allowed to invoke it can reach it, the Gateway among them. It reads files only from its own package, writes none, and needs no environment variables.
7. `pyproject.toml` gets a `context` dependency group with exactly what the server needs on Lambda, and `npm run check` checks that the server imports with only that group installed, in a temporary environment of its own, as it already does for the `server` group.

The app:

8. Seeding loads the plans into the app's payout rules from `context/plans.yaml`, and the two documents into the documents table from `context/policy_wording.md` and `context/claims_manual.md`, keeping each document's version from its front matter. The product no longer reads `data/plans.json`, `data/policy_wording.md` or `data/claims_manual.md`, which stay in `data/` as they are. The approval limit still comes from `data/company.json` and stays a setting. Reading YAML adds `pyyaml` to the project's dependencies, and to the `server` group too if the backend imports it, so the app's package and its import check keep working.
9. The app's `search_documents` and `read_section` operations go, since the agent now reads the documents in the context layer. The claim agent's API document then has six operations: `get_claim`, `get_policy`, `get_claim_history`, `calculate_payout`, `record_decision` and `pay_claim`.
10. The claim agent's instructions still end with the contents of both documents, from the documents table.

Done when:

- Tests call each tool against the real files in `context/`, including an unknown term and a section that doesn't exist.
- A test calls the Lambda handler with Function URL events, with a Function URL's host, twice in one process, listing the tools and then calling one, and both succeed.
- The context group check passes in `npm run check`.
- The tests for the agent's API document expect the six operations.
- With `npm run dev` running, the claim agent's tools from the context layer answer on the direct route.

## Step 3: A complete decision record

Claims manual section 14: "Every decision record holds the decision, the payout, the calculation, the section relied on, a reason in plain language, who or what made the decision and when. For a payout above $1,000 it also holds who signed off and when. A decision with no reason on file is treated as not yet made."

1. The app keeps the latest payout calculation from `calculate_payout` for each claim's current attempt.
2. `record_decision` takes who made the decision (`decided_by`), besides the decision, the payout, the section and the reason. The agent fills it in, as it fills in the claim's id, so the model never sees it: the UnderCover Agent with the version of the configuration it's working on, or the security check for the check's referrals, which sit outside the versions.
3. `record_decision` refuses a record that falls short of section 14 with a 422 that names section 14 and says what is missing, so the agent can put it right and try again. The request's own checks stay as they are and now name section 14 too: a reason, a section or a maker that is blank, an approval that pays nothing, and a decline or a referral that pays something. They come before the app looks at the claim, so they get the same answer on any claim. The new check is the calculation: an approval needs a calculation on file for this attempt, and a payout equal to it.
4. The record then holds the calculation (the calculation's lines and its payout, as `calculate_payout` gave them for an approval, and none for a decline or a referral), who made the decision, when, and the claims manual's version in force (section 13), with the new fields named as `context/data_dictionary.yaml` names them. A handler's sign-off still adds who signed off and when.
5. Many existing tests and the end-to-end tests record approvals directly, with payouts of their own. Give each test suite one shared helper that records a matching calculation first and sends the maker, rather than changing each test or its expected payouts. A recipe that works on any claim: one `expense` line under `emergency_medical` for the payout plus the plan's deductible, where a first calculation of the payout alone shows the deductible. Backend tests may write the calculation directly instead.

Done when:

- Tests cover each refusal, a complete approval with its calculation, a decline, a referral by the security check, and the maker and the manual's version on the record.
- After one `npm run seed`, `uv run -m agent CLM-1001` records a complete decision.

## Step 4: Memory of each customer

1. When `UNDERCOVER_MEMORY_ID` is set, the claim graph uses that AgentCore Memory as its store, through `AgentCoreMemoryStore` from `langgraph-checkpoint-aws`, which joins the project's dependencies, in the AWS CLI's region. The checkpoints stay in Supabase. The memory is part of our claims platform, in our own AWS account, and each customer's memories are used only for that customer's claims (claims manual section 11).
2. When the claim agent's work on a claim ends with a decision it recorded, the graph saves two events to memory, with the claim's customer as the actor and the claim as the session: the claim (its summary, the benefit claimed, the date and place of the incident and the items claimed) as the customer's message, and the decision with its payout, section and reason as the agent's. The story and the documents stay on the claim: a story is where a customer's text could try to instruct us, and the documents hold whole medical records. This happens in code every time, never at the model's choice.
3. Nothing is saved for a claim the security check referred, since its text tried to instruct us and memory would carry it into the customer's later claims, and nothing is saved for an evaluation's copy of a claim.
4. AgentCore turns the events into memories in the background, with the two strategies the deployment gives the memory: Semantic, which keeps facts about the customer under `/customers/{actorId}/facts/`, and Summary, which keeps a summary of each claim under `/customers/{actorId}/claims/{sessionId}/`.
5. The model gets a `search_memory(query)` tool, described as searching what we remember about this claim's customer from their earlier claims. It searches only under `/customers/<this claim's customer>`, so one customer's memories never reach another's claim, and it returns each memory's text, leaving out the summary of the claim it's working on, which a claim worked again would otherwise find. The tool is there only when memory is on and the run isn't an evaluation, so evaluations and their scores don't depend on memory; the kind of run decides it when its claim graphs are built.
6. Memory adds what happened on a customer's earlier claims. The claim history in our records is still what counts for repeat claims (claims manual section 9).
7. The claim agent's instructions, in `backend/instructions/claim.md`, name what the agent now has to go on: the context layer's definitions, plans, rules, reference data and documents, and its memory of the customer. They stay written as goals, like the rest.
8. When AgentCore can't be reached, saving logs a warning and the claim keeps its decision, and a search gives the model the error as a refusal.

Done when:

- Tests with a stand-in store cover the two events saved after a decision, nothing saved for a claim the check referred or for an evaluation's copy, a search kept to the claim's customer, and no memory tool when memory is off.
- With `npm run dev` running and no `UNDERCOVER_MEMORY_ID`, the agent works as before with no memory tool.

## Step 5: Every step on the claim page

The claim page is where our handlers, and anyone checking the agent's work, see what happened on a claim. Each kind of step below is a kind of its own in the app, in `agent/api.py` and in `dashboard/src/api.ts`: a lookup (which takes the place of `reading`), a memory search or save, and a refusal. A lookup's step holds what was looked up and its file with the file's system, owner and review date, in a shape the dashboard can group by file. The page shows each step of the agent's work as it happens:

1. Each tool call, named as the Gateway names it (`undercover-context___lookup_term`) when the agent is on the Gateway, and by its own name otherwise. The model's reply names its own tools, so the agent maps them to the Gateway's names on that route.
2. Each lookup in the context layer, saying what was looked up and where it came from: a term, a plan, the claim rules, a record's fields, a search of the reference data or of the documents, or a section read.
3. Each search of memory with what it found, and each save to memory with what was saved.
4. Refusals, standing out from the other steps: the section 14 check's refusal and the agent's next attempt at the record, and anything the Gateway refused, labeled as the Gateway's.
5. A Context used panel, in place of Sections read, lists everything the agent looked up in the context layer once each, grouped by file, with each file's source.
6. The decision panel shows the whole record from step 3, with the calculation line by line.

The page follows `docs/BRAND.md`, and its words follow the dashboard's plain style.

Done when:

- Tests cover each kind of step, the Context used panel and the decision panel with a calculation.
- After the live runs below, which use the direct route with memory off, Dana Whitfield sees on CLM-1005's and CLM-1006's pages the tool calls, the lookups with where each came from, the Context used panel and the decision with its calculation, checked through the Playwright MCP server. The memory steps, the Gateway's names and refusals are covered by the tests.

## Deployment

`docs/TECH_STACK.md`'s Deployment section gets the context layer and the agent's settings:

- The context layer's package is `context/` without its tests, with the `context` group's packages installed for Linux and Python 3.12. Its Lambda handler is `context.server.handler`, behind a Function URL with `AWS_IAM` auth, with no environment variables.
- The app's package and environment are as before. The app reads `context/` only while seeding, never when it's imported or for a request, so its package needs no `context/`; the manual's version for a decision comes from the documents table.
- The agent's settings: `UNDERCOVER_GATEWAY_URL` (the Gateway, when set), `UNDERCOVER_CONTEXT` (the context layer on the direct route), `UNDERCOVER_MEMORY_ID` (the memory, when set), and the AWS credentials and region from the AWS CLI's configuration whenever `UNDERCOVER_GATEWAY_URL` or `UNDERCOVER_MEMORY_ID` is set.

## What stays the same

- The rules in `docs/SPEC.md`, with the changes above. Update SPEC.md for the context layer, the memory and the complete record.
- The check for hidden instructions, the approval limit as a setting, the sign-off that pays, and the screening model.
- The API rules in `docs/TECH_STACK.md`: every operation has an `operation_id`, a one-line docstring and no optional inputs. The context layer's tools follow the same rules.
- Langfuse tracing as it is. Nothing in this change depends on it, and the agent works the same without the Langfuse keys.
- The agent's service stays on the laptop, where only the backend calls it.
- Tests never call a model, AWS, Supabase Auth or the Gateway, `npm run check` never reads `.env`, and the code follows `docs/CODE_STANDARDS.md`. Update its rules on how the agent reaches the backend for the Gateway and the context layer, with one module for each route.
- The improver, apart from the sentence in `backend/instructions/improver.md` that lists the claim agent's tools, which should name the new ones.
- The rule that an approval pays more than zero.
- `npm run seed` rebuilds everything, as it does today.
- Everything `npm run dev` starts, `npm run build` and `npm run check` work on Windows too (`docs/PROCESS.md`).
- Nothing in this change creates anything on AWS. The deployment does that.

## What done looks like

- `npm run check` is green with `.env` moved out of the way, with the tests from each step.
- After one `npm run seed`, with `npm run dev` running on the default model, on the direct route and with memory off: `uv run -m agent CLM-1005`, then `uv run -m agent CLM-1006`, then a dispatch at N=25 that works the rest of the queue as before, and an evaluation of the evaluation set's five tiny claims. Check the claim pages through the Playwright MCP server, and report what the runs spent.
- `docs/SPEC.md`, `docs/TECH_STACK.md`, `docs/PROCESS.md`, `docs/CODE_STANDARDS.md`, `docs/STATUS.md` and `data/README.md` describe the product as it now is.

## Not for now

- Memory in evaluations.
- Masking personal fields for the agent, and requesting documents from customers.

## Notes from our last build

These notes come from our own build of the security changes, on the `week3day2-end` branch, and from our team's experiments with the Gateway and AgentCore Memory. If your build took a different path, a note may not match your code: follow its intent where it applies and skip it where it doesn't.

- **What our deployment expects:** it packs `context/` with the `context` group's Linux packages and gives Lambda the handler `context.server.handler`. The Gateway's targets are named `undercover-app` and `undercover-context`, with a Cedar permit for each target's tools beside the forbid on payments over $1,000. It creates the memory with a Semantic strategy on `/customers/{actorId}/facts/` and a Summary strategy on `/customers/{actorId}/claims/{sessionId}/`, writes `UNDERCOVER_GATEWAY_URL` and `UNDERCOVER_MEMORY_ID` into `.env`, and runs the agent with `uv run -m agent <claim>`, with `UNDERCOVER_API` set to the app on Lambda.
- **The agent's tools** are in `agent/tools.py`, on `agent/api.py` and the one client in `agent/connection.py`. `ClaimContext` holds the claim's id and run, and the tools read it through `ToolRuntime`; it's where the policy, the customer and the version go too. `read_section` gives its reading as the tool's artifact, and `record_result` in `agent/harness.py` records it as a step.
- **The claim graph** is in `agent/harness.py`: `screen`, `refer`, the model, a `ToolNode` with `handle_tool_errors=refusal` and `wrap_tool_call=record_result`, and `pay`. `claim_graphs` builds a graph for each claim run on the service's pool, and `begin` gives the first message. A save to memory after the decision fits as a node of its own, so it runs once even when work carries on after a restart.
- **The MCP client:** our deployment notebook from the security changes, `labs/week3day2_lab2.ipynb`, reaches the Gateway with `MultiServerMCPClient` from `langchain-mcp-adapters` (0.3.2 in `uv.lock`) and a `SigV4Auth` class on `httpx.Auth`, signing for `bedrock-agentcore`. Its tools are async only. With the client's default `handle_tool_errors=True`, a tool the app refuses returns the app's answer as if it had succeeded; with `handle_tool_errors=False` it raises a `ToolException` whose message is the app's answer, which the graph's `refusal` already turns into a refusal for the model. A refusal by the Gateway's Policy raises `McpError` from `mcp.shared.exceptions`, with a message that starts "Tool Execution Denied". The Gateway is stateless, so a session for each call works, at about 0.75 seconds a call in our experiment.
- **Async calls from the synchronous agent:** `asyncio.run` on the main thread leaves it with no event loop afterwards on Python 3.12, and Mangum, which the app's and the context layer's Lambda tests call, asks for the main thread's loop; `conftest.py` already notes this trap. LangGraph runs a lone task on the caller's thread, so the bridge to the async tools mustn't take the main thread's loop away, for example by running each call on a loop of its own that it closes without touching the thread's.
- **The context layer on Lambda:** our experiment ran FastMCP from the `mcp` package (1.30 in `uv.lock`) with `stateless_http=True` and `json_response=True` under Mangum. Mangum runs the app's startup and shutdown around every request, and FastMCP's session manager can only run once, so a server reused across requests fails on its second request with a lifespan error. Reading the files once at import and building a fresh server in the handler for each request, `Mangum(build_server().streamable_http_app(), lifespan="auto")(event, context)`, works. FastMCP turns on DNS rebinding protection when its host is 127.0.0.1, which refuses the Function URL's host, so the server on Lambda passes `TransportSecuritySettings(enable_dns_rebinding_protection=False)`; the Function URL's IAM auth guards it there. On the laptop, uvicorn can run one server as usual.
- **AgentCore Memory:** `AgentCoreMemoryStore(memory_id=..., region_name=...)` from `langgraph-checkpoint-aws` (1.2.4 in our experiment; `memory_id` is keyword-only). `store.put((customer_id, claim_id), key, {"message": HumanMessage(...)})` writes one event, as the customer's message for a `HumanMessage` and the agent's for an `AIMessage`, and ignores the key. `store.search(("customers", customer_id), query=..., limit=5)` searches everything under `/customers/<id>`, the facts and every claim's summary, and each result's text is in `item.value["content"]`. In our experiment, memories appeared about 90 seconds after the events were written, and a search for another customer found nothing.
- **The documents** are split in `backend/documents.py` at headings matching `^## (\d+)\. (.+)$`, and `with_contents` in `backend/configuration.py` adds their contents to the instructions. Seeding is `seed` in `backend/database.py`, which reads `data/plans.json` and the two documents. The agent's API document is built in `backend/agent_api.py` from `OPERATIONS`.
- **The decision:** `record_decision` and `calculate_payout` are in `backend/main.py`, and the decisions table in `backend/database.py`. The request's checks are in `DecisionRequest` in `backend/models.py`: Pydantic's own messages for a blank field don't mention section 14, and FastAPI returns a validation error's `detail` as a list, so naming section 14 there takes messages of our own. Our last runs called `calculate_payout` once before every approval and recorded exactly its payout, so the check in step 3 mostly confirms good records; its refusals show when something goes wrong.
- **The claim page** is `dashboard/src/pages/ClaimPage.tsx`, with `StepList.tsx`, `SectionsRead.tsx` and `DecisionPanel.tsx` in `dashboard/src/components`, and the step kinds in `dashboard/src/api.ts`.
- **The checks:** `npm run check:server` in `package.json` is the model for the context group's check. Ruff, pyright, pytest and coverage are set up in `pyproject.toml` for `backend/` and `agent/`, so add `context/`. `npm run dev` runs its parts with `concurrently`.

## Planning

Follow `docs/PROCESS.md`, but write this plan to `docs/PLAN_CONTEXT.md` and tick it off there. Take the five steps in order, one phase each, and commit at the end of each phase. Do the live checks last, after reseeding once.
