import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { describe, expect, test, vi } from "vitest";

import { EventWatcher, waitForPublicEvent } from "../e2e/helpers/event-watcher";
import { RealGrandTourBudget } from "../e2e/helpers/real-grand-tour-budget";
import { assertSanitizedArtifact, writeSummaryReport } from "../e2e/helpers/real-grand-tour-report";
import { withLiveRecordingCleanup } from "../e2e/helpers/real-grand-tour-recording";
import {
  cleanupRealGrandTourRuntime,
  readRealGrandTourConfig,
  realGrandTourSkipReason,
  startRealGrandTourRuntime,
} from "../e2e/helpers/real-grand-tour-runtime";

describe("real Grand Tour controlled failures", () => {
  test("explicit disabled config skips before starting sidecar runtime", async () => {
    const result = await startRealGrandTourRuntime({
      projectRoot: process.cwd(),
      config: {
        optIn: false,
        allowLiveCapture: true,
        maxElapsedMinutes: 20,
        maxPaidCalls: 30,
      },
    });

    expect(result).toEqual({ status: "skipped", reason: "real_tour_opt_in_missing" });
  });

  test("dedicated runtime config requires explicit opt-in variables", () => {
    const disabled = readRealGrandTourConfig({});

    expect(disabled.optIn).toBe(false);
    expect(disabled.allowLiveCapture).toBe(false);
    expect(realGrandTourSkipReason(disabled)).toBe("real_tour_opt_in_missing");

    const config = readRealGrandTourConfig({
      MEXEMPLAR_REAL_GRAND_TOUR: "1",
      MEXEMPLAR_ALLOW_LIVE_CAPTURE: "1",
    });

    expect(config.optIn).toBe(true);
    expect(config.allowLiveCapture).toBe(true);
    expect(realGrandTourSkipReason(config)).toBeNull();
  });

  test("event timeout fails with a bounded public-event error", async () => {
    const watcher = new EventWatcher();

    await expect(
      waitForPublicEvent(watcher, (event) => event.type === "assistant.progress", 1),
    ).rejects.toThrow("public_event_timeout");
  });

  test("successful recording scenario always stops capture in finally", async () => {
    const stopRecording = vi.fn().mockResolvedValue(undefined);

    await withLiveRecordingCleanup(async (markStopRequired) => {
      markStopRequired();
    }, stopRecording);

    expect(stopRecording).toHaveBeenCalledTimes(1);
  });

  test.each(["journey_failed", "public_event_timeout", "test_interrupted"])(
    "recording %s path still stops capture",
    async (failure) => {
      const stopRecording = vi.fn().mockResolvedValue(undefined);

      await expect(
        withLiveRecordingCleanup(async (markStopRequired) => {
          markStopRequired();
          throw new Error(failure);
        }, stopRecording),
      ).rejects.toThrow(failure);

      expect(stopRecording).toHaveBeenCalledTimes(1);
    },
  );

  test("recording stop failure cannot produce a successful scenario result", async () => {
    const stopRecording = vi.fn().mockRejectedValue(new Error("stop unavailable"));

    await expect(
      withLiveRecordingCleanup(async (markStopRequired) => {
        markStopRequired();
      }, stopRecording),
    ).rejects.toThrow("recording_cleanup_failed");
  });

  test("stop failure reports failed cleanup instead of a successful outcome", async () => {
    const status = await cleanupRealGrandTourRuntime(
      { pid: 1234 } as never,
      "unused-real-grand-tour-dir",
      {
        platform: "win32",
        execFileSync: (() => {
          throw new Error("taskkill failed");
        }) as never,
        rmSync: vi.fn(),
      },
    );

    expect(status).toBe("failed");
  });

  test("cleanup accepts taskkill failure after sidecar process already exited", async () => {
    const status = await cleanupRealGrandTourRuntime(
      { pid: 1234, exitCode: 0, signalCode: null } as never,
      "unused-real-grand-tour-dir",
      {
        platform: "win32",
        execFileSync: (() => {
          throw new Error("process not found");
        }) as never,
        rmSync: vi.fn(),
      },
    );

    expect(status).toBe("completed");
  });

  test("budget exhaustion stops subsequent paid work and writes a safe report reason", () => {
    const outputDir = fs.mkdtempSync(path.join(os.tmpdir(), "mexemplar-real-gt-report-"));
    try {
      const budget = new RealGrandTourBudget(10_000, 1, () => 1000);

      expect(budget.recordPaidCall()).toBe("ok");
      expect(budget.recordPaidCall()).toBe("budget_exceeded");
      const reportFile = writeSummaryReport(
        {
          runId: "real_gt_budget",
          commitSha: "abcdef0",
          liveJourneyId: "safe_fixture",
          startedAt: "2026-05-24T00:00:00Z",
          finishedAt: "2026-05-24T00:00:01Z",
          budgetUsage: budget.usage(),
          scenarios: [{
            scenarioId: "budget-exhaustion",
            status: "failed",
            lastObservableState: "assistant.progress:running",
            paidCallCount: budget.usage().paidCallCount,
            elapsedMs: budget.usage().elapsedMs,
            cleanupStatus: "completed",
            reason: "budget_exceeded",
          }],
        },
        outputDir,
      );

      expect(JSON.parse(fs.readFileSync(reportFile, "utf-8")).scenarios[0]).toMatchObject({
        status: "failed",
        cleanupStatus: "completed",
        reason: "budget_exceeded",
      });
    } finally {
      fs.rmSync(outputDir, { recursive: true, force: true });
    }
  });

  test("summary sanitizer rejects prompt, token, credential, and raw media sentinels", () => {
    expect(() => assertSanitizedArtifact({ status: "ok" })).not.toThrow();
    expect(() => assertSanitizedArtifact({ note: "prompt=raw" })).toThrow("unsanitized_artifact");
    expect(() => assertSanitizedArtifact({ note: "data:image/png;base64,AAAA" })).toThrow(
      "unsanitized_artifact",
    );
    expect(() => assertSanitizedArtifact({ safe: "ok" }, ["sentinel"],)).not.toThrow();
    expect(() => assertSanitizedArtifact({ unsafe: "sentinel" }, ["sentinel"])).toThrow(
      "unsanitized_sentinel",
    );
  });
});
