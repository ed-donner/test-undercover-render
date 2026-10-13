import { expect, test } from "@playwright/test";
import { HANDLERS } from "./handlers";

test("the queue lists every claim", async ({ page }) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Claims queue" }),
  ).toBeVisible();
  await expect(page.locator("tbody tr")).toHaveCount(26);
  for (const claimId of ["CLM-1025", "CLM-1901"]) {
    const row = page.getByRole("row").filter({ hasText: claimId });
    await expect(row.getByText("Waiting")).toBeVisible();
  }
});

test("a claim opens from the queue", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: "CLM-1001" }).click();
  await expect(page).toHaveURL("/claims/CLM-1001");
  await expect(page.getByText(/My flight home from Rome/)).toBeVisible();
  await expect(
    page.getByText("Hotel Aurelia Fiumicino", { exact: false }),
  ).toBeVisible();
  await expect(page.getByText("POL-2001")).toBeVisible();
});

test("signing out from the account menu lands on the sign-in page", async ({
  browser,
}) => {
  // A browser of its own, so signing out leaves the other tests signed in.
  const context = await browser.newContext({
    storageState: HANDLERS.dana.storage,
  });
  const page = await context.newPage();
  await page.goto("/scoreboard");
  const who = page.getByLabel("Signed in");
  await expect(who.getByText("Dana Whitfield")).toBeVisible();
  await expect(who.getByText("Senior Claims Handler")).toBeVisible();
  await who.getByRole("button", { name: "Account" }).click();
  await who.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL("/sign-in");
  await expect(
    page.getByRole("heading", { name: "Sign in", level: 1 }),
  ).toBeVisible();
  await page.goto("/scoreboard");
  await expect(page).toHaveURL("/sign-in");
  await context.close();
});
