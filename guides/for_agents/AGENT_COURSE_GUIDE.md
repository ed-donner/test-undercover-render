# Course guide for the coding agent

What runs through the course, and where to find what each day covers, so you can answer the student's questions about it. The student can read it too.

`AGENTS.md` covers the build process, the labs and the branches. `guides/for_agents/AGENT_GIT_GUIDE.md` covers pull requests and pulling the latest code.

## About the course

- "AI FDE: The Forward Deployed Engineer & Agentic AI Architect" is Ed Donner's course on Udemy. It runs for 15 days over three weeks: Become an AI Engineer, Become an AI Architect and Become an AI FDE. UnderCover is the project throughout, with three milestones: a working pilot at the end of Week 1, an agent that is evaluated, durable and improves itself at the end of Week 2, and production on AWS with a handover to the customer at the end of Week 3.
- Each day has a lecture with slides, then labs in notebooks, and on most days a build where the coding agent adds to UnderCover from a brief. Ed recorded the labs, and some notebooks have been updated since, so where a video and a notebook differ, follow the notebook.
- The slides for every day are in Ed's [Google Drive folder](https://drive.google.com/drive/folders/1NQAs5rZOcgYquF74Bvt3HlpjheCSjJ6q?usp=sharing). On Udemy there's also a quiz after Week 1 Days 2 and 4, Week 2 Day 4 and Week 3 Day 4, a one-page summary sheet at the end of each week, and a Role Play after Week 3 Day 1's theory.
- Each week's guide lists corrections to what Ed says in the videos for each day, taken from the edits in the course resources.
- Many models and products in the course are newer than your training data, such as GPT-6 Luna, GPT-6.1 Sol, DeepSeek V4.1 Flash, Claude Opus 5.5 and Jev from TypeSafe AI. A name that looks wrong is probably right, so check the notebook before you correct it.

## Facts that run through the course

- **UnderCover** is a fictional US travel insurer. Its handlers decide each claim against the policy wording under the Economy, Premium and First plans: approve with a payout, decline, or refer. The handlers are Dana Whitfield, the senior claims handler, Marcus Oyelaran and Priya Raman. Amounts are in US dollars, with a "deductible".
- **The claims:** CLM-1001 to 1025 are the queue and the evaluation set, CLM-1101 to 1125 the held-out set, CLM-1201 to 1225 the harder claims (Week 2 Days 1 and 4), CLM-1301 to 1325 the even harder claims (Week 2 Day 2), CLM-1901 the prompt injection (in the queue from Week 3 Day 2, making 26) and CLM-9001 the claim in Week 3 Day 4's first lab. Each set marks five claims as `tiny`. The handlers' answers are in `data/evals/`, which the claim agent must never see.
- **The scores:** accuracy needs the right decision and a payout within $1, and decision accuracy needs only the decision. The cost of mistakes is a business cost, separate from API cost: $1,500 for a wrongful decline, the payout for a wrongful approval, $50 for a needless referral and the difference for a wrong amount. The straight-through rate is the share of claims not referred, including approvals held for sign-off. A run of 25 claims is noisy, so one run can't show a small gain.
- **The $1,000 limit:** the agent can approve a claim over $1,000, but a handler signs off before it's paid. That's an approval held for sign-off, not a referral. How it works changes over the course:
  - Week 1 Day 3 to Week 2 Day 2: the backend refuses the agent's payment, and a handler's sign-off pays.
  - Week 2 Days 3 to 5: the claim graph pauses with `interrupt()`, and the sign-off resumes it so the agent pays.
  - Week 3 Days 2 and 3: there's no pause. A held approval ends the agent's work and the sign-off pays. The Gateway's Policy also refuses the agent's payments over $1,000.
  - From Week 3 Day 4: the pause returns, with Sign off (the app pays) or Send back with a note (the agent decides again).
- **Who can sign off:** all three handlers until Week 2 Day 5's build. From `week2day5-end`, only Dana can sign off over the limit, run improvement rounds or change settings.
- **The model in Ed's build:** GPT-6 Luna at `low` reasoning on Week 1 Day 3, DeepSeek V4.1 Flash at `low` from Week 1 Day 5 to Week 2 Day 3, and Luna at `low` from Week 2 Day 4. From Week 2 Day 5 the configuration starts on Luna at `none` and the improver can change it. `MODEL_NAME` in `.env` overrides the model, for example with `openrouter/free`.
- **Running the queue again:** a decided claim is final, so a rerun needs a reseed. That's `uv run -m backend.seed` until Week 2 Day 3, then `npm run seed`, which resets the queue in Supabase, along with the scoreboard and the configuration versions once they exist.
- **ADLC has two meanings,** numbered on the slides. The first is building agents with code, the agent development lifecycle: most of the course, and Week 3 Day 1. The second is building code with agents, which is Week 1 Day 3.
- **The agents:** keep yourself, the student's coding agent, apart from the product's agents: the UnderCover Agent that decides claims (the claim agent), the improver (Week 2 Day 5) and the UnderCover Copilot (Week 3 Day 5).

## The three weeks

Each week has a guide of its own, with the week's learning objectives and, for each day, what the slides teach, what the labs and the product build are for, what to watch out for, and corrections to the videos. When the student asks about a day, read its week's guide.

- **Week 1: Become an AI Engineer**, in `guides/for_agents/AGENT_GUIDE_WEEK1.md`: Path to FDE; Frontier LLMs & Agents; Coding Agents & ADLC; Open-Source, Local, Token Cost; Harness Engineering
- **Week 2: Become an AI Architect**, in `guides/for_agents/AGENT_GUIDE_WEEK2.md`: Agent Architecture, Evals, Observability; Agentic RAG, MCP, Memory; Durable State & Human in the Loop; Agent Swarms; Self-Improvement, RSI
- **Week 3: Become an AI FDE**, in `guides/for_agents/AGENT_GUIDE_WEEK3.md`: AI Solutions Architect; Security, Guardrails, API Gateways; Enterprise Context Layer & Integrations; Production Deployment; Capstone
