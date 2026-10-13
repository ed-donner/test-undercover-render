import { expect, test } from "@playwright/test";

test("the header opens the Configuration page, with version 1 current", async ({
  page,
}) => {
  await page.goto("/");
  const nav = page.getByRole("navigation", { name: "Main" });
  await nav.getByRole("link", { name: "Configuration" }).click();
  await expect(page).toHaveURL("/configuration");
  await expect(
    nav.getByRole("link", { name: "Configuration" }),
  ).toHaveAttribute("aria-current", "page");

  const versions = page.getByRole("region", { name: "Versions" });
  const first = versions
    .getByRole("row")
    .filter({ hasText: "The claims team" });
  await expect(first.getByText("Current")).toBeVisible();

  await first.getByRole("link", { name: "Version 1" }).click();
  await expect(page).toHaveURL("/configuration/versions/1");
  const instructions = page.getByRole("region", { name: "Instructions" });
  await expect(
    instructions.getByText(/10\. How we work out your payment/),
  ).toBeVisible();
});

test("the old Instructions page lands on the Configuration page", async ({
  page,
}) => {
  await page.goto("/instructions");
  await expect(page).toHaveURL("/configuration");
});
