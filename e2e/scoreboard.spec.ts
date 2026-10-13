import { expect, test } from "@playwright/test";
import type { DecisionKind } from "../dashboard/src/api";
import {
  createEvaluation,
  finishRun,
  payClaim,
  decide,
  recordModelCall,
  recordWorkTime,
  startClaim,
} from "./api";

// This test stands in for the agent's service and its claim agents, playing
// out an evaluation of the held-out set's tiny claims through the API, and
// checks the Scoreboard and the evaluation's page. Only this file records
// evaluations, and its copies are its own.

test("the Scoreboard shows an evaluation played out through the API", async ({
  page,
  request,
}) => {
  const { run_id, number, claims } = await createEvaluation(
    request,
    "held_out",
    true,
    5,
  );
  const copyOf = (original: string) => `${original}-E${String(number)}`;
  expect(claims).toHaveLength(5);

  for (const { claim_id } of claims) {
    await startClaim(request, claim_id, `e2e-${claim_id}`);
    await recordModelCall(request, claim_id, run_id, 0.0125);
    await recordWorkTime(request, claim_id, run_id, 40);
  }
  const decideCopy = (
    original: string,
    decision: DecisionKind,
    payout: number,
  ) =>
    decide(request, copyOf(original), {
      decision,
      payout,
      section: "Section 5",
      reason: `The agent's reason on ${original}.`,
    });
  const pay = (original: string, amount: number) =>
    payClaim(request, copyOf(original), amount);
  await decideCopy("CLM-1104", "approve", 250);
  await pay("CLM-1104", 250);
  await decideCopy("CLM-1106", "approve", 300);
  await pay("CLM-1106", 300);
  await decideCopy("CLM-1110", "refer", 0);
  await decideCopy("CLM-1112", "approve", 1200);
  await finishRun(request, run_id);

  await page.goto("/scoreboard");
  const evaluation = `Evaluation #${String(number)}`;
  const row = page.getByRole("row", { name: new RegExp(`^${evaluation} `) });
  await expect(row.getByText("Finished")).toBeVisible();
  for (const shown of [
    "80%",
    "40%",
    "$620.00",
    "60%",
    "1.76",
    "$0.0125",
    "40 s",
  ])
    await expect(row.getByText(shown, { exact: true })).toBeVisible();
  await expect(row.getByRole("cell").last()).toHaveText(/^\d+ s$/);

  await row.getByRole("link", { name: evaluation }).click();
  await expect(page).toHaveURL(`/scoreboard/${run_id}`);
  await expect(page.getByText(/judge cost/)).toContainText(
    "judge cost $0.0001",
  );
  const scored = page.getByRole("region", { name: "Claims" });
  for (const original of ["CLM-1104", "CLM-1106", "CLM-1110", "CLM-1112"]) {
    const row = scored.getByRole("row", { name: new RegExp(copyOf(original)) });
    await expect(row.getByText("B", { exact: true })).toBeVisible();
    await expect(row.getByText("2.20", { exact: true })).toBeVisible();
  }
  const undecided = scored.getByRole("row", {
    name: new RegExp(copyOf("CLM-1114")),
  });
  await expect(undecided.getByText("F", { exact: true })).toBeVisible();
  await expect(undecided.getByText("0.00", { exact: true })).toBeVisible();
  for (const original of ["CLM-1106", "CLM-1112", "CLM-1114"])
    await expect(
      scored
        .getByRole("row", { name: new RegExp(copyOf(original)) })
        .getByText("Miss"),
    ).toBeVisible();
  for (const original of ["CLM-1104", "CLM-1110"])
    await expect(
      scored
        .getByRole("row", { name: new RegExp(copyOf(original)) })
        .getByText("Right"),
    ).toBeVisible();
  await expect(
    scored.getByRole("row", { name: new RegExp(copyOf("CLM-1114")) }),
  ).toContainText("No decision");

  await scored.getByRole("link", { name: copyOf("CLM-1112") }).click();
  await expect(page).toHaveURL(`/claims/${copyOf("CLM-1112")}`);
  await expect(
    page.getByText("A copy of CLM-1112 in an evaluation"),
  ).toBeVisible();
  await expect(
    page.getByText(
      "Held for sign-off. In an evaluation this counts as finished, and a copy can't be signed off.",
    ),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Sign off" })).toHaveCount(0);
});
