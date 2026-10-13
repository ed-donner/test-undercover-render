import { type Locator, type Page, expect, test } from "@playwright/test";
import { decide, nextStarted, startClaim, started, stopTheWork } from "./api";

// The Copilot's sidebar on every signed-in page, driving a stand-in for the
// Copilot, which plays scripted turns through the backend with the handler's
// sign-in.

test.afterEach(async ({ request }) => {
  await stopTheWork(request);
});

const sidebar = (page: Page) =>
  page.getByRole("complementary", { name: "Copilot" });

async function ask(page: Page, message: string) {
  const box = sidebar(page).getByRole("textbox", { name: "Ask the Copilot" });
  await box.fill(message);
  await box.press("Enter");
}

async function boxOf(locator: Locator) {
  const box = await locator.boundingBox();
  if (!box) throw new Error("Not on the page");
  return box;
}

const PAGES = [
  "/",
  "/claims/CLM-1002",
  "/scoreboard",
  "/improvement",
  "/configuration",
  "/settings",
];

test("the sidebar is open beside every page, and stays collapsed once collapsed", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  for (const path of PAGES) {
    await page.goto(path);
    await expect(sidebar(page)).toBeVisible();
    const main = await boxOf(page.getByRole("main"));
    const copilot = await boxOf(sidebar(page));
    expect(copilot.x).toBeGreaterThanOrEqual(main.x + main.width);
  }
  await sidebar(page)
    .getByRole("button", { name: "Collapse the Copilot" })
    .click();
  await page.reload();
  await expect(
    page.getByRole("button", { name: "Open the Copilot" }),
  ).toBeVisible();
  await expect(sidebar(page)).toHaveCount(0);
  await page.getByRole("button", { name: "Open the Copilot" }).click();
  await expect(sidebar(page)).toBeVisible();
});

test("on a narrow window the sidebar opens over the page, below the header, and Escape collapses it", async ({
  page,
}) => {
  await page.setViewportSize({ width: 800, height: 800 });
  await page.goto("/");
  const main = await boxOf(page.getByRole("main"));
  const header = await boxOf(page.getByRole("banner"));
  const copilot = await boxOf(sidebar(page));
  expect(copilot.x).toBeLessThan(main.x + main.width);
  expect(copilot.x + copilot.width).toBeLessThanOrEqual(800);
  expect(copilot.y).toBeGreaterThanOrEqual(header.y + header.height);
  const who = page.getByLabel("Signed in");
  await who.getByRole("button", { name: "Account" }).click();
  // A click lands only on what's on top, so the sidebar leaves the menu clear.
  await who.getByRole("link", { name: "Settings" }).click();
  await expect(page).toHaveURL("/settings");
  await sidebar(page).getByRole("button", { name: "New conversation" }).focus();
  await page.keyboard.press("Escape");
  await expect(sidebar(page)).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Open the Copilot" }),
  ).toBeFocused();
});

test("the Copilot's steps show as cards, then its answer, and the page shows its action", async ({
  page,
  request,
}) => {
  await page.goto("/");
  const before = (await started(request)).length;
  await ask(page, "What needs me today?");
  const copilot = sidebar(page);
  const lookup = copilot.locator(".card", { hasText: "read_section" });
  await expect(lookup).toContainText("policy_wording 3");
  await lookup.getByRole("button").click();
  await expect(lookup).toContainText("Policy administration, owned by");
  const action = copilot.locator(".card", { hasText: "start_dispatch" });
  await expect(action.getByLabel("Done")).toBeVisible();
  await expect(action).toHaveClass(/card-action/);
  const refused = copilot.locator(".card", { hasText: "send_back_claim" });
  await expect(refused.getByText("Refused")).toBeVisible();
  await expect(refused).toContainText(
    "Claim CLM-1009 is not waiting for sign-off",
  );
  await expect(copilot.getByRole("table")).toBeVisible();
  await expect(copilot.getByText("3 model calls, $0.0021")).toBeVisible();
  expect(await nextStarted(request, before)).toMatchObject({
    operation: "work_run",
  });
  await expect(
    page.getByRole("region", { name: "Dispatch" }).getByText("Running"),
  ).toBeVisible();
  await copilot.getByRole("link", { name: "CLM-1009" }).first().click();
  await expect(page).toHaveURL("/claims/CLM-1009");
});

async function holdForSignOff(
  request: Parameters<typeof startClaim>[0],
  claimId: string,
) {
  await startClaim(request, claimId, `e2e-copilot-${claimId}`);
  await decide(request, claimId, {
    decision: "approve",
    payout: 1350,
    section: "Section 7, Emergency Medical",
    reason: "The hospital bill is covered under section 7.",
  });
}

test("a sign-off waits for Dana's confirmation, even after a reload, and pays once she confirms", async ({
  page,
  request,
}) => {
  await holdForSignOff(request, "CLM-1008");
  await page.goto("/");
  await ask(page, "Sign off CLM-1008");
  const card = page.getByRole("region", { name: "Confirm the sign-off" });
  await expect(card.getByRole("link", { name: "CLM-1008" })).toBeVisible();
  await expect(card.getByText("Dorothy Gale")).toBeVisible();
  await expect(card.getByText("$1,350.00")).toBeVisible();
  await expect(
    card.getByText("The hospital bill is covered under section 7."),
  ).toBeVisible();
  const box = sidebar(page).getByRole("textbox", { name: "Ask the Copilot" });
  await expect(box).toBeDisabled();
  await expect(box).toHaveAttribute(
    "placeholder",
    "Answer the confirmation first",
  );
  await page.reload();
  await expect(card.getByText("$1,350.00")).toBeVisible();
  await card.getByRole("button", { name: "Sign off and pay" }).click();
  await expect(card.getByRole("status")).toHaveText("Signed off and paid");
  await page.goto("/claims/CLM-1008");
  await expect(
    page.getByText(/^Paid \$1,350\.00, signed off by Dana Whitfield at /),
  ).toBeVisible();
});

test("Cancel leaves the claim held, and the answer says nothing was signed off", async ({
  page,
  request,
}) => {
  await holdForSignOff(request, "CLM-1011");
  await page.goto("/");
  await ask(page, "Sign off CLM-1011");
  const card = page.getByRole("region", { name: "Confirm the sign-off" });
  await card.getByRole("button", { name: "Cancel" }).click();
  await expect(card.getByRole("status")).toHaveText("Canceled");
  await expect(
    sidebar(page).getByText(
      "I haven't signed off CLM-1011. What would you like to do instead?",
    ),
  ).toBeVisible();
  await page.goto("/claims/CLM-1011");
  await expect(
    page.locator(".page-header").getByText("Waiting for sign-off"),
  ).toBeVisible();
});

test("the earlier conversations hold each by its first question, and open it", async ({
  page,
}) => {
  await page.goto("/");
  await ask(page, "How did the latest dispatch go?");
  const copilot = sidebar(page);
  await expect(copilot.getByRole("table")).toBeVisible();
  await copilot.getByRole("button", { name: "New conversation" }).click();
  await expect(copilot.getByText("Hello, Dana.")).toBeVisible();
  await copilot.getByRole("button", { name: "Earlier conversations" }).click();
  const earlier = copilot.getByRole("button", {
    name: /How did the latest dispatch go\?/,
  });
  await expect(earlier.first()).toBeVisible();
  await earlier.first().click();
  await expect(
    copilot.getByText("How did the latest dispatch go?").first(),
  ).toBeVisible();
  await expect(copilot.getByRole("table")).toBeVisible();
});
