import { describe, expect, it } from "vitest";

import { canContinueTask } from "../../src/api/assistantTasks";

describe("assistant task continuation", () => {
  it("allows a quota-exhausted task to continue after the user restores quota", () => {
    expect(
      canContinueTask({
        displayPhase: "paused",
        suspendReason: "quota_exhausted",
      }),
    ).toBe(true);
  });
});
