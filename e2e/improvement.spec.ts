import { expect, test } from "@playwright/test";
import {
  createRound,
  createVersion,
  finishOpenRound,
  recordChangeProposal,
  recordRecipeProposal,
  recordReview,
  reviews,
  started,
} from "./api";
import { HANDLERS } from "./handlers";

// Rounds of the improver played out through the API as the agent's service
// would record them, with each review on the page reaching the stand-in for the
// agent's service.

const RULE = "A stolen phone needs a police report.";
const DANA = HANDLERS.dana.handler_id;
const INSTRUCTIONS = `# Working a claim\n\n${RULE}\n`;

test.afterEach(async ({ request }) => {
  await finishOpenRound(request);
});

test("a round started on the page reaches the agent's service", async ({
  page,
  request,
}) => {
  await page.goto("/improvement");
  await page.getByRole("button", { name: "Start a round" }).click();
  await expect
    .poll(() => started(request))
    .toContainEqual({ path: "/api/rounds", body: { handler_id: DANA } });
});

test("a change approved on the page reaches the agent's service, and the round moves on", async ({
  page,
  request,
}) => {
  const round = await createRound(request);
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
    .poll(() => reviews(request))
    .toContainEqual({
      path: `/api/rounds/${round}/proposals/${proposal}/review`,
      body: { review: "approved", handler_id: DANA, reason: "" },
    });

  await recordReview(request, round, proposal, "approved");
  await createVersion(request, round);
  await expect(
    page
      .getByRole("list", { name: "Where the round has got to" })
      .locator("[aria-current=step]"),
  ).toHaveText("Evaluations, 0 of 3");
});

test("a recipe rejected on the page sends its reason to the agent's service", async ({
  page,
  request,
}) => {
  const round = await createRound(request);
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
    .poll(() => reviews(request))
    .toContainEqual({
      path: `/api/rounds/${round}/proposals/${proposal}/review`,
      body: {
        review: "rejected",
        handler_id: DANA,
        reason: "Keep the step that reads the wrong claims",
      },
    });
});

test.describe("signed in as Marcus Oyelaran", () => {
  test.use({ storageState: HANDLERS.marcus.storage });

  test("a proposal waiting shows no buttons", async ({ page, request }) => {
    const round = await createRound(request);
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
