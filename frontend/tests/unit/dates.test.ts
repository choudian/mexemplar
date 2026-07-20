import { describe, expect, test } from "vitest";

import { parseApiDateTime } from "../../src/utils/dates";

describe("parseApiDateTime", () => {
  test("treats a timezone-less backend datetime as UTC", () => {
    expect(parseApiDateTime("2026-07-21T07:00:00")?.toISOString()).toBe(
      "2026-07-21T07:00:00.000Z",
    );
  });

  test("preserves an explicit timezone offset", () => {
    expect(parseApiDateTime("2026-07-21T15:00:00+08:00")?.toISOString()).toBe(
      "2026-07-21T07:00:00.000Z",
    );
  });

  test("returns null for empty or invalid values", () => {
    expect(parseApiDateTime(null)).toBeNull();
    expect(parseApiDateTime("not-a-date")).toBeNull();
  });
});
