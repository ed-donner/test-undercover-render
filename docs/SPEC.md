# The claims pilot

From the head of claims operations at UnderCover Travel Insurance.

## How claims work today

UnderCover sells travel insurance on three plans: Economy, Premium and First. Our three claims handlers work through a queue of claims by hand. For each claim, a handler reads the customer's story and documents and checks them against the policy and our policy wording. Then they approve the claim with a payout, decline it or refer it. A claim is referred when it needs someone's judgment or more information, as the claims manual explains.

## The pilot

We want an AI agent, the UnderCover Agent, to work the queue the way a handler does. For each claim it should:

- read the claim, the customer's policy and claim history, and the sections of the policy wording and the claims manual it needs
- look up what else the business knows that bears on the claim, and what we remember about the customer
- approve, decline or refer the claim
- work out the payout when it approves
- explain the decision in two or three sentences, along with the relevant section of the policy

## What the agent works from

The agent works from three sources of data, each with a different owner:

- **The context layer** is the business's data from other systems, which data governance owns and the agent only reads: the terms the policy wording defines, what each field of a claim, a policy and an earlier claim means, the plans, the rules claims operations applies to every claim, facts from outside UnderCover such as storms, strikes and product prices, and the policy wording and the claims manual. Every answer names the file it came from, with that file's system, owner and review date.
- **Memory** is the agent's own notes on each customer. Once the agent's work on a claim ends with a decision it recorded, the claim and the decision are saved to that customer's memory, never the story or the documents, and the agent can search what we remember about a customer on their later claims. Each customer's memories are used only for that customer's claims. Nothing is saved for a claim the security check referred, and evaluations use no memory. The claim history in our records is still what counts for repeat claims.
- **The database** is the system of record: claims, policies, customers, decisions and payments. The agent reaches it only through our app.

When our AgentCore Gateway is set up, the agent's tools and its payments go through it, so the Gateway's Policy sees every call the model makes and every payment, and refuses any payment over $1,000. A tool call the Gateway refuses goes back to the agent as a refusal, and a payment it refuses waits for a handler's sign-off. Without the Gateway, the agent calls our app directly. Either way the agent can act only on its own claim and read only its own customer's records.

Our goal is to handle claims straight through, as accurately as our handlers do.

## Working the queue on its own

The agent works the queue in dispatches, with many claims at once:

- A handler starts a dispatch on the queue page, choosing how many claim agents work at once, from 1 to 25. A dispatch works every claim left in progress, every waiting claim and every claim sent back, oldest submitted first. Code chooses the claims and keeps track of the dispatch, with no model. Our app keeps one piece of the agent's work going at a time: a dispatch, an evaluation, or a round of the improver while it works. Asking for another while one is going says what is going. The agent can also work one named claim.
- Each claim goes to a claim agent of its own that works that one claim from a clean start and reports back in a line: the decision and payout, or what went wrong. Every step on a claim is recorded on that claim.
- Before the claim agent's model sees a claim, a second model reads everything the customer wrote, as the claim agent would read it, and checks whether it tries to instruct whoever handles the claim. A claim with such an instruction goes to a handler as a referral with the check's reason, and the claim agent's model never sees it. The check runs once at the start of a claim's work, on a model of its own that the improver can't change, and its result is the first step on the claim.
- For each claim the agent looks up the sections of the policy wording and the claims manual it needs, the way a handler would, rather than being handed whole documents, and whatever else in the context layer bears on the claim. It works out an approval's payout with UnderCover's payout rules, which are part of our systems.
- Every decision record meets claims manual section 14: it holds the decision, the payout, the calculation of an approval's payout, the section relied on, the reason, who or what made the decision (the UnderCover Agent with its version, or the security check) and when, and the claims manual's version in force. The system refuses a record that falls short, saying what is missing, and an approval's payout must be the calculation it worked out for that attempt.
- An approval over the approval limit pauses the agent's work on that claim, and the payment waits for a handler who can sign off over the limit. That handler either signs it off or sends it back to the agent with a note saying what to look at again, of up to 1,000 characters. A sign-off pays the claim at once, and the payment records who signed off and when; the agent then finishes its work on the claim. A send back keeps the decision with the note, who sent it back and when, clears it from the claim and records the note among the claim's steps. The agent reads the note as a senior handler's review, checked against the policy wording and the claims manual like everything else, and decides again, referring the claim when the wording doesn't support the note. Its new decision goes through the same checks as any other, and can be sent back again. A sent-back claim is taken up once, straight away or by the next dispatch if the agent didn't get it.
- Work survives a restart. If the agent is stopped partway through a claim, by a crash, a restart or Ctrl-C, the next dispatch carries on with that claim from where it got to, and that doesn't count as a new attempt. A dispatch that was stopped shows as stopped, with why. While the agent works on a dispatch, an evaluation, a round or a claim it resumed, it tells our app so every minute; work our app hasn't heard of for five minutes counts as stopped, "The agent stopped answering", and the next start goes ahead.
- Problems are put right automatically. A claim that hits a rate limit or a timeout waits and carries on from where it got to, as the same attempt, and one still hitting them after its waits stays in progress for the next dispatch. A claim that fails with any other error before it is decided goes back in the queue and the same dispatch tries it once more from the start, and a claim that fails twice is left for a handler. One bad claim never stops a dispatch, and no claim is ever decided or paid twice, even when a step runs again after a restart.
- When a dispatch finishes, its summary is built from our records, with no model writing it: how many claims were approved, declined and referred, each payout waiting for a sign-off, and each claim left for a handler or for the next dispatch.
- The tokens and cost of every model call, the security check's included, and the time the agent spends working on each claim are recorded with the dispatch or evaluation they happened in.
- Evaluations check the agent's work against our handlers' decisions. An evaluation works copies of one of our two labeled sets of claims, whole or its five tiny claims, through the same dispatcher and claim agent. The copies never show in the queue, a dispatch never picks them up, nobody can sign them off, and an approval held for sign-off counts as finished. An evaluation stopped partway shows as stopped. Each evaluation is scored with our measures: how often the decision matches the handler's, how often the payout does too, the cost of the mistakes, the share of claims handled straight through, the model cost and time per claim, and the time for the whole run.

## Improving the agent

The claim agent's instructions, model and reasoning effort make up one configuration, kept in versions, and a judge grades each of the agent's explanations in an evaluation against our handler's reason. A second agent, the improver, improves the configuration in rounds, which a senior handler starts on the Improvement page:

- A round first makes sure the current version has one evaluation on the evaluation set and two on the held-out set. The improver then follows its recipe: it reads the results, proposes a new version with its reason, and waits for a handler to approve or reject it. A rejection's reason goes back to the improver, which may propose again.
- An approved version is evaluated once on the evaluation set and twice on the held-out set, and our rule keeps it or rolls it back: it must meet our objectives on the held-out set, improve at least one measure by more than its noise and make none worse by more than its tolerance. A kept version becomes the current version. The improver then proposes a better recipe for the next round, which a handler approves or rejects in the same way.
- The improver can't change our objectives, the noise and tolerance, the spending limit, the models allowed, the approval limit, the evaluation sets or the judge, and nothing it proposes takes effect until a handler approves it.
- Each round has a spending limit covering the improver's own model calls, all of the round's evaluations and the judge. The improver is refused an evaluation that is likely to cost more than what's left, and once the limit is spent no new claim starts in the round's evaluations.
- Only one round is open at a time, and a senior handler can stop it. A round stopped before its verdict leaves the current version as it was.

## What the team needs to see

- The queue, with where each claim stands: waiting, in progress, waiting for sign-off, sent back, decided or left for a handler.
- The latest dispatch, with each of its claims and where it stands, its model cost and time, and its summary when it finishes.
- A scoreboard of the evaluations, newest first, with their measures, each opening to its claims beside the handlers' decisions with the misses easy to spot.
- Each claim in full, with the agent's decision and its reasons, and each decision sent back with its note, who sent it back and when.
- What the agent is doing on a claim while it works, step by step, starting with the security check: each tool it calls, each lookup in the context layer with where it came from, each search of the memory and each save to it, each refusal, standing out from the other steps, and any attempt that failed. A panel lists everything it looked up, once each, grouped by the file it came from with that file's source, and the decision shows the whole record with the calculation line by line.
- The claim agent's configuration: every version, what it changed from the one before, why, who proposed and approved it, and its held-out scores.
- The improvement rounds as they happen: where a round has got to, a proposal waiting with its change shown as a diff, the rounds so far with the held-out scores before and after, the verdict and why, who approved or rejected what and when, and the cost, a chart of each version tried, and the recipe's versions.
- The platform's settings: the approval limit, our objectives, the noise and tolerance, the spending limit for each round and the claim agents at once in its evaluations, with who changed them and when, and the models the claim agent may use.

## Rules

- Our handlers sign in with their email and password. Every page needs a signed-in handler, and the system checks the handler on every action they take.
- The agent identifies itself with an API key on every request it makes to our systems. What only the agent does needs the key, what only handlers do needs a signed-in handler, and the key never stands in for a handler.
- A payout over the approval limit, $1,000 to start with and a setting, needs a sign-off from a handler who can sign off over it. The agent can approve such a claim, but the payment waits until that sign-off. The system refuses any payment over the limit, even if the agent tries to pay, and the sign-off itself pays the claim. Only such a handler can also send a held decision back to the agent, start or stop a round, approve or reject the improver's proposals or change a setting; anyone else is told what they can't do and why.
- Decisions follow the policy wording and the claims manual. The wording comes first, and the manual says how to read it.
- Every decision record meets claims manual section 14, and carries the manual's version (section 13).
- Each customer's memories are used only for that customer's claims (claims manual section 11).
- Our handlers' own decisions on these claims are in `data/evals/`. We use them to check the agent's work, and the dashboard shows them beside the agent's for both labeled sets. The claim agent must never see them. The improver reads our handlers' decisions and reasons on the evaluation set, to learn from the misses, but nothing in the agent reads the held-out set's: those claims only score its changes.
- Amounts are in US dollars.

## Our records

Everything is in `data/`, described in `data/README.md`: the claims queue, the policies, the customers, the plans, the handlers, the policy wording and the claims manual. The held-out claims in `data/evals/` are for evaluations and stay out of the queue. Data governance's seven files in `context/` are the context layer: the data dictionary, the glossary, the plans, the claim rules, the reference data, the policy wording and the claims manual, each naming its source. Our systems load the plans and the two documents from there, and nobody but data governance changes them.

## Not for now

- No sign-up. Our handlers' accounts are set up for them.
- Declining a held payout outright. A handler signs it off or sends it back to the agent.
- No real payments.
- No messages to customers.
- Memory in evaluations.
- Masking personal fields for the agent, and requesting documents from customers.