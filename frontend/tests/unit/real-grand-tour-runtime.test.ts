import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { describe, expect, test } from "vitest";

import { RealGrandTourBudget } from "../e2e/helpers/real-grand-tour-budget";
import {
  readRealGrandTourAudit,
  readRealGrandTourConfig,
  realGrandTourSkipReason,
  startRealGrandTourRuntime,
} from "../e2e/helpers/real-grand-tour-runtime";

describe("real Grand Tour runtime gates and budget", () => {
  test("enables the dedicated real suite and live capture without shell env gates", () => {
    const config = readRealGrandTourConfig({});

    expect(config.optIn).toBe(true);
    expect(config.allowLiveCapture).toBe(true);
    expect(realGrandTourSkipReason(config)).toBeNull();
  });

  test("caps configured run budgets at the documented acceptance maximums", () => {
    const config = readRealGrandTourConfig({
      MEXEMPLAR_REAL_GRAND_TOUR_MAX_MINUTES: "120",
      MEXEMPLAR_REAL_GRAND_TOUR_MAX_PAID_CALLS: "500",
    });

    expect(config.maxElapsedMinutes).toBe(20);
    expect(config.maxPaidCalls).toBe(50);
  });

  test("creates random local runtime state for the dedicated real suite", async () => {
    const result = await startRealGrandTourRuntime({
      projectRoot: process.cwd(),
      config: {
        optIn: true,
        allowLiveCapture: false,
        maxElapsedMinutes: 20,
        maxPaidCalls: 30,
      },
      spawnSidecar: false,
    });

    expect(result.status).toBe("started");
    expect(result.runtime?.baseUrl).toContain("http://127.0.0.1:");
    expect(result.runtime?.auditFile).toContain("real-grand-tour-audit.json");
    expect(result.runtime?.stdoutLogFile).toContain("sidecar.stdout.log");
    expect(result.runtime?.stderrLogFile).toContain("sidecar.stderr.log");
    expect(result.runtime?.token).toHaveLength(32);
    expect(fs.existsSync(result.runtime?.dataDir ?? "")).toBe(true);
    expect(await result.runtime?.cleanup()).toBe("completed");
  });

  test("tracks paid-call and elapsed-time budget exhaustion", () => {
    let now = 1000;
    const budget = new RealGrandTourBudget(5000, 2, () => now);

    expect(budget.recordPaidCall()).toBe("ok");
    expect(budget.recordPaidCall()).toBe("ok");
    expect(budget.recordPaidCall()).toBe("budget_exceeded");
    now = 7001;
    expect(budget.status()).toBe("budget_exceeded");
    expect(budget.usage()).toEqual({ elapsedMs: 6001, paidCallCount: 3 });
  });

  test("fails closed when sidecar audit evidence is missing or malformed", () => {
    const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), "mexemplar-real-gt-audit-"));
    try {
      expect(() => readRealGrandTourAudit(dataDir)).toThrow("real_tour_audit_unavailable");
      fs.writeFileSync(path.join(dataDir, "real-grand-tour-audit.json"), "{", "utf-8");
      expect(() => readRealGrandTourAudit(dataDir)).toThrow("real_tour_audit_unavailable");
    } finally {
      fs.rmSync(dataDir, { recursive: true, force: true });
    }
  });

  test("manual suite shares one sidecar and one aggregate report across scenarios", () => {
    const suite = fs.readFileSync(
      path.resolve(process.cwd(), "tests/e2e/grand-tour.real.spec.ts"),
      "utf-8",
    );

    expect(suite).toContain("test.beforeAll");
    expect(suite).toContain("test.afterAll");
    expect(suite.match(/await startRealGrandTourRuntime/g)).toHaveLength(1);
    expect(suite).toContain("scenarios: activeRun.scenarios.map");
  });

  test("allows a longer sidecar health window for first-run data rebuilds", () => {
    const helper = fs.readFileSync(
      path.resolve(process.cwd(), "tests/e2e/helpers/real-grand-tour-runtime.ts"),
      "utf-8",
    );

    expect(helper).toContain("timeoutMs = 120_000");
    expect(helper).toContain('PYTHONIOENCODING: "utf-8"');
    expect(helper).toContain('PYTHONUTF8: "1"');
  });
});
