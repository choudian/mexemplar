import crypto from "node:crypto";
import { execFileSync } from "node:child_process";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { EventWatcher, streamPublicUiEvents, waitForPublicEvent } from "./helpers/event-watcher";
import { writeSummaryReport, type ScenarioReport } from "./helpers/real-grand-tour-report";
import { withLiveRecordingCleanup } from "./helpers/real-grand-tour-recording";
import {
  readRealGrandTourAudit,
  readRealGrandTourConfig,
  realGrandTourSkipReason,
  startRealGrandTourRuntime,
  waitForRealGrandTourHealth,
  type RealGrandTourAuditSnapshot,
  type RealGrandTourRuntime,
} from "./helpers/real-grand-tour-runtime";
import { RealGrandTourSafeJourneyPage, SAFE_LIVE_JOURNEY } from "./pages/real-grand-tour-safe-journey";

const config = readRealGrandTourConfig();
const skipReason = realGrandTourSkipReason(config);
const projectRoot = path.resolve(process.cwd(), "..");
const commitSha = execFileSync("git", ["rev-parse", "--short", "HEAD"], {
  cwd: projectRoot,
  encoding: "utf8",
}).trim();

type RunRuntime = {
  sidecar: RealGrandTourRuntime;
  runId: string;
  scenarios: ScenarioReport[];
  evidenceFailures: Set<string>;
  startedAt: string;
};

type ScenarioRuntime = {
  watcher: EventWatcher;
  eventAbort: AbortController;
  startedAtMs: number;
  paidCallsAtStart: number;
};

const maxRunMs = config.maxElapsedMinutes * 60 * 1000;
let run: RunRuntime | null = null;
let scenario: ScenarioRuntime | null = null;

function observableState(watcher: EventWatcher): string {
  const state = watcher.lastObservableState;
  if (!state) return "none";
  return `${state.type}:${state.status ?? state.stage ?? "observed"}`;
}

function runElapsedMs(activeRun: RunRuntime): number {
  return Math.max(0, Date.now() - Date.parse(activeRun.startedAt));
}

function addOnce(items: string[], value: string): void {
  if (!items.includes(value)) items.push(value);
}

async function injectRuntime(page: Page, runtime: RealGrandTourRuntime): Promise<void> {
  await page.addInitScript(
    ({ baseUrl, port, token }) => {
      window.__MEXEMPLAR_E2E_SIDECAR__ = { baseUrl, port, sessionToken: token };
    },
    { baseUrl: runtime.baseUrl, port: runtime.port, token: runtime.token },
  );
}

async function stopLiveRecording(page: Page, watcher: EventWatcher): Promise<void> {
  await page.getByRole("button", { name: "停止录制" }).click();
  await waitForPublicEvent(
    watcher,
    (event) => event.type === "recording.progress" && (
      event.payload.status === "stopped" || event.payload.status === "completed"
    ),
    60_000,
  );
}

test.describe("Manual Real Grand Tour", () => {
  test.skip(Boolean(skipReason), skipReason ?? "real_tour_enabled");

  test.beforeAll(async () => {
    const result = await startRealGrandTourRuntime({ projectRoot, config });
    if (result.status !== "started" || !result.runtime) {
      throw new Error(result.reason ?? "real_tour_runtime_unavailable");
    }
    try {
      await waitForRealGrandTourHealth(result.runtime);
      readRealGrandTourAudit(result.runtime.dataDir);
    } catch (error) {
      await result.runtime.cleanup();
      throw error;
    }
    run = {
      sidecar: result.runtime,
      runId: `real_gt_${crypto.randomUUID()}`,
      scenarios: [],
      evidenceFailures: new Set<string>(),
      startedAt: new Date().toISOString(),
    };
  });

  test.beforeEach(async ({ page }) => {
    const activeRun = run;
    if (!activeRun) throw new Error("real_tour_runtime_unavailable");
    const audit = readRealGrandTourAudit(activeRun.sidecar.dataDir);
    await injectRuntime(page, activeRun.sidecar);
    const watcher = new EventWatcher();
    const eventAbort = new AbortController();
    void streamPublicUiEvents(
      activeRun.sidecar.baseUrl,
      activeRun.sidecar.token,
      watcher,
      eventAbort.signal,
    ).catch(() => {
      // A scenario waiting for an event will fail with a bounded timeout.
    });
    scenario = {
      watcher,
      eventAbort,
      startedAtMs: Date.now(),
      paidCallsAtStart: audit.paidCallCount,
    };
    if (runElapsedMs(activeRun) >= maxRunMs) {
      throw new Error("real_tour_budget_exceeded:elapsed_time");
    }
  });

  test.afterEach(async ({ page }, testInfo) => {
    void page;
    const activeRun = run;
    const activeScenario = scenario;
    if (!activeRun || !activeScenario) return;
    activeScenario.eventAbort.abort();
    const evidenceFailures: string[] = [];
    let audit: RealGrandTourAuditSnapshot | null = null;
    try {
      audit = readRealGrandTourAudit(activeRun.sidecar.dataDir);
    } catch {
      evidenceFailures.push("audit_unavailable");
    }
    if (audit?.credentialMutationCount) {
      evidenceFailures.push("credential_mutation_detected");
    }
    if (audit?.budgetExceeded) {
      evidenceFailures.push("budget_exceeded");
    }
    if (runElapsedMs(activeRun) > maxRunMs) {
      evidenceFailures.push("budget_exceeded");
    }
    evidenceFailures.forEach((failure) => activeRun.evidenceFailures.add(failure));
    const status =
      testInfo.status === "passed" ? "passed" : testInfo.status === "skipped" ? "skipped" : "failed";
    const elapsedMs = Math.max(0, Date.now() - activeScenario.startedAtMs);
    const paidCallCount = Math.max(0, (audit?.paidCallCount ?? activeScenario.paidCallsAtStart) - activeScenario.paidCallsAtStart);
    activeRun.scenarios.push({
      scenarioId: testInfo.title,
      status: evidenceFailures.length > 0 ? "failed" : status,
      lastObservableState: observableState(activeScenario.watcher),
      paidCallCount,
      elapsedMs,
      cleanupStatus: "pending",
      ...(evidenceFailures.length > 0 ? { reason: evidenceFailures.join(",") } : {}),
      ...(evidenceFailures.length === 0 && status === "failed" ? { reason: "scenario_failed" } : {}),
    });
    scenario = null;
  });

  test.afterAll(async () => {
    const activeRun = run;
    if (!activeRun) return;
    const evidenceFailures = [...activeRun.evidenceFailures];
    let audit: RealGrandTourAuditSnapshot | null = null;
    try {
      audit = readRealGrandTourAudit(activeRun.sidecar.dataDir);
    } catch {
      addOnce(evidenceFailures, "audit_unavailable");
    }
    if (audit?.credentialMutationCount) {
      addOnce(evidenceFailures, "credential_mutation_detected");
    }
    if (audit?.budgetExceeded || runElapsedMs(activeRun) > maxRunMs) {
      addOnce(evidenceFailures, "budget_exceeded");
    }
    const cleanupStatus = await activeRun.sidecar.cleanup();
    if (cleanupStatus !== "completed") {
      addOnce(evidenceFailures, "cleanup_failed");
    }
    writeSummaryReport(
      {
        runId: activeRun.runId,
        commitSha,
        liveJourneyId: SAFE_LIVE_JOURNEY.liveJourneyId,
        startedAt: activeRun.startedAt,
        finishedAt: new Date().toISOString(),
        budgetUsage: {
          elapsedMs: runElapsedMs(activeRun),
          paidCallCount: audit?.paidCallCount ?? 0,
        },
        credentialMutationCount: audit?.credentialMutationCount ?? 0,
        scenarios: activeRun.scenarios.map((item) => ({ ...item, cleanupStatus })),
      },
      path.resolve(process.cwd(), "test-results", "real-grand-tour"),
    );
    run = null;
    if (evidenceFailures.length > 0) {
      throw new Error(`real_tour_evidence_failed:${evidenceFailures.join(",")}`);
    }
  });

  test("readiness", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("status")).toContainText(/已就绪|ready/i, { timeout: 60_000 });
    await expect(page.getByRole("button", { name: /AI 助手|AI Assistant/ })).toBeVisible();
  });

  test("assistant-real-reply", async ({ page }, testInfo) => {
    testInfo.annotations.push({ type: "cost-warning", description: "This scenario performs a real paid model call." });
    await page.goto("/");
    await page.getByRole("button", { name: /AI 助手|AI Assistant/ }).click();
    await page.getByLabel("输入消息").fill("Use one short non-sensitive sentence to confirm readiness.");
    await page.getByRole("button", { name: "发送" }).click();
    await waitForPublicEvent(
      scenario!.watcher,
      (event) => event.type === "assistant.progress" && event.payload.status !== "running",
      120_000,
    );
    await expect(page.locator(".assistant-message[data-role='assistant']").last()).not.toHaveText("", {
      timeout: 120_000,
    });
  });

  test("teaching-live-recording", async ({ browser, page }, testInfo) => {
    test.skip(!config.allowLiveCapture, "live_capture_opt_in_missing");
    testInfo.annotations.push({
      type: "privacy-warning",
      description: "Live capture may record visible desktop or browser content; use only the fixed safe fixture.",
    });
    await page.goto("/");
    await page.getByRole("button", { name: /技能教学/ }).click();
    await page.getByRole("button", { name: "开始" }).first().click();
    await page.getByRole("button", { name: "开始录制" }).click();
    await expect(page.getByRole("alertdialog", { name: "录制隐私确认" })).toContainText(
      /可见内容可能会被记录/,
    );
    await withLiveRecordingCleanup(
      async (markStopRequired) => {
        markStopRequired();
        await page.getByRole("button", { name: "确认并开始录制" }).click();
        await waitForPublicEvent(
          scenario!.watcher,
          (event) => event.type === "recording.progress" && event.payload.status === "recording",
        );

        const fixtureContext = await browser.newContext();
        try {
          const fixturePage = await fixtureContext.newPage();
          const journey = new RealGrandTourSafeJourneyPage(fixturePage);
          await journey.openFixture();
          await journey.performFixedActions();
          expect(await journey.terminalState()).toBe(SAFE_LIVE_JOURNEY.terminalAssertion);
        } finally {
          await fixtureContext.close();
        }
      },
      () => stopLiveRecording(page, scenario!.watcher),
    );
  });

  test("teaching-workflow-progress", async ({ page }) => {
    test.skip(!config.allowLiveCapture, "live_capture_opt_in_missing");
    await page.goto("/");
    await page.getByRole("button", { name: /技能教学/ }).click();
    await page.getByRole("button", { name: "开始" }).first().click();
    await page.getByRole("button", { name: "开始录制" }).click();
    await expect(page.getByRole("alertdialog", { name: "录制隐私确认" })).toContainText(
      /可见内容可能会被记录/,
    );
    await withLiveRecordingCleanup(
      async (markStopRequired) => {
        markStopRequired();
        await page.getByRole("button", { name: "确认并开始录制" }).click();
        await waitForPublicEvent(
          scenario!.watcher,
          (event) => event.type === "recording.progress" && event.payload.status === "recording",
        );
      },
      () => stopLiveRecording(page, scenario!.watcher),
    );
    await waitForPublicEvent(
      scenario!.watcher,
      (event) => event.type === "teaching.progress",
      120_000,
    );
    await expect(page.getByText("需求分析师")).toBeVisible({ timeout: 120_000 });
  });

  test("skills-compositions-visibility", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: /技能列表/ }).click();
    await expect(page.getByRole("heading", { name: "技能列表" })).toBeVisible();
    await page.getByRole("button", { name: /技能组合/ }).click();
    await expect(page.getByRole("heading", { name: "技能组合" })).toBeVisible();
  });

  test("settings-non-secret-interaction", async ({ page }) => {
    const secretRequests: string[] = [];
    const forbiddenSecretApi = ["", "api", "settings", "secrets", ""].join("/");
    page.on("request", (request) => {
      if (request.url().includes(forbiddenSecretApi)) secretRequests.push(request.url());
    });
    await page.goto("/");
    await page.getByRole("button", { name: /应用设置/ }).click();
    await expect(page.getByRole("heading", { name: "应用设置" })).toBeVisible();
    const timeout = page.getByLabel("请求超时");
    await timeout.fill("30");
    await page.getByRole("button", { name: /保存设置/ }).click();
    await expect(page.getByText("无未保存更改")).toBeVisible();
    await expect(page.locator("body")).not.toContainText(/sk-[A-Za-z0-9_-]+/);
    expect(secretRequests).toEqual([]);
  });

  test("cross-screen-stability", async ({ page }) => {
    await page.goto("/");
    for (const name of [/AI 助手/, /技能教学/, /技能列表/, /技能组合/, /应用设置/]) {
      await page.getByRole("button", { name }).click();
      await expect(page.getByRole("heading")).toBeVisible();
    }
  });
});
