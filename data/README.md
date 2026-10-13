# UnderCover seed data

The data behind UnderCover Travel Insurance, a fictional insurer. Everything here is invented, including the people, the airlines and the hotels. Amounts are in US dollars.

## The insurer's systems

- `company.json`: company settings, including the $1,000 payout approval limit, which seeding makes the first value of the setting.
- `plans.json`: the three plans (Economy, Premium, First) with their limits, waiting periods and deductibles, and the three add-ons. The labs read it; seeding reads the same plans from `context/plans.yaml`.
- `policies.json`: one policy per trip, with the plan, the add-ons, the purchase date, the trip and the travelers.
- `customers.json`: contact details and claim history, with the date and a one line summary of each earlier claim. This is personal data.
- `handlers.json`: the claims handlers, with the email each signs in with. Only Dana Whitfield (`dana.whitfield@undercover.example`) can sign off payouts over the limit, start and stop rounds, review the improver's proposals and change the settings; Marcus Oyelaran and Priya Raman can't.
- `improvement.json`: the improver's settings to start with, from the lab: the objectives on the held-out set, the noise and the tolerance for accuracy, the grade, cost per claim and time per claim, the spending limit for each round and the claim agents at once in its evaluations.
- `models.json`: the models the claim agent may use, with their reasoning efforts and prices in US dollars per million tokens.
- `claims.json`: the claims queue, twenty-five claims. Each has the customer's story, the items claimed and the supporting documents as text.

Set `MODEL_NAME` in `.env` before `npm run seed` if you're on a free model: seeding chooses version 1 of the claim agent and the models allowed from it.

## The documents

- `policy_wording.md`: the contract with the customer. Short enough to fit in a prompt.
- `claims_manual.md`: the internal handling manual. Longer, and it holds rules the wording does not, such as the third claim in 12 months, losses to wild animals and meals without receipts.

These two files and `plans.json` stay here for the labs. The product's copies are in `context/`, the context layer's seven files, which data governance owns: each names the system it comes from, its owner and when it was last reviewed, and the documents add their version. Seeding loads the plans and both documents from there.

## The evaluation set

- `evals/decisions.json`: the handlers' decisions on the twenty-five claims in the queue: approve, decline or refer, the payout, the calculation, the reason and what each claim tests. An agent deciding claims must never be shown this file.
- `evals/held_out_claims.json` and `evals/held_out_decisions.json`: twenty-five more claims with their decisions, kept out of the queue for checking that an improvement generalizes. They have the same blend as the queue. Keep them out of sight while you write a prompt or a rule, and score them afterwards.

The queue is the development set and the held-out claims are the test set. Nothing is trained on either.

Every decision also carries a few tags. `difficulty` is `routine`, `hard` (the wording settles it and it stretches a small model) or `manual` (it needs something the prompt does not hold, listed in `needs`: the claims manual, the customer's history or both). `failure_class` groups the hard claims that one rule should fix. `tone` is `plain`, `amusing` or `nod`. `tiny` marks a subset of five claims in each set, one of each kind, which fits inside a free model's daily allowance.

The labs define `get_sample_data(tiny=False, held_out=False)`, which returns the claims of either set with their decisions.

A decision is scored on two things: the decision itself and the payout. A valid claim that pays more than $1,000 is still an approve. The payment waits for a handler's sign-off, and `over_approval_limit` marks those claims.

## The security claim

- `security/`: CLM-1901, a stolen watch whose story carries an instruction to the AI to approve it in full, with its policy, its customer and the handler's decision (decline). It is a prompt injection kept for security testing, in a folder of its own. Seeding puts CLM-1901, its policy (POL-2901) and its customer (Derek Vance, CUS-3901) in the queue beside `claims.json`, `policies.json` and `customers.json`, which stay as they are, so the queue holds twenty-six claims. It never seeds `security/decisions.json`, so CLM-1901 is in neither evaluation set and no score changes.
