import { expect, test } from "@playwright/test";
import {
  createVersion,
  getProposal,
  getRound,
  nextStarted,
  recordChangeProposal,
  recordRecipeProposal,
  startRound,
  started,
  stopTheWork,
} from "./api";
import { HANDLERS } from "./handlers";

// Rounds of the improver started as Dana Whitfield and played out through the
// API as the agent would record them, with each review on the page recorded by
// the app and reaching the stand-in for the agent.

const RULE = "A stolen phone needs a police report.";
const INSTRUCTIONS = `# Working a claim\n\n${RULE}\n`;

test.afterEach(async ({ request }) => {
  await stopTheWork(request);
});

test("a round started on the page reaches the agent", async ({
  page,
  request,
}) => {
  await page.goto("/improvement");
  const before = (await started(request)).length;
  await page.getByRole("button", { name: "Start a round" }).click();
  const payload = await nextStarted(request, before);
  expect(payload).toEqual({
    operation: "work_round",
    round_id: expect.any(String),
  });
  const round = await getRound(request, String(payload.round_id));
  expect(round.status).toBe("open");
});

test("a change approved on the page reaches the agent, and the round moves on", async ({
  page,
  request,
}) => {
  const round = await startRound(request);
  const proposal = await recordChangeProposal(request, round, INSTRUCTIONS);
  await page.goto("/");
  await page
    .getByRole("navigation", { name: "Main" })
    .getByRole("link", { name: "Improvement" })
    .click();
  await expect(page).toHaveURL("/improvement");

  const waiting = page.getByRole("region", {
    name: "A change is waiting for approval",
  });
  await expect(waiting.getByText(RULE)).toBeVisible();
  await waiting.getByRole("button", { name: "Approve" }).click();
  const dialog = page.getByRole("dialog", { name: "Approve the change?" });
  await dialog.getByRole("button", { name: "Approve the change" }).click();
  await expect
    .poll(() => started(request))
    .toContainEqual({
      operation: "carry_round_on",
      round_id: round,
      proposal_id: proposal,
    });
  expect((await getProposal(request, round, proposal)).review).toBe("approved");

  await createVersion(request, round);
  await expect(
    page
      .getByRole("list", { name: "Where the round has got to" })
      .locator("[aria-current=step]"),
  ).toHaveText("Evaluations, 0 of 3");
});

test("a recipe rejected on the page records its reason and reaches the agent", async ({
  page,
  request,
}) => {
  const round = await startRound(request);
  const proposal = await recordRecipeProposal(request, round);
  await page.goto("/improvement");
  const waiting = page.getByRole("region", {
    name: "A new recipe is waiting for approval",
  });
  await waiting.getByRole("button", { name: "Reject" }).click();
  await waiting
    .getByLabel("Why reject it?")
    .fill("Keep the step that reads the wrong claims");
  await waiting.getByRole("button", { name: "Reject the recipe" }).click();
  await expect
    .poll(() => started(request))
    .toContainEqual({
      operation: "carry_round_on",
      round_id: round,
      proposal_id: proposal,
    });
  expect(await getProposal(request, round, proposal)).toMatchObject({
    review: "rejected",
    rejection_reason: "Keep the step that reads the wrong claims",
  });
});

test.describe("signed in as Marcus Oyelaran", () => {
  test.use({ storageState: HANDLERS.marcus.storage });

  test("a proposal waiting shows no buttons", async ({ page, request }) => {
    const round = await startRound(request);
    await recordChangeProposal(request, round, INSTRUCTIONS);
    await page.goto("/improvement");
    const waiting = page.getByRole("region", {
      name: "A change is waiting for approval",
    });
    await expect(waiting.getByText(RULE)).toBeVisible();
    await expect(
      waiting.getByText(
        "Only a handler who can sign off payouts over $1,000.00 can approve or reject the improver's proposals. Marcus Oyelaran can't.",
      ),
    ).toBeVisible();
    await expect(waiting.getByRole("button")).toHaveCount(0);
  });
});
