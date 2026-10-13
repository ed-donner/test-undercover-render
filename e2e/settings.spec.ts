import { expect, test } from "@playwright/test";
import { HANDLERS } from "./handlers";

// Only this file changes the settings.

test("a senior handler changes the spending limit", async ({ page }) => {
  await page.goto("/settings");
  const limit = page
    .getByRole("group", { name: "Spending" })
    .getByLabel("Spending limit for each round");
  await limit.fill("0.75");
  const save = page.getByRole("button", { name: "Save", exact: true });
  const dialog = page.getByRole("dialog");

  await save.click();
  await expect(
    dialog.getByText("Spending limit for each round: $0.50 to $0.75"),
  ).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(page.getByText(/Not changed since/)).toBeVisible();

  await save.click();
  await dialog.getByRole("button", { name: "Save the settings" }).click();
  await expect(dialog).toBeHidden();
  await expect(page.getByText(/Last changed by Dana Whitfield/)).toBeVisible();

  await page.reload();
  await expect(limit).toHaveValue("0.75");
  await expect(page.getByText(/Last changed by Dana Whitfield/)).toBeVisible();
});

test("the appearance is kept in the browser", async ({ page }) => {
  await page.goto("/settings");
  const appearance = page.getByRole("group", { name: "Appearance" });
  await appearance.getByLabel("Dark").check();
  const root = page.locator("html");
  await expect(root).toHaveAttribute("data-theme", "dark");
  await expect(page.locator("body")).toHaveCSS(
    "background-color",
    "rgb(4, 35, 46)",
  );
  await page.reload();
  await expect(root).toHaveAttribute("data-theme", "dark");

  await page.emulateMedia({ colorScheme: "dark" });
  await appearance.getByLabel("Light").check();
  await expect(page.locator("body")).toHaveCSS(
    "background-color",
    "rgb(240, 244, 245)",
  );
});

test.describe("signed in as Marcus Oyelaran", () => {
  test.use({ storageState: HANDLERS.marcus.storage });

  test("the settings are read only, and say why", async ({ page }) => {
    await page.goto("/settings");
    await expect(
      page.getByText(
        "Only a handler who can sign off payouts over $1,000.00 can change the settings. Marcus Oyelaran can't.",
      ),
    ).toBeVisible();
    await expect(page.getByRole("button", { name: "Save" })).toHaveCount(0);
  });
});
