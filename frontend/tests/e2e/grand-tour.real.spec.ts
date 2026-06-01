import crypto from "node:crypto";
import { execFileSync } from "node:child_process";
import path from "node:path";

import { expect, test } from "@playwright/test";

import { EventWatcher, streamPublicUiEvents, waitForPublicEvent } from "./helpers/event-watcher";
import {
  createRealGrandTourFlow,
  type TeachingRunDto,
} from "./helpers/real-grand-tour-flow";
import { withLiveRecordingCleanup } from "./helpers/real-grand-tour-recording";
import { writeSummaryReport, type ScenarioReport } from "./helpers/real-grand-tour-report";
import {
  readRealGrandTourAudit,
  readRealGrandTourConfig,
  realGrandTourSkipReason,
  startRealGrandTourRuntime,
  waitForRealGrandTourHealth,
  type RealGrandTourAuditSnapshot,
  type RealGrandTourRuntime,
} from "./helpers/real-grand-tour-runtime";
import { SAFE_LIVE_JOURNEY } from "./pages/real-grand-tour-safe-journey";

const config = readRealGrandTourConfig();
const skipReason = realGrandTourSkipReason(config);
const projectRoot = path.resolve(process.cwd(), "..");
const commitSha = execFileSync("git", ["rev-parse", "--short", "HEAD"], {
  cwd: projectRoot,
  encoding: "utf8",
}).trim();
const frontendPort = Number(process.env.PLAYWRIGHT_REAL_GRAND_TOUR_DEV_SERVER_PORT ?? "5175");
const frontendBaseUrl = `http://127.0.0.1:${frontendPort}`;
const maxRunMs = config.maxElapsedMinutes * 60 * 1000;
const flow = createRealGrandTourFlow({ frontendBaseUrl, maxRunMs });

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

let run: RunRuntime | null = null;
let scenario: ScenarioRuntime | null = null;

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
    await flow.injectRuntime(page, activeRun.sidecar);
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
    if (flow.runElapsedMs(activeRun) >= maxRunMs) {
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
    if (flow.runElapsedMs(activeRun) > maxRunMs) {
      evidenceFailures.push("budget_exceeded");
    }
    evidenceFailures.forEach((failure) => activeRun.evidenceFailures.add(failure));
    const status =
      testInfo.status === "passed" ? "passed" : testInfo.status === "skipped" ? "skipped" : "failed";
    const elapsedMs = Math.max(0, Date.now() - activeScenario.startedAtMs);
    const paidCallCount = Math.max(
      0,
      (audit?.paidCallCount ?? activeScenario.paidCallsAtStart) -
        activeScenario.paidCallsAtStart,
    );
    activeRun.scenarios.push({
      scenarioId: testInfo.title,
      status: evidenceFailures.length > 0 ? "failed" : status,
      lastObservableState: flow.observableState(activeScenario.watcher),
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
      flow.addOnce(evidenceFailures, "audit_unavailable");
    }
    if (audit?.credentialMutationCount) {
      flow.addOnce(evidenceFailures, "credential_mutation_detected");
    }
    if (audit?.budgetExceeded || flow.runElapsedMs(activeRun) > maxRunMs) {
      flow.addOnce(evidenceFailures, "budget_exceeded");
    }
    const cleanupStatus = await activeRun.sidecar.cleanup();
    if (cleanupStatus !== "completed") {
      flow.addOnce(evidenceFailures, "cleanup_failed");
    }
    writeSummaryReport(
      {
        runId: activeRun.runId,
        commitSha,
        liveJourneyId: SAFE_LIVE_JOURNEY.liveJourneyId,
        startedAt: activeRun.startedAt,
        finishedAt: new Date().toISOString(),
        budgetUsage: {
          elapsedMs: flow.runElapsedMs(activeRun),
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

  test("browser-teaching-to-assistant-dispatch", async ({ page }, testInfo) => {
    testInfo.annotations.push({
      type: "cost-warning",
      description: "This scenario performs real paid model calls through the full teaching and assistant chain.",
    });
    const activeRun = run;
    const activeScenario = scenario;
    if (!activeRun || !activeScenario) throw new Error("real_tour_runtime_unavailable");

    await page.goto("/");
    await expect(page.getByRole("status")).toContainText(/已就绪|ready/i, { timeout: 60_000 });
    await flow.selectTeachingMode(page, /浏览器录制/);
    await flow.startTeachingRecording(page, activeScenario.watcher);
    await flow.stopRecordingIfNeeded(page, activeScenario.watcher);
    const intentEvent = await flow.waitForStage(activeScenario.watcher, "intent_confirmation");

    const workflowId = intentEvent.scope.workflowId;
    const stoppedRun = await flow.apiFetch<TeachingRunDto>(
      activeRun.sidecar,
      `/api/teaching/runs/${encodeURIComponent(workflowId)}`,
    );
    const recordingSummary = stoppedRun.summary.recording;
    const actionCount = flow.numberFromRecord(recordingSummary, "action_count") ?? 0;
    expect(actionCount).toBeGreaterThan(0);

    const afterIntentSequence = intentEvent.sequence;
    await flow.advanceIntentWithScript(page, activeScenario.watcher, afterIntentSequence);
    await flow.waitForEventOrFail(
      activeScenario.watcher,
      (event) =>
        event.type === "teaching.stage_changed" &&
        ["trial_validation", "published"].includes(flow.eventStage(event) ?? ""),
      flow.workflowTimeoutMs,
      "learning_completed",
      afterIntentSequence,
    );
    const savedEvent = await flow.waitForSkillSavedEvent(
      activeScenario.watcher,
      afterIntentSequence,
    );
    const savedToolId = String(savedEvent.payload.toolId);

    const pendingSkill = await flow.waitForSkill(
      activeRun.sidecar,
      "pending",
      (skill) =>
        skill.workflowId === workflowId &&
        skill.toolId === savedToolId &&
        skill.trialSuccessCount < 3,
      flow.shortEventTimeoutMs,
    );
    await flow.completeThreeSkillTrials(page, activeScenario.watcher, pendingSkill);
    const publishedSkill = await flow.waitForSkill(
      activeRun.sidecar,
      "published",
      (skill) => skill.workflowId === workflowId && skill.trialSuccessCount >= 3,
      flow.shortEventTimeoutMs,
    );

    await page.getByRole("button", { name: /工具列表/ }).click();
    await page.getByRole("tab", { name: /已掌握/ }).click();
    const publishedCard = page.locator(".skill-mastered-card", { hasText: publishedSkill.name });
    await expect(publishedCard).toBeVisible({ timeout: flow.shortEventTimeoutMs });
    await expect(publishedCard).toContainText(/成功\s*3\/3/);

    const composition = await flow.createAndPublishComposition(activeRun.sidecar, page, publishedSkill);
    expect(composition.members.some((member) => member.toolId === publishedSkill.toolId)).toBe(true);

    await flow.sendAssistantDispatchPrompt(
      page,
      `Use the published skill named "${publishedSkill.name}" for this safe local validation task. Submit "${SAFE_LIVE_JOURNEY.fixedInputText}" and reply with the result.`,
    );
    await flow.sendAssistantDispatchPrompt(
      page,
      `Use the published skill composition named "${composition.name}" for this safe local validation task. Submit "${SAFE_LIVE_JOURNEY.fixedInputText}" and reply with the result.`,
    );
  });

  test("desktop-recording-smoke", async ({ browser, page }, testInfo) => {
    test.skip(!config.allowLiveCapture, "live_capture_opt_in_missing");
    testInfo.annotations.push({
      type: "privacy-warning",
      description: "Live capture may record visible desktop content; use only the fixed safe fixture.",
    });
    const activeScenario = scenario;
    if (!activeScenario) throw new Error("real_tour_runtime_unavailable");

    await page.goto("/");
    await flow.selectTeachingMode(page, /桌面录制/);
    await withLiveRecordingCleanup(
      async (markStopRequired) => {
        markStopRequired();
        await flow.startTeachingRecording(page, activeScenario.watcher);
        await flow.performDesktopSafeJourney(browser);
      },
      () => flow.stopRecordingIfNeeded(page, activeScenario.watcher),
    );
  });

  test("teaching-workflow-progress", async ({ page }) => {
    test.skip(!config.allowLiveCapture, "live_capture_opt_in_missing");
    const activeScenario = scenario;
    if (!activeScenario) throw new Error("real_tour_runtime_unavailable");

    await page.goto("/");
    await flow.selectTeachingMode(page, /桌面录制/);
    await withLiveRecordingCleanup(
      async (markStopRequired) => {
        markStopRequired();
        await flow.startTeachingRecording(page, activeScenario.watcher);
        await waitForPublicEvent(
          activeScenario.watcher,
          (event) => event.type === "recording.progress" && event.payload.status === "recording",
        );
      },
      () => flow.stopRecordingIfNeeded(page, activeScenario.watcher),
    );
    await waitForPublicEvent(
      activeScenario.watcher,
      (event) => event.type === "teaching.progress",
      120_000,
    );
    await expect(page.getByText("需求分析师")).toBeVisible({ timeout: 120_000 });
  });

  test("skills-compositions-visibility", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("button", { name: /工具列表/ }).click();
    await expect(page.getByRole("heading", { name: "工具列表" })).toBeVisible();
    await page.getByRole("button", { name: /工具组合/ }).click();
    await expect(page.getByRole("heading", { name: "工具组合" })).toBeVisible();
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
    for (const name of [/AI 助手/, /工具教学/, /工具列表/, /工具组合/, /应用设置/]) {
      await page.getByRole("button", { name }).click();
      await expect(page.locator("main, section").first()).toBeVisible();
    }
  });
});
