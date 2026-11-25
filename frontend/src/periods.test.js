import test from "node:test";
import assert from "node:assert/strict";
import { moscowDate, periodRange } from "./periods.js";

test("Monday begins in Moscow while UTC is still Sunday", () => {
  const now = new Date("2026-11-15T21:00:00Z");
  assert.equal(moscowDate(now), "2026-11-16");
  const range = periodRange("week", undefined, now);
  assert.equal(range.from, "2026-11-16T00:00:00+03:00");
  assert.equal(range.to, "2026-11-23T00:00:00+03:00");
});
test("Sunday belongs to the same Monday–Sunday week", () => {
  assert.equal(periodRange("selected", "2026-11-22").start, "2026-11-16");
});
test("previous week crosses the year boundary", () => {
  const range = periodRange("previous", undefined, new Date("2027-01-01T12:00:00Z"));
  assert.equal(range.start, "2026-12-21");
  assert.equal(range.end, "2026-12-28");
});
test("calendar day and leap-year month", () => {
  assert.equal(periodRange("today", undefined, new Date("2026-11-19T20:00:00Z")).from, "2026-11-19T00:00:00+03:00");
  assert.equal(periodRange("month", undefined, new Date("2028-02-29T12:00:00Z")).end, "2028-03-01");
});
