# Plan: the context layer, memory and the Gateway for the claim agent

This plan makes the changes in `docs/CONTEXT.md`, one phase for each of its five steps, in order, then runs the live checks and brings the docs up to date in a sixth phase. Each phase leaves `npm run check` green and is committed before the next one starts.

SIDENOTE: For consistency with the course, please read `labs/week3day3.ipynb`, which deploys the app and the context layer, creates the Gateway and the memory, and runs the agent against them, without running it. Where the notebook and this document differ, follow this document. Include this sidenote in your plan too.

When it's done, the claim agent's tools and its payments go through the AgentCore Gateway whenever `UNDERCOVER_GATEWAY_URL` is set, signed with the AWS CLI's credentials, so the Gateway's Policy sees every call the model makes and every payment. Without it, the agent calls the app directly with its key, as today, and the context layer on the laptop. The context layer is an MCP server of its own that serves the seven files in `context/`: definitions, plans, rules, reference data and the two documents, with every answer naming the file it came from and that file's source. It runs on the laptop at `http://127.0.0.1:8006/mcp` and is ready for Lambda behind a Function URL. Seeding loads the plans and the documents from the same files, and the app no longer serves the documents. Every decision record meets claims manual section 14: it holds its calculation, who or what made it, when, and the manual's version. With `UNDERCOVER_MEMORY_ID` set, the agent saves each decided claim to AgentCore Memory and can search what it remembers about the customer on their later claims. The claim page shows every lookup and where it came from, every memory search and save, and every refusal, with a Context used panel and the whole decision record.

Phases 1 to 5 are checked with tests, local commands and a SQLite backend, and none of them uses the real model, AWS or Supabase. The live checks the brief lists under steps 1 to 5 all move to phase 6, which reseeds Supabase once and runs them in one go, on the default model, on the direct route with memory off.

## Design

### Three sources of data

| Source | Owner | What it holds | How the claim agent reaches it |
| --- | --- | --- | --- |
| The context layer | Data governance | The seven files in `context/` | Read only: through the Gateway's `undercover-context` target, or directly at `UNDERCOVER_CONTEXT` |
| Memory | The agent | Its notes on each customer | AgentCore Memory directly, with the AWS CLI's credentials, when `UNDERCOVER_MEMORY_ID` is set |
| The database | The app | Claims, policies, customers, decisions and payments, and the agent's saved progress beside them | The records only through the app; the checkpoints directly in Supabase, as today |

### Modules

The context layer, a new top-level package in `context/`, beside the seven files, whose content stays as it is:

- `context/files.py`: the seven files, read once when the process starts, and the lookups on them. It reads each YAML file with its `source`, and splits each document at its numbered headings (`^## (\d+)\. (.+)$`) into sections tagged with their document, number and title. A document's front matter (its source and version) is never part of a section. Each lookup returns its answer with `sources`, the files it came from. It reads only from its own folder and writes nothing.
- `context/server.py`: `build_server(security)` makes a FastMCP server with `stateless_http=True` and `json_response=True`, holding the seven tools. Each tool is a thin call into `files.py` with a one-line docstring, required inputs and `ToolAnnotations(readOnlyHint=True)`. `handler(event, context)` is the Lambda entry point: it builds a fresh server for each request, `Mangum(build_server(...).streamable_http_app(), lifespan="auto")(event, context)`, with `TransportSecuritySettings(enable_dns_rebinding_protection=False)`, since a Function URL's host would be refused and the Function URL's IAM auth guards it there. The files are read at import, never per request.
- `context/__main__.py`: `uv run -m context` serves one server at `http://127.0.0.1:8006/mcp` through FastMCP's own `run(transport="streamable-http")`, with FastMCP's protection for a local host left on.
- `context/tests/`: its tests, which the package leaves out.

The backend:

- `context_files.py` (new): reads the context layer's files for seeding: the plans from `context/plans.yaml` without its `source`, and each document's body and version from its front matter, with `yaml.safe_load`. Only `seed` calls it, so nothing reads `context/` on import or for a request, and the app's package needs no `context/`. It has its own small reader rather than importing `context.files`, since the two packages deploy apart.
- `database.py`: seeding takes the plans and the documents from `context_files.py`; `documents` gains `version`; `decisions` gains `calculation`, `decided_by`, `manual_version` and `gateway_refusal`; a new `calculations` table keeps each claim's latest calculation with the thread it was made on; `steps` gains `sources`; `claim_view` reads the new decision columns.
- `records.py` (new): what claims manual section 14 asks of a decision record: the request's checks, the calculation check and their messages, each written once.
- `main.py`: `search_documents` and `read_section` go; `calculate_payout` keeps its calculation for the claim's current attempt; `record_decision` takes `decided_by`, checks the record with `records.py` and stores all of it; `hold_payment` (new) holds a payment the Gateway refused for a handler's sign-off.
- `agent_api.py`: `OPERATIONS` holds the six operations.
- `documents.py`: loses `search`; keeps the sections and the contents the instructions end with, and gains the manual's version in force.
- `models.py`: the step kinds, `Source`, `Calculation`, the fuller `Decision`, `DecisionRequest` with `decided_by` and none of its own length or payout rules (`records.py` checks those and names section 14), and `HoldRequest`. `Section` and `SectionMatch` go.
- `views.py`: `to_claim` builds the whole decision record.
- `instructions/claim.md` and `instructions/improver.md`: see "The instructions" below.

The agent:

- `routes.py` (new): what the two routes share: `Target` (`undercover-app` and `undercover-context`), the `Route` protocol and `GatewayRefused`. A route's `call(target, operation, inputs)` returns the answer parsed from its JSON, and `name(target, operation)` gives the name the call goes by on that route. `GatewayRefused.answer` is "Refused by the Gateway: ...", as `Refused.answer` is the app's. It imports nothing else in the agent.
- `mcp_tools.py` (new): MCP tools for the synchronous agent. It lists a server's tools with `MultiServerMCPClient` over streamable HTTP, with `handle_tool_errors=False` and an `httpx.Auth` when it's given one, and calls one by name. Each call runs on an event loop of its own that it closes without touching the thread's, so the main thread keeps its loop for Mangum (the trap `conftest.py` notes). Each call opens a session of its own, since both servers are stateless. A service's refusal comes back as LangChain's `ToolException` with the service's answer, and an MCP error is raised as it is.
- `gateway.py` (new): the Gateway route. `SigV4Auth`, the lab's `httpx.Auth`, signs each request with botocore's SigV4 for `bedrock-agentcore`, with the credentials and region of boto3's default session, which are the AWS CLI's. It calls `<target>___<operation>`, with the separator written here alone, and raises an MCP error from a tool call as `GatewayRefused`. `from_environment()` reads `UNDERCOVER_GATEWAY_URL` and gives the route, or none when it isn't set.
- `direct.py` (new): the direct route. The app's operations go through their functions in `api.py`, with the key; the context layer's go as MCP tools at `UNDERCOVER_CONTEXT`, or `http://127.0.0.1:8006/mcp` when that isn't set, unsigned. Calls go by their own names.
- `memory.py` (new): AgentCore Memory. `memory_store()` gives an `AgentCoreMemoryStore(memory_id=..., region_name=...)` in boto3's default region when `UNDERCOVER_MEMORY_ID` is set, or none. `remember(store, claim, decision)` saves the two events and returns what it saved. `recall(store, customer_id, claim_id, query)` searches one customer's memories and leaves out this claim's own summary, by the namespaces each record lists in `value["namespaces"]`. The namespaces are written here alone.
- `tools.py`: `ClaimContext` gains the claim's policy and customer, the route and `decided_by`. The app's tools go through the route and take no id from the model. It gains the context layer's seven tools and `search_memory`. `claim_tools(remembers)` gives the tools for a graph, with `search_memory` only when the graph remembers, and `TARGETS` names each tool's target.
- `harness.py`: `refusal` answers a `GatewayRefused` too, and `record_result` records any refused call as a `refusal` step. `pay` pays through the route and holds a payment the Gateway refused. It gains the `remember` node, and `record_reply` names each call as its route does. `claim_graphs(version, pool, kind)` reads the route and the memory when it builds a run's graphs, and builds `ClaimAgent`s: each a graph with a saver of its own, plus the route and the `decided_by` its claims' contexts need. `work_claim`, `carry_on` and `work_in_run` take a `ClaimAgent` where they took a graph, and build each claim's context from the claim.
- `api.py`: loses `search_documents`, `read_section` and `DocumentName`; gains `hold_payment`; `record_decision` gains `decided_by` and `record_step` gains `sources`; the step kinds.
- `service.py` passes each run's kind to its claim agents, and `__main__.py` builds them for no run. `dispatcher.py` doesn't change.

Inside the agent, `harness` now also uses `routes`, `gateway`, `direct` and `memory`; `tools` uses `routes` and `memory`; `gateway` and `direct` use `routes` and `mcp_tools`, and `direct` uses `api`; `routes`, `mcp_tools` and `memory` use nothing else in the agent. The improver uses none of them.

The dashboard:

- `api.ts`: the step kinds, `Source`, each step's `sources`, and the decision's new fields with `Calculation`.
- `StepList.tsx`: each kind of step, as below.
- `ContextUsed.tsx` (new) takes the place of `SectionsRead.tsx`.
- `DecisionPanel.tsx`: the whole record, with the calculation line by line, and the sign-off panel for a payment the Gateway refused.

The rest:

- `pyproject.toml`: `pyyaml` and `langgraph-checkpoint-aws` join the dependencies, and `pyyaml` joins the `server` group too, since `backend.main` imports seeding. A new `context` group holds exactly what the server needs on Lambda: `mcp`, `mangum` and `pyyaml`. Ruff, pyright, pytest and coverage take in `context/`.
- `package.json`: `dev:context` (`uv run -m context`), which `dev` starts beside the backend, the agent's service and the dashboard, and `check:context` (`uv run --isolated --only-group context python -c "import context.server"`), which `check` runs after `check:server`.
- `e2e/api.ts`: its one `decide` helper records a matching calculation first and sends the maker.

### How the claim agent reaches each thing

| What | Gateway route | Direct route |
| --- | --- | --- |
| The model's app tools: `get_claim`, `get_policy`, `get_claim_history`, `calculate_payout`, `record_decision` | `undercover-app___<operation>`, signed | `api.py`, with the key |
| The payment, made by the `pay` node | `undercover-app___pay_claim`, signed | `api.pay_claim`, with the key |
| The context layer's tools | `undercover-context___<operation>`, signed | MCP at `UNDERCOVER_CONTEXT`, unsigned |
| Bookkeeping (start, steps, model calls, work times, failures), the check's read and its referral, `hold_payment`, the runs, the versions and the improver | The app directly, with the key | The same |
| Memory | AgentCore Memory directly, with the AWS CLI's credentials | The same |

- Both routes give the model the same tools, with the same names and inputs: they are the agent's own tools in `tools.py`, and only the route under them changes. Each answer is parsed from its JSON and handed to the model with `as_json`, so `get_claim` gives the same text on both routes, and it's the text the check reads through `claim_as_read`.
- The tools fill in what the agent knows from `ClaimContext`: the claim's id for `get_claim`, `calculate_payout` and `record_decision`, its policy for `get_policy`, its customer for `get_claim_history`, and `decided_by` for `record_decision` (phase 3). A claim agent can act only on its own claim and read only its own customer's records (claims manual section 11). Recording a decision still ends the agent's work through the graph's state.
- A refusal by the app or the context layer comes back as `Refused` from a direct call to the app and as `ToolException` from an MCP call. `refusal` gives the model either one as a refusal with its reason, as today, and `record_result` records it as a `refusal` step. An MCP tool never answers a refusal as if it had succeeded, since `handle_tool_errors` is off.
- A tool call the Gateway refuses raises `McpError` in the MCP client, which `gateway.py` raises as `GatewayRefused`. `refusal` answers it with "Refused by the Gateway: ..." and `record_result` records it, so the claim's work goes on.
- A payment the Gateway refuses: `pay` records the refusal as a `refusal` step and calls `hold_payment` with the Gateway's reason. That moves the approved, unpaid claim in progress to waiting for sign-off and keeps the reason on the decision as `gateway_refusal`. The graph ends there, as for any held payout, and a handler's sign-off pays it through the app, as today. A repeat of the hold after a restart returns the claim, and a claim that isn't approved, is paid or isn't in progress gets a 409. `hold_payment` needs the key, and it stays off the Gateway and out of the agent's API document. This only happens when the approval limit setting has been raised above the Policy's $1,000, so the tests cover it.
- `claim_graphs` reads `UNDERCOVER_GATEWAY_URL`, `UNDERCOVER_CONTEXT` and `UNDERCOVER_MEMORY_ID` when it builds a run's graphs, never on import, so `uv run -m agent`, which loads `.env` after its imports, sees them. It lists the route's tools at the same moment, once for the run, so a context layer that isn't running stops the run at its start with one line saying so.
- The agent stays synchronous and works on Windows: the bridge makes a fresh loop for each call and never calls `asyncio.run`.

### The context layer's tools

| Tool | Inputs | Answer |
| --- | --- | --- |
| `lookup_term` | `term` | The term as the glossary writes it, its definition and the sections of the wording it comes from, matched whatever its case. An unknown term gets an answer saying so, with the terms the glossary defines |
| `describe_fields` | `record`: `claim`, `policy` or `previous_claim` | The record's description and its fields from the data dictionary |
| `get_plan` | `plan`: `economy`, `premium` or `first` | The plan's limits, waiting periods and deductible, the benefits the deductible applies to, and the add-ons |
| `get_claim_rules` | none | The claim rules |
| `search_reference_data` | `query` | The facts that contain every word of the query, whatever its case, each with its topic |
| `search_documents` | `query` | As the app's operation does today: the sections whose title or text contains the query, ignoring case, with the paragraphs that mention it, each naming its file |
| `read_section` | `document`: `policy_wording` or `claims_manual`, and `number` | As the app's operation does today: one section in full with its document's title |

- Every answer is a JSON object holding `sources`: the files it came from, each with its `file` name and the `system`, `owner` and `reviewed` date of that file's source. A search of the documents names the file of each section it finds, and its `sources` are those files.
- A section that doesn't exist, or an input outside its allowed values, is refused with its reason, and the model sees the refusal on both routes.
- The tools follow the API rules: a one-line docstring as the description and every input required. A test checks each tool's input schema with the same rules `api_rules.py` applies to the app.

### A complete decision record

- `calculate_payout` now keeps its calculation (its lines and its payout) in `calculations`, one row a claim with the thread it was made on, each calculation replacing the last. The latest calculation on the claim's current thread is the one that counts. It refuses a claim that hasn't been started with a 409, as `record_step` does, since there's no attempt yet. Its docstring says it keeps the calculation for the decision.
- `record_decision` checks, in this order:
  1. The request, before the app looks at the claim, so the answer is the same on any claim, CLM-9999 included. A blank reason, section or maker, an approval that pays nothing, and a decline or a referral that pays something each get a 422 whose `detail` is one sentence naming claims manual section 14 and what's missing, such as "Claims manual section 14: a decision record needs who or what made the decision". A decision other than approve, decline or refer is still Pydantic's own 422.
  2. The claim, as today: a 404 for an unknown claim, the same decision again returns the claim, a different decision on a decided claim gets a 409, and so does a claim that isn't in progress.
  3. For an approval, the calculation: there must be one on file for this attempt, and the payout must equal its payout. Each failure gets a 422 naming section 14, such as "Claims manual section 14: an approval needs the calculation of its payout for this attempt. Work it out with calculate_payout" or "Claims manual section 14: the payout must be the calculation's $243.00".
- The record holds these fields, with the new ones named as `context/data_dictionary.yaml` names them:

  | Field | What it holds |
  | --- | --- |
  | `decision`, `payout`, `section`, `reason`, `decided_at` | As today |
  | `calculation` | For an approval, the calculation's `lines` (each step and amount) and its `payout`, as `calculate_payout` gave them; none for a decline or a referral |
  | `decided_by` | "UnderCover Agent, version N", from the version the claim agent works on, or "Security check" for the check's referrals, which sit outside the versions |
  | `manual_version` | The claims manual's version in force (section 13), from the documents table, such as "2026.2" |
  | `signed_off_by`, `signed_off_at` | Added by a handler's sign-off, as today |
  | `gateway_refusal` | The Gateway's reason for refusing the payment, or none (step 1). The data dictionary doesn't describe it, and the plan leaves data governance's file as it is |

- The model's `record_decision` tool has no `decided_by` input: the tool fills it in from `ClaimContext`, and `refer` sends the check's. The agent's API document, and so the Gateway's `record_decision` tool, has `decided_by` in its body, as the notebook expects.
- One shared helper in each test suite records approvals with a matching calculation and sends the maker, so the tests and their payouts stay as they are. The backend's `decide` in `backend/tests/claim_requests.py` writes the calculation row directly. The e2e `decide` in `e2e/api.ts` follows the brief's recipe through the API: one `expense` line under `emergency_medical` for the payout alone shows the plan's deductible, then a second for the payout plus the deductible leaves exactly the payout on file. The agent's `decide` in `agent/tests/stubs.py` scripts a `calculate_payout` before an approval's `record_decision`. A scripted stub can't read a first calculation's answer, so the helper takes the claim's deductible up front, from its plan in `context/plans.yaml`, and scripts one `expense` line under `emergency_medical` for the payout plus that deductible; a reply worked out from the last tool result would do too. Either way no expected payout changes. Tests that count a claim's model calls or steps gain the calculation's.

### Memory of each customer

- With `UNDERCOVER_MEMORY_ID` set and a run that isn't an evaluation (a claim worked on the command line has no run, and counts as not an evaluation), `claim_graphs` compiles each graph with the memory as its store, `compile(checkpointer=saver, store=store)`, adds the `remember` node and gives the model `search_memory`. Otherwise the graph has neither and is today's graph. The checkpoints stay in Supabase.
- `remember` runs once the claim agent's work ends with a decision it recorded: after `tools` for a decline, a referral or a held approval, and after `pay`. It isn't on the path from `refer`, so nothing is saved for a claim the check referred, and a failure before a decision never reaches it. As a node of its own it runs once, even when work carries on after a restart, since the checkpoint after it is saved.
- It saves two events, with the claim's customer as the actor and the claim as the session, through `store.put((customer_id, claim_id), key, {"message": ...})`. The first is the claim as a `HumanMessage`: its summary, the benefit claimed, the date and place of the incident and the items claimed, and never the story or the documents. The second is the decision as an `AIMessage`, with its payout, section and reason. Code always does this, and the model has no say.
- AgentCore turns the events into memories in the background, with the two strategies the deployment gives the memory: facts under `/customers/{actorId}/facts/` and a summary of each claim under `/customers/{actorId}/claims/{sessionId}/`.
- `search_memory(query)`, "Search what we remember about this claim's customer from their earlier claims.", calls `store.search(("customers", customer_id), query=query, limit=5)` for the claim's customer alone and returns each memory's text, from `value["content"]`. It leaves out the summary of the claim it's working on, which a claim worked again would otherwise find. `AgentCoreMemoryStore` 1.2.4 sets every result's `namespace` to the prefix searched, `("customers", <customer>)`, and a record's own namespace is only in `value["namespaces"]`, a list of strings such as `/customers/CUS-3005/claims/CLM-1005/`. So the filter drops a result when that list holds this claim's summary namespace, and never looks at the result's `namespace`.
- When AgentCore can't be reached, `remember` logs a warning and the claim keeps its decision, and `search_memory` raises a `ToolException`, which the model gets as a refusal.
- The claim history in our records is still what counts for repeat claims (claims manual section 9).

### The claim graph

```
START -> screen --(instructions found)--> refer -> END
            |
            +--(none found)--> agent <-> tools --(paid at once)--> pay --> remember -> END
                                             +--(held, declined or referred)--> remember -> END
```

With memory off, or in an evaluation, there's no `remember` and those edges go to `END`, as today. A payment the Gateway refuses ends `pay` with the claim held, then goes on to `remember`.

### Every step on the claim page

| Kind | Recorded when | Content | Sources | On the page |
| --- | --- | --- | --- | --- |
| `screening`, `message`, `tool_result`, `error` | As today | As today | None | As today |
| `tool_call` | The model calls a tool | The call, named as its route names it | None | "Called" and the call |
| `lookup` (in place of `reading`) | The context layer answers a tool | What was looked up, such as `Term "unattended"`, `Plan: premium`, `The claim rules`, `Fields of a claim`, `Reference data: "Lisbon strike"`, `Documents: "unattended"` or `Claims manual, section 14: Records` | The files the answer came from | "Looked up", with each file and its source |
| `memory_search` | `search_memory` answers | The query and what it found | None | "Searched memory", with what it found |
| `memory_save` | `remember` saves | What was saved | None | "Saved to memory", with what was saved |
| `refusal` | A tool call or the payment is refused | The tool, named as its route names it, and the refusal, which names the Gateway when the Gateway refused | None | A Raspberry "Refused" chip with an icon, standing out from the other steps |

- The model's reply names its own tools. `record_reply` records each call as the route names it, such as `undercover-context___lookup_term(term="unattended")` on the Gateway and `lookup_term(term="unattended")` directly, and `record_result` names a result or a refusal the same way.
- The context layer's tools return their answer for the model and their `lookup` step as the tool's artifact, as `read_section` gives its reading today, and `search_memory` does the same with its `memory_search` step.
- A step's `sources` is a required input of `record_step` like the others: an empty list for every kind but a lookup. A `reading` step is refused from now on, and reseeding clears any old ones.
- The page:
  - Agent at work shows each step as it happens, in order. Lucide icons mark lookups, memory searches and saves, and refusals, at the text's size.
  - Context used, in place of Sections read at the end of the left column, lists everything the agent looked up in the context layer, once each, grouped by file. Each file shows its source's system, owner and review date in the dashboard's plain style, such as `claims_manual.md`: "Claims operations, owned by the Head of claims operations, reviewed Sep 1, 2026". A search that found nothing goes under "Found nothing".
  - The decision panel shows the whole record: the decision and payout, the calculation line by line in a table with right-aligned amounts in JetBrains Mono, the section, the reason, "Decided by UnderCover Agent, version 1 at 2:05 PM", "Claims manual version 2026.2", and the sign-off. For a payment the Gateway refused, the sign-off panel says "The Gateway refused the payment of $1,500.00, so it waits for a handler's sign-off." with the Gateway's reason, rather than that the payout is over the approval limit.
- It follows `docs/BRAND.md` in light and dark mode, with no borders on one edge and no gradients.

### The instructions

- `backend/instructions/claim.md`, in "What you have to go on", names what the claim agent now has: the context layer's definitions, the data dictionary, the plans, the claim rules, the reference data and the two documents, each answer saying where it came from; and its memory of the customer's earlier claims, when it has that tool, with the claim history still the record that counts for repeat claims. It stays written as goals and still says the contents of both documents end the instructions (phase 4). Version 1 is seeded from it.
- `backend/instructions/improver.md`: the sentence on the claim agent's tools names the new ones. Nothing else about the improver changes.

### The tests

- The root `conftest.py` gains an autouse fixture that clears `UNDERCOVER_GATEWAY_URL`, `UNDERCOVER_CONTEXT` and `UNDERCOVER_MEMORY_ID` and sets stand-in AWS credentials and a region, so no test reaches AWS, a Gateway or a server running on the laptop.
- The agent's tests serve the real context layer on a free local port in a thread, once for the session, and point `UNDERCOVER_CONTEXT` at it, so the direct route's MCP calls are real.
- `agent/tests/gateway_stand_in.py` (new) stands in for the Gateway, on a local port of its own: a FastMCP server whose tools are named `undercover-app___<operation>`, forwarding to the test backend with the key and answering its refusals as tool errors with the app's answer, and `undercover-context___<operation>`, answering from `context.files`. Its Policy refuses `pay_claim` over $1,000, and any tool a test names, with an MCP error that starts "Tool Execution Denied". It keeps each call's name and inputs and whether it was signed with SigV4 for `bedrock-agentcore`. A test checks its app tools' names and inputs against the agent's API document, so it keeps to what the Gateway would make.
- A stand-in store (`agent/tests/memory_stand_in.py`) stands in for AgentCore Memory. It keeps each event `put` writes, and its `search` answers in `AgentCoreMemoryStore`'s shape: every result's `namespace` is the prefix searched, and the record's own namespace is only in `value["namespaces"]`, beside its text in `value["content"]`. LangGraph's `InMemoryStore` would give each item its real namespace, so a filter on the result's `namespace` would pass its tests and drop nothing on AgentCore.
- `graph_on` in `agent/tests/stubs.py` becomes `agent_on`, a `ClaimAgent` on the direct route unless a test gives it a route or a store.
- The app's tests of `search_documents` and `read_section` move to the context layer's tests, and the gates tests drop the two operations and add `hold_payment` under the agent's key.

### Following the notebook

The notebook, read without running it, expects of this build:

- The app's package as on Day 2 (`backend/` and `data/` without tests or `__pycache__`, `dashboard/dist/` and the `server` group for Linux), which still imports and needs no `context/`.
- `/api/agent/openapi.json` with six operations, which the Gateway turns into `undercover-app___<operation>`, with `amount` in `pay_claim`'s body and `decided_by` in `record_decision`'s.
- The `context` group exported with `uv export --only-group context` and installed for Linux and Python 3.12, beside `context/` without tests or `__pycache__`, under the handler `context.server.handler`, with no environment variables, on 512 MB and a 30 second timeout.
- A signed `tools/list` posted to `/mcp` with `Accept: application/json, text/event-stream` answering in JSON (`json_response=True`), with each tool's description.
- Each context file's `source` with `system`, `owner` and `reviewed`, in a YAML file's top level or a document's front matter, which the plan leaves as they are.
- `undercover-context___lookup_term` with `term="unattended"`, `undercover-context___read_section` with `document="claims_manual"` and `number=14`, and `undercover-context___search_reference_data` with `query="Lisbon strike"`, which finds the Lisbon strike.
- `undercover-app___pay_claim` of $4,800 on CLM-1005 refused by the Policy, and `undercover-app___record_decision` of a referral that pays $243 refused by the app's section 14 check whatever the claim, before it reads the claim.
- `UNDERCOVER_GATEWAY_URL` and `UNDERCOVER_MEMORY_ID` in `.env`, and `uv run -m agent CLM-1005` with `UNDERCOVER_API` set to the app on Lambda: the tools and the payment through the Gateway, the bookkeeping to the app with the key, and the claim saved to memory once it's decided, with CUS-3005 as the actor and CLM-1005 as the session.
- A search under `/customers/<customer>` alone, and a memory search on CLM-1006's page when the agent chose to search.

Where the notebook and the brief differ, the brief wins. The notebook's `call_tool` reads an app refusal as a result, with the client's default error handling; the agent turns error handling off, so it raises and becomes a refusal.

### Checked against the code standards

- One way to call each service (rule 7): the claim agent's tools reach the app and the context layer through one route, `gateway.py` or `direct.py`, with one module for each route. `UNDERCOVER_GATEWAY_URL`, the `___` separator and `bedrock-agentcore` are written in `gateway.py` alone; `UNDERCOVER_CONTEXT` and its default in `direct.py` alone; `UNDERCOVER_MEMORY_ID` and the namespaces in `memory.py` alone; the target names in `routes.py` alone; and the app's address in `connection.py`, as today. The rule's text is updated to say so in phase 1, so every later review checks it.
- One job a module (rule 8): `mcp_tools.py` calls MCP tools from synchronous code, `gateway.py` signs and names the Gateway's calls, `direct.py` sends the direct route's, `memory.py` reads and writes the memory, `records.py` checks a record against section 14, `context_files.py` reads the context files for seeding, `context/files.py` answers lookups, and `context/server.py` serves them.
- Literals once (rule 9): the refusal answers, the section 14 messages, the step kinds, `decided_by`'s two forms, the targets, the namespaces and the port.
- The framework's own way (rule 10): `MultiServerMCPClient` from `langchain-mcp-adapters`, an `httpx.Auth` with botocore's `SigV4Auth`, FastMCP with stateless JSON responses and `TransportSecuritySettings`, Mangum, a LangGraph store passed at compile and read through `ToolRuntime.store` and `Runtime.store`, `AgentCoreMemoryStore`, `ToolNode`'s `handle_tool_errors` and `wrap_tool_call`, tool artifacts for steps, FastAPI and Pydantic for the record, and `yaml.safe_load`.
- One job a function (rule 11): `pay` pays and hands a refused payment to `hold`; `remember` saves; each tool calls one operation; `record_decision` calls `records.py` for its checks.
- The agent (rule 13): its parts stay apart, with the routes and the memory added. Rules about claims and payments are still enforced by the app and the Policy, whatever the agent does.
- Instructions as goals (rule 14): the claim agent's instructions name what it has to go on, and code saves to memory and fills in the maker.
- Bringing code up to standard first (rule 12): the tools that took ids from the model read them from `ClaimContext` before anything else moves onto a route.

### How the criteria are checked

Phases 1 to 5 use pytest, vitest and Playwright, which never read `.env` and use SQLite, a stub model, the real context layer on a local port, and stand-ins for the Gateway, AgentCore Memory, Langfuse, the agent's service, Supabase Auth and the judge. Some criteria also use commands on a SQLite backend seeded into the scratchpad with a throwaway key, and `uv run -m context` on its own. Phase 6 reseeds Supabase once with `npm run seed`, runs `npm run dev` on the default model with no `UNDERCOVER_GATEWAY_URL` or `UNDERCOVER_MEMORY_ID`, and checks pages through the Playwright MCP server, signed in as Dana Whitfield with `HANDLER_PASSWORD`. No command prints a key.

## Phase 1: Tools from the Gateway

Add `routes.py`, `mcp_tools.py`, `gateway.py` and `direct.py`, and the stand-in Gateway. Move the claim agent's app tools and the payment onto the route, with the ids from `ClaimContext`. Add `hold_payment`, the decision's `gateway_refusal` and the sign-off panel's words for it. Bring the `refusal` step kind forward from step 5, since this step records refusals; the other step kinds come in phase 5. Update rules 7 and 13 in `docs/CODE_STANDARDS.md`. Until phase 2, the documents tools go to the app on both routes, as `undercover-app___search_documents` and `undercover-app___read_section` on the Gateway. The live check for this step is in phase 6.

- [x] pytest (agent): the model's tools are the same on both routes, with the same names and inputs, and `get_claim`, `get_policy`, `get_claim_history` and `calculate_payout` have no id among their inputs
- [x] Stub test, Gateway route: a claim agent reads CLM-1001, its policy and its history, works out the payout and approves $420.00. The stand-in Gateway receives `undercover-app___get_claim`, `undercover-app___get_policy` with POL-2001, `undercover-app___get_claim_history` with CUS-3001, `undercover-app___calculate_payout`, `undercover-app___record_decision` and the graph's `undercover-app___pay_claim`, each signed for `bedrock-agentcore`. The claim is decided and paid once
- [x] Stub test, Gateway route: the stand-in receives none of the bookkeeping, the check's read or its referral, which reach the app directly with the key
- [x] Stub test: `get_claim` gives the model the same text on both routes, and it's the text the security check is sent
- [x] Stub test, each route: a decision the app refuses reaches the model as a refusal with the app's reason, is recorded as a `refusal` step, and the claim's work goes on to a decision
- [x] Stub test, Gateway route: a tool call the stand-in's Policy refuses reaches the model as "Refused by the Gateway: Tool Execution Denied ...", is recorded as a `refusal` step that names the Gateway, and the claim's work goes on
- [x] Stub test, Gateway route: with the approval limit changed to $2,000, an approval of $1,500.00 whose payment the Gateway refuses is recorded as the Gateway's refusal and ends waiting for sign-off, reported as `CLM-1002  approve  $1,500.00, waiting for sign-off`, with the Gateway's reason on the decision. Dana's sign-off then pays it once, and carrying the claim on afterwards runs nothing
- [x] pytest (backend): `hold_payment` with the key moves an approved, unpaid claim in progress to waiting for sign-off with the reason, and a repeat returns the claim; a claim not approved, already paid or not in progress gets a 409 (an approved, unpaid claim is always in progress or already held, so a claim not in progress, such as one waiting, gets the 409 for not being approved); without the key it gets a 401; it isn't in the agent's API document, and the gates tests list it under the agent's key
- [x] pytest (agent): with `UNDERCOVER_GATEWAY_URL` set after the agent's modules are imported, the next claim graph built uses the Gateway; with it unset, the direct route
- [x] pytest (agent): after an MCP call on the main thread, `asyncio.get_event_loop()` still returns the thread's loop, and the Lambda handler tests pass in the same session
- [x] pytest: the stand-in Gateway's app tools have the names and inputs of the agent's API document's operations
- [x] The boundaries test allows `harness` to use `routes`, `gateway` and `direct`, `tools` to use `routes`, `gateway` and `direct` to use `routes` and `mcp_tools`, `direct` to use `api`, and `routes` and `mcp_tools` to use nothing else in the agent; the improver uses none of them
- [x] `grep -rn "UNDERCOVER_GATEWAY_URL\|bedrock-agentcore\|___" agent --include='*.py'` finds them only in `agent/gateway.py` and tests
- [x] vitest: a `refusal` step shows a "Refused" chip that stands out from the other steps; a held payout with `gateway_refusal` says "The Gateway refused the payment" with its reason, and one without says it's over the approval limit, as today
- [x] `docs/CODE_STANDARDS.md` rules 7 and 13 describe the two routes, with one module for each, and the shared MCP module
- [x] `npm run check` passes with `.env` moved out of the way

## Phase 2: The context layer

Add the `context` package, its Lambda handler, the `context` group and its check, and `dev:context`. Seed the plans and the documents from `context/` through `backend/context_files.py`. Remove the app's `search_documents` and `read_section`, and move the claim agent's documents tools and the five new ones onto the context layer through both routes. Build both packages in the scratchpad and add the context layer to `docs/TECH_STACK.md`'s Deployment section. The live check for this step is in phase 6.

- [x] pytest (context), against the real files: `lookup_term("UNATTENDED")` gives the glossary's definition with section 5 and `glossary.yaml`'s source (The policy wording, version 2026.1; Legal; 2026-09-01); an unknown term gets an answer that lists the glossary's terms
- [x] pytest (context): `describe_fields("claim")` includes `decision.manual_version`; `get_plan("premium")` gives a deductible of 50.00, the deductible's two benefits and the three add-ons; `get_claim_rules()` gives the four rules; each names its file and source
- [x] pytest (context): `search_reference_data("lisbon STRIKE")` finds the Lisbon strike under `events` and nothing that holds only one of the words
- [x] pytest (context): `search_documents("unattended")` finds the sections it finds in the app today, each naming its file; `read_section("claims_manual", 14)` gives "Records" with `claims_manual.md`'s source; section 99 is refused, saying it wasn't found
- [x] pytest (context): no section holds any front matter, the documents' versions are 2026.1 and 2026.2, and the files are read at import and not again on a request
- [x] pytest (context): every tool has a one-line description, is read only, and has every input required
- [x] pytest (context): the Lambda handler, called twice in one process with Function URL events whose host is a Function URL's, first lists the seven tools and then calls `lookup_term`, and both succeed
- [x] `npm run check:context` passes, and the packages in `.venv` are the same before and after it; `npm run check:server` still passes, with `pyyaml`
- [x] `uv run -m context` serves `http://127.0.0.1:8006/mcp`, where a `tools/list` posted with `Accept: application/json, text/event-stream` answers in JSON with the seven tools; with it running, a short script with no model builds the direct route and calls each of the claim agent's context tools, and each answers
- [x] `uv run -m backend.seed` prints the same counts as before; pytest shows the payout rules equal `context/plans.yaml` without its source, and each document's text is its file's body without the front matter, with its version 2026.1 or 2026.2, which shows the documents come from `context/`; `git diff --exit-code week3day3-start -- data context/*.yaml context/*.md` passes
- [x] `grep -rn "plans.json" backend agent context --include='*.py'` finds nothing outside tests
- [x] pytest: `/api/agent/openapi.json` holds exactly `get_claim`, `get_policy`, `get_claim_history`, `calculate_payout`, `record_decision` and `pay_claim`; the app has no `search_documents` or `read_section`; a version's instructions still end with the contents of both documents
- [x] Stub tests: the context layer's tools answer on the direct route, from the real context layer, and on the Gateway route as `undercover-context___<operation>`; a section that doesn't exist reaches the model as a refusal on each route
- [x] The two packages, built in the scratchpad as the notebook builds them, are each under 50 MB zipped, and the report gives their sizes (21.0 MB for the app and 10.3 MB for the context layer)
- [x] `npm run dev` starts the backend, the agent's service, the context layer and the dashboard, and stops them all together
- [x] `docs/TECH_STACK.md`'s Deployment section: the context layer's package, its handler `context.server.handler` behind a Function URL with `AWS_IAM` auth and no environment variables, and the app reading `context/` only while seeding
- [x] `npm run check` passes with `.env` moved out of the way

## Phase 3: A complete decision record

Keep each claim's latest calculation, add `decided_by`, `records.py` and the record's new fields, and the manual's version on the documents. Give each test suite its one helper for approvals. The live check for this step is in phase 6.

- [x] pytest: `calculate_payout` keeps the latest calculation for the claim's current attempt, a second replacing the first; a new attempt starts with none; on a claim never started it returns 409
- [x] pytest: a blank reason, a blank section, a blank maker, an approval paying 0, and a decline and a referral paying $243 each return 422 with a one-sentence `detail` naming claims manual section 14, on a claim in progress and on CLM-9999 alike, and record nothing
- [x] pytest: an approval with no calculation for this attempt, one with a payout other than the calculation's, and one whose calculation was made on an earlier attempt each return 422 naming section 14 and record nothing
- [x] pytest: a complete approval's record holds the calculation's lines and payout, `decided_by`, `decided_at` and `manual_version` "2026.2"; a decline and a referral hold no calculation; a sign-off still adds who signed off and when
- [x] pytest: every `decision.` field `context/data_dictionary.yaml` names is a field of a claim's decision
- [x] Stub test: the claim agent's decisions are made by "UnderCover Agent, version 1", or the version its run works on, and the check's referral by "Security check"; the model's `record_decision` tool has no `decided_by` input
- [x] Stub test: an approval with no calculation reaches the model as a refusal naming section 14, recorded as a `refusal` step; the model then works out the payout and records the decision, which is recorded once
- [x] Stub test, Gateway route: the stand-in's `undercover-app___record_decision` receives `decided_by`
- [x] The backend's, the agent's and the end-to-end tests each record approvals through their one helper, and no test's expected payout changes
- [x] The shared OpenAPI rules test passes, and the agent's API document's `record_decision` body requires `decided_by`
- [x] e2e: every spec passes with the helper
- [x] `npm run check` passes with `.env` moved out of the way

## Phase 4: Memory of each customer

Add `langgraph-checkpoint-aws` with `uv add`, `agent/memory.py`, the `remember` node and `search_memory`, and the run's kind in `claim_graphs`. Rewrite "What you have to go on" in `claim.md` and the sentence in `improver.md`. Add the agent's settings to `docs/TECH_STACK.md`'s Deployment section. The live check for this step is in phase 6.

- [x] `langgraph-checkpoint-aws` is in the project's dependencies and in neither the `server` nor the `context` group
- [x] Stub test, with a stand-in store: after an approval is paid, two events are saved with the customer as the actor and the claim as the session: the claim (summary, benefit claimed, date and place of the incident, items claimed) as a `HumanMessage`, and the decision with its payout, section and reason as an `AIMessage`; neither holds the story or a document's text
- [x] Stub test: a decline, a referral by the model and an approval held for sign-off each save the two events; a claim the check referred, an evaluation's copy and a claim that fails before a decision save nothing
- [x] Stub test: a claim carried on after `remember` has run saves nothing more
- [x] Stub test, with the stand-in store answering in `AgentCoreMemoryStore`'s shape: `search_memory` searches only under `("customers", <the claim's customer>)`, returns each memory's text, and leaves out the summary of the claim it's working on, found by its `value["namespaces"]` while every result's `namespace` is the prefix searched; the customer's facts and other claims' summaries come back, and another customer's memories never do
- [x] Stub test: with memory off, and in an evaluation with memory on, the graph has no `remember` node and the model has no `search_memory` tool
- [x] Stub test: with a store that can't be reached, saving logs a warning and the claim keeps its decision, and a search reaches the model as a refusal
- [x] pytest (agent): `UNDERCOVER_MEMORY_ID` set after the agent's modules are imported is read when the next claim graph is built, and `AgentCoreMemoryStore` is made with that `memory_id` and boto3's default region, with the constructor replaced by a recorder
- [x] `grep -rn "UNDERCOVER_MEMORY_ID\|AgentCoreMemoryStore" agent --include='*.py'` finds them only in `agent/memory.py` and tests
- [x] `claim.md` names the context layer's definitions, plans, rules, reference data and documents and the memory of the customer, written as goals with no list of steps; `improver.md` names the claim agent's new tools; a test that version 1's instructions are `claim.md` still passes
- [x] `docs/TECH_STACK.md`'s Deployment section lists the agent's settings: `UNDERCOVER_GATEWAY_URL`, `UNDERCOVER_CONTEXT`, `UNDERCOVER_MEMORY_ID` and the AWS CLI's credentials and region when either AWS setting is set
- [x] `npm run check` passes with `.env` moved out of the way

## Phase 5: Every step on the claim page

Add the step kinds `lookup`, `memory_search` and `memory_save` in the app, `agent/api.py` and `dashboard/src/api.ts`, with each step's `sources`, and drop `reading`. Record each lookup and memory step, name each call as its route does, and build the Context used panel and the whole decision record on the claim page. The live check for this step is in phase 6.

- [x] pytest (backend): a step of each kind is recorded and listed with its `sources`; a `reading` step returns 422; `sources` is required
- [x] Stub test: each of the seven context tools records one `lookup` step saying what was looked up, with its file and that file's system, owner and review date; a search of the documents names the files of the sections it found
- [x] Stub test: `search_memory` records a `memory_search` step with its query and what it found, and `remember` a `memory_save` step with what it saved
- [x] Stub test: a section 14 refusal is recorded as a `refusal` step, followed by the model's next `record_decision` call
- [x] Stub test: on the Gateway route, each `tool_call` step names its tool as the Gateway does, such as `undercover-context___lookup_term(term="unattended")`; on the direct route, by its own name
- [x] vitest: each kind of step shows as the design says, with its icon, and a refusal stands out; Context used lists each lookup once, grouped by file, each file with its source, and a search that found nothing under "Found nothing"; there's no Sections read panel
- [x] vitest: the decision panel shows the calculation line by line, who decided and when, the manual's version, and the sign-off; a decline shows no calculation
- [x] e2e: steps of each new kind recorded through the API show on a claim's page as they're recorded, without a reload, and the Context used panel and the decision with its calculation show
- [x] `grep -rn '"reading"\|SectionsRead\|Sections read' agent backend dashboard/src e2e --include='*.py' --include='*.ts' --include='*.tsx'` finds nothing (with its quotes, so `threading` doesn't match) outside the two tests that check they're gone: the backend's, which sends a `reading` step and gets a 422 as the first criterion asks, and the dashboard's, which checks there's no Sections read panel
- [x] `npm run check` passes with `.env` moved out of the way

## Phase 6: The live checks and the docs

Reseed once, then run every live check in this order, on the default model, on the direct route with memory off. Then update the docs, review the whole branch against `week3day3-start` with a fresh subagent and fix what it finds.

- [x] `grep -c '^UNDERCOVER_GATEWAY_URL=\|^UNDERCOVER_MEMORY_ID=' .env` prints `0`
- [x] `npm run seed` prints 26 claims, 51 policies and 50 customers into the `undercover` schema on Postgres
- [x] With `npm run dev` running, signed in as Dana Whitfield, the queue, a claim, the Scoreboard, the Improvement, Configuration and Settings pages load with no errors in `browser_console_messages`; a short script with no model calls each of the claim agent's context tools on the direct route, and each answers
- [x] Steps 1 and 3: `uv run -m agent CLM-1001` prints `CLM-1001  approve  $420.00`, and the record read with the key (by a short script, so the key never appears on a command line) shows it complete: the calculation's payout of $420.00, "UnderCover Agent, version 1", `decided_at` and manual version 2026.2
- [x] Step 4: `uv run -m agent CLM-1005`, then `uv run -m agent CLM-1006`, each record a complete decision with no memory tool and no memory step, and the decisions are reported
- [x] A dispatch at N=25 on the queue page works the other 23 claims, and the decisions are reported beside the last live run's. CLM-1901 is referred by "Security check", every approval's payout equals its calculation's, and the report counts the section 14 refusals and the claims that needed a second attempt
- [x] An evaluation of the evaluation set's five tiny claims on the Scoreboard finishes, and its measures are reported beside the last live run's
- [x] Step 5: through the Playwright MCP server, signed in as Dana Whitfield, CLM-1005's and CLM-1006's pages show the tool calls, the lookups with the file each came from, the Context used panel and the decision with its calculation, in light and dark mode (screenshots), with no console errors
- [x] The Supabase MCP server's `select count(*) from undercover.decisions where decided_by is null or manual_version is null` returns 0, and `select count(*) from undercover.decisions where decision = 'approve' and calculation is null` returns 0
- [x] Report what the live checks spent, from the backend's records and the OpenRouter key's usage; on GPT-6 Luna it comes to under $0.25
- [x] `docs/SPEC.md`: the three sources of data, the context layer, the Gateway for the model's tools and the payment, the memory of each customer kept to that customer's claims, the complete decision record, and what the claim page shows
- [x] `docs/TECH_STACK.md`: `context/` and its server, the two routes, `mcp_tools.py`, the memory, `records.py`, seeding from `context/`, the six operations in the agent's document, `hold_payment`, the new settings, and the Deployment section
- [x] `docs/PROCESS.md`: `npm run dev` starts the context layer, `npm run check` includes the context check, and these live checks in place of the security changes'
- [x] `docs/CODE_STANDARDS.md` describes the agent's parts as built
- [x] `data/README.md`: seeding reads the plans and the two documents from `context/`, and `plans.json`, `policy_wording.md` and `claims_manual.md` stay in `data/` for the labs
- [x] `docs/STATUS.md` describes what's built, the live checks and what they cost, and the known gaps, including the data dictionary not describing `gateway_refusal`, AgentCore's memories arriving about 90 seconds after a save, and a `remember` stopped partway saving its events again when the claim carries on
- [x] A fresh subagent reviews the whole branch against `week3day3-start`, not `main`, with `docs/CODE_STANDARDS.md`; everything it would block the merge for is fixed, or explained in the report where I disagree
- [x] `npm run check` passes, both with `.env` in place and with it moved out of the way

## Not in this plan

- Deploying anything to AWS, creating the Gateway, its targets and Policy, the credential provider or the memory: the notebook does these. Nothing here creates anything on AWS.
- Running the agent itself on AWS. It stays on the laptop, and the agent's service still only takes the backend's calls.
- Memory in evaluations, and AgentCore's Episodic strategy (the notebook's assignment).
- Masking personal fields for the agent, and requesting documents from customers.
- Changing the content of the files in `context/`, which data governance owns.
- Rejecting a held payout, real payments, messages to customers and sign-up, as `docs/SPEC.md` says.
