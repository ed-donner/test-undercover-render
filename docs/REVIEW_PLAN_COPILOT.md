# Review of the Copilot implementation plan

Reviewed `docs/PLAN_COPILOT.md` against `docs/COPILOT.md`, the project's required guidance, the existing backend, agent and dashboard, the referenced deployment material, and the installed framework code.

**Recommendation: retain the six-phase plan with the targeted amendments below.** This revision reflects the assessment of the original review. Keep the decision-time approval limit for the third success criterion. Do not add execution generations, reconciliation tables, action receipts or decision revisions.

This is a review of the proposed design, not a claim that the Copilot is implemented. The seven amendments below replace the original review's broader recommendations; leave the rest of the plan unchanged. Only this review has been edited. References to changes in the plan or `docs/STATUS.md` are recommendations for later work, not changes made to those documents.

## What the plan gets right

- It follows the required hand-written `StateGraph`, `ToolNode`, separate interrupt node, synchronous execution and durable checkpointer. It reproduces the course sidenote and uses the deployment notebook's runtime, environment and memory names.
- The handler's token belongs in runtime context, and the separate `call_as` path avoids the claim agent's API key. Checking `/api/me` before model work and enforcing conversation ownership in the backend are the right boundaries.
- Sign-off remains a handler operation enforced by the backend. Confirmation details come from records, and a fresh process can resume the graph.
- Waiting happens in code against the specific run returned by a start. The dedicated success-criteria tool and backend payment count provide a good basis for deterministic reporting.
- The proposed reads avoid the answer key. In today's code, `get_run` returns agent outcomes and `list_evaluations` returns aggregate measures; `get_evaluation` adds handler decisions. Keeping the latter out of the Copilot's API is appropriate.
- Handler memory has its own store setting and namespaces, derives its actor from verified identity, and saves only the user message and final answer.
- The plan covers the sidebar, ownership, token refresh, model-call limits, optional memory, local and Runtime entry points, and the required handover. It does not add AWS provisioning to application code.

## Agreed amendments

### 1. Write the complete success-criteria answer in code

The original plan appends the correct table to unrestricted model text, and its phase 3 test preserves incorrect figures before that table. Replace this with a terminal answer written entirely in code: the table and its verdict line, including the existing explanations for unavailable evaluation results.

After `check_success_criteria` finishes, the graph ends the turn through the memory node when enabled, with no further model call, as it does for Cancel. The sidebar, saved conversation and memory all receive exactly that answer.

**Plan changes:** remove `answer_of` and the instruction line telling the model that code will append the table. Update the graph's routing and the phase 3 wording to describe the code-written answer instead of a table appended to a model reply.

**Acceptance:** replace the “50% and 40%” test with one asserting that the final answer is exactly the code's table and verdict line, that the model is not called after the tool, and that memory saves the same answer. Retain the planned tests for a refused start, an unfinished or failed evaluation, no payouts over the limit, and a changed accuracy objective.

### 2. Bind the answer to the displayed turn and check the held decision

The confirmation request currently carries only `{answer}`, so an old browser tab can answer a newer card. Change the body to `{turn_id, answer}`, using the displayed card's turn id. The app refuses the answer if that turn is not the one waiting for confirmation.

For the waiting turn, Cancel is always accepted, regardless of whether the claim is still held or its decision still matches the card. For Sign off, the app compares the claim's current held decision with the decision captured for the card. If they no longer match, or the claim is no longer held, it resumes the graph as a Cancel with that reason instead of leaving the confirmation waiting. The turn ends with a code-written line: “The claim changed since the card was shown, so I canceled this sign-off without making a payment. Please ask again.” The conversation is then free for a new message. Use the existing decision record for this comparison; no decision revision or separate confirmation identifier is required.

Allow one `sign_off_claim` request per turn. A second request in that turn is refused with a line asking the handler to ask again, and creates no second pause. This keeps the existing single confirmation and pause-time fields sufficient.

The card shows “Signed off and paid” only from the sign-off's actual successful result, not from `confirmation_answer == "sign_off"`. While the action is pending, canceled, refused or failed, the card must reflect that outcome. A stale Sign off shows the cancellation and its reason. No action receipt is added.

**Acceptance:** add tests for a stale tab submitting an older `turn_id` and an answer after cancellation: each is refused and pays nothing. Test Cancel on the waiting turn when the decision has changed or the claim is no longer held: it is accepted and ends the turn. Test Sign off in both cases, including a changed reason with the same payout: it resumes as a Cancel with the reason, pays nothing, ends with the code-written explanation, and leaves the conversation able to accept a new message. Test a second `sign_off_claim` in the same turn: no second pause or payment, and the refusal asks the handler to ask again. In the sidebar tests, an accepted confirmation alone must not show “Signed off and paid”; the successful sign-off result must, and a cancellation, refusal or failure must not.

### 3. Run tool calls one at a time

Set `max_concurrency: 1` when running the Copilot's graph, including a resumed confirmation, as the claim agent's graph does. Keep the existing model setting that disables parallel tool calls; the graph configuration enforces serial execution even if a model reply contains several calls.

**Acceptance:** return multiple ordinary tool calls from the stub and verify that they execute one at a time in order. Retain the sign-off handling, with the one-sign-off-per-turn rule above.

### 4. Keep botocore above DEBUG and exercise its real request path

The original review verified that botocore's DEBUG request logging includes the invocation payload, which contains the handler's token. A stand-in replacing `invoke_agent_runtime` bypasses that logging path.

Keep botocore's logger above DEBUG, at INFO or higher, including when application logging is at DEBUG. Keep the existing rules that application logs, saved state, cards and memory never contain the sign-in.

**Acceptance:** make the DEBUG-log test use the real boto3 client with fake credentials and a fake handler token, stubbing only the network send. Let serialization and SDK request handling run normally. Capture logs with application logging at DEBUG, verify botocore remains above DEBUG, and assert that no log contains the token. This test makes no AWS request.

### 5. Make the phase wording match the work available in each phase

Three wording changes are needed:

- Phase 2's tool inventory includes only the tools implemented by phase 2. Exclude `wait_for_run`, `what_needs_a_handler`, `check_success_criteria` and the memory lookup until phase 3 adds them.
- Say that the claim agent's behavior tests stay unchanged, while its boundary tests change to describe the shared modules. The existing boundary tests require imports that the proposed extraction intentionally moves.
- Move phase 5's manual browser check on `npm run dev` to phase 6. Phase 5 keeps its vitest and end-to-end checks with the existing local stand-ins, consistent with the commitment to use no real services in phases 1–5.

**Acceptance:** phase-specific tool assertions match the implemented tools; the existing claim-agent behavior tests still pass; the updated boundary tests enforce the new module relationships. Phase 6 includes the greeting, open/collapsed sidebar, narrow window, light/dark mode and console checks previously assigned to the phase 5 manual check.

### 6. Add the negative payout case, bound conflict retries and observe connections

**Payment criterion:** keep comparing each queue payment with the approval limit recorded on its decision. The original review's recommendation to use the current Settings limit is withdrawn. Add a test fixture with a payment over its decision-time limit and no handler sign-off. The third criterion must report No. Keep the existing successful and empty-count tests and the exclusion of evaluation copies.

**Runtime conflicts:** cap conflict retries so the complete start request stays inside the app Lambda's 30 seconds. The budget must cover connection/read timeouts and retry sleeps, with time left to return the outcome. Stop retrying when that budget is exhausted, even if fewer than the planned four attempts have run. Preserve the existing distinction between work known not to have started and an uncertain result after sending it.

**Connections:** note Supabase's connection count during the existing live handover, particularly while the Copilot waits for the dispatch or evaluation it started. Record the observation with the live results; this does not require a pool redesign or extra live runs.

**Acceptance:** the seeded unsigned payout produces No; a test with delayed conflict responses proves that attempts and waits respect the total start budget; the final live report includes the observed connection count alongside the already planned costs.

### 7. Refuse late updates to stopped turns and document the crash gaps

Every turn-update route must use the same stopped-turn check as the read path. Once a turn is shown as stopped, refuse late step updates, pause reports, finish reports and failure reports, including when it is still the conversation's latest turn. A late callback must not change it back to working, waiting for confirmation, done or failed. A turn waiting for confirmation remains exempt from the working-turn timeout, as planned.

**Acceptance:** age a working turn past the cutoff, read it as stopped, and send each late update: every update is refused and the turn remains stopped. Repeat after a newer turn has begun and verify that its records are unaffected. No execution generation or broader recovery mechanism is added.

The gaps between a graph checkpoint and an app update remain accepted limitations. Recommend adding the following to `docs/STATUS.md` as known gaps of the Copilot design when that document is next updated:

- If the Copilot stops after saving an interrupt but before reporting the pause to the app, the saved graph is waiting for confirmation while the app still shows the turn working. The card is absent, and the app eventually shows the turn as stopped.
- If the Copilot stops after saving its result but before reporting completion to the app, the sidebar can miss an answer or confirmation outcome already present in the saved graph. A sign-off may already have paid, or memory may already have been saved; the app can still show the turn working and eventually stopped. Automatic reconciliation is not included.

These are documentation recommendations only. `docs/STATUS.md` has not been changed in this revision.

## Applying the amendments to the existing phases

| Phase | Agreed amendment |
| --- | --- |
| 1 | Require the card's `turn_id`, accept Cancel for the waiting turn and resume a stale Sign off as a Cancel with its reason, refuse late stopped-turn updates, bound conflict retries, and add the real-boto3 logging test and unsigned-payout count case. |
| 2 | Enforce one sign-off per turn and serial tool execution; keep behavior tests unchanged and update boundary tests and the phase-specific tool inventory. |
| 3 | End the success-criteria turn with the complete code-written answer; remove `answer_of` and the table instruction, and test exact output and the negative payment criterion. |
| 4 | Keep botocore above DEBUG wherever Runtime calls are made and retain the actual SDK request path in the logging test. |
| 5 | Base the confirmation card's success label on the actual sign-off result and test stale cards; keep checks on local stand-ins. |
| 6 | Include the moved manual browser check, note Supabase connections during the planned handover, and document the two checkpoint/app crash gaps. |

## Review evidence and limits

The review used repository source and documentation, read notebook source without executing notebook cells, and checked the installed LangGraph/ToolNode and botocore behavior relevant to the findings. The token-log probe used a fake token and fake AWS credentials with the send operation replaced; it made no network request. The plan has no Copilot implementation to exercise yet, so the proposed races and recovery paths are design findings with explicit tests to add.

No live model call, AWS deployment, live database reseed, or manual inspection of `data/evals/` was performed. Product code, the spec and the implementation plan were left unchanged.

Validation: `npm run check` passed, including the Python and TypeScript checks, isolated server/context/runtime imports, and all 24 Playwright checks. These establish the existing repository's baseline; they do not validate the unimplemented Copilot. The suite used its existing local stand-ins and temporary test databases.
