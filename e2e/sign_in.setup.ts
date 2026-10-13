import { expect, test as setup } from "@playwright/test";
import { HANDLERS, TEST_PASSWORD } from "./handlers";

// Signs in on the sign-in page as each handler the tests use, and keeps each
// browser's storage, with its session, for the tests.
for (const handler of Object.values(HANDLERS)) {
  setup(`sign in as ${handler.name}`, async ({ page }) => {
    await page.goto("/");
    await expect(page).toHaveURL("/sign-in");
    await page.getByLabel("Email").fill(handler.email);
    await page.getByLabel("Password").fill(TEST_PASSWORD);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(
      page.getByLabel("Signed in").getByText(handler.name),
    ).toBeVisible();
    await page.context().storageState({ path: handler.storage });
  });
}
