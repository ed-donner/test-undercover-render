import { generatePath } from "react-router";

// The routes of the pages, and the links to the pages that show one thing.
export const SIGN_IN = "/sign-in";
export const QUEUE = "/";
// The page the Configuration page took the place of, which leads there.
export const INSTRUCTIONS = "/instructions";
export const SCOREBOARD = "/scoreboard";
export const CONFIGURATION = "/configuration";
export const VERSION_PAGE = `${CONFIGURATION}/versions/:number`;
export const SETTINGS = "/settings";
export const IMPROVEMENT = "/improvement";
export const RECIPE_PAGE = `${IMPROVEMENT}/recipes/:number`;
export const CLAIM_PAGE = "/claims/:claimId";
export const EVALUATION_PAGE = `${SCOREBOARD}/:runId`;

export const claimPage = (claimId: string) =>
  generatePath(CLAIM_PAGE, { claimId });
export const evaluationPage = (runId: string) =>
  generatePath(EVALUATION_PAGE, { runId });
export const versionPage = (number: number) =>
  generatePath(VERSION_PAGE, { number: String(number) });
export const recipePage = (number: number) =>
  generatePath(RECIPE_PAGE, { number: String(number) });
