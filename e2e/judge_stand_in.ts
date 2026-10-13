// Stands in for OpenRouter's Decisions endpoint in the end-to-end tests: it grades
// every explanation the same, a score of 2.2 with B the most likely level, the
// same grounds at 0.8 and the same section at 0.3, for $0.00002.
import { createServer } from "node:http";
import { reply } from "./stand_in.ts";

const ANSWER = {
  model: "typesafe/jev-1.13",
  answers: {
    grade: {
      type: "score",
      score: 2.2,
      probabilities: { "0": 0.05, "1": 0.1, "2": 0.5, "3": 0.35 },
    },
    same_grounds: { type: "noul", noul: 0.8 },
    same_section: { type: "noul", noul: 0.3 },
  },
  usage: { input_tokens: 400, output_tokens: 3, cost: 0.00002 },
};

createServer((request, response) => {
  request.resume();
  if (request.method === "POST" && request.url === "/api/alpha/decisions")
    reply(response, 200, ANSWER);
  else if (request.url === "/health") reply(response, 200, { status: "ok" });
  else reply(response, 404, { detail: "Not found" });
}).listen(Number(process.env.PORT), "127.0.0.1");
