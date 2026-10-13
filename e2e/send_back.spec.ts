import { expect, test } from "@playwright/test";
import { decide, payClaim, resumes, startClaim, takeClaim } from "./api";

// A senior handler sends a held decision back with a note on the claim page,
// and the test, standing in for the agent, takes the claim and decides again.

const NOTE =
  "Meridian Air has already paid 350 dollars for the lost bag, so take it off.";

test("a held claim sent back with a note is decided again", async ({
  page,
  request,
}) => {
  await startClaim(request, "CLM-1022", "e2e-8");
  await decide(request, "CLM-1022", {
    decision: "approve",
    payout: 1350,
    section: "Section 5, Baggage and Personal Effects",
    reason: "The loss is covered.",
  });
  const resumed = await resumes(request);

  await page.goto("/claims/CLM-1022");
  const heading = page.locator(".page-header");
  await expect(heading.getByText("Waiting for sign-off")).toBeVisible();
  await page.getByRole("button", { name: "Send back", exact: true }).click();
  await page.getByLabel("What should the agent look at again?").fill(NOTE);
  await page.getByRole("button", { name: "Send back to the agent" }).click();

  await expect(heading.getByText("Sent back")).toBeVisible();
  const sentBack = page.getByRole("region", { name: "Decisions sent back" });
  await expect(sentBack.getByText(NOTE)).toBeVisible();
  await expect(sentBack.locator(".payout")).toHaveText("$1,350.00");
  await expect(
    sentBack.getByText(/^Sent back by Dana Whitfield at /),
  ).toBeVisible();
  await expect(page.locator(".steps > li").last()).toContainText(
    `Handler's note Sent back by Dana Whitfield: ${NOTE}`,
  );
  expect(await resumes(request)).toEqual([...resumed, "CLM-1022"]);

  await takeClaim(request, "CLM-1022", null);
  await decide(request, "CLM-1022", {
    decision: "approve",
    payout: 900,
    section: "Section 5, Baggage and Personal Effects",
    reason: "The loss is covered, less what the airline paid.",
  });
  await payClaim(request, "CLM-1022", 900);
  const decision = page.getByRole("region", { name: "Decision", exact: true });
  await expect(decision.getByText("Paid $900.00")).toBeVisible();
  await expect(heading.getByText("Decided")).toBeVisible();
  const column = page.locator(".claim-layout .column").last();
  await expect(column.getByRole("heading", { level: 2 })).toHaveText([
    "Decision",
    "Decisions sent back",
    "Agent at work",
  ]);
});
