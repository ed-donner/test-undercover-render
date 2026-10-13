import { expect, it } from "vitest";
import {
  addOnName,
  date,
  duration,
  grade,
  initials,
  label,
  modelCost,
  money,
} from "./format";

it("takes a handler's initials from their first and last names", () => {
  expect(initials("Dana Whitfield")).toBe("DW");
  expect(initials("Mary Ann Okafor")).toBe("MO");
});

it("formats money in US dollars", () => {
  expect(money(1150)).toBe("$1,150.00");
  expect(money(0)).toBe("$0.00");
});

it("formats dates without shifting the day", () => {
  expect(date("2026-06-24")).toBe("Jun 24, 2026");
});

it("turns codes into labels", () => {
  expect(label("trip_delay")).toBe("Trip delay");
  expect(addOnName("electronics_plus")).toBe("Electronics Plus");
  expect(addOnName("new_add_on")).toBe("New add on");
});

it("formats model costs to four places, since they're often under a cent", () => {
  expect(modelCost(0.0125)).toBe("$0.0125");
  expect(modelCost(1.5)).toBe("$1.5000");
});

it("formats lengths of time in minutes and seconds", () => {
  expect(duration(41.4)).toBe("41 s");
  expect(duration(161)).toBe("2 min 41 s");
  expect(duration(0)).toBe("0 s");
  expect(duration(120)).toBe("2 min");
});

it("shows the judge's grade to two places", () => {
  expect(grade(2.2)).toBe("2.20");
  expect(grade(0)).toBe("0.00");
});
