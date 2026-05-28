import crypto from "node:crypto";
import { execFileSync } from "node:child_process";
import path from "node:path";

import { expect, test, type Browser, type Page } from "@playwright/test";

import {
  EventWatcher,
  streamPublicUiEvents,
  type PublicUiEvent,
} from "./helpers/event-watcher";
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
import {
  RealGrandTourSafeJourneyPage,
  SAFE_LIVE_JOURNEY,
} from "./pages/real-grand-tour-safe-journey";

const config = readRealGrandTourConfig();
const skipReason = realGrandTourSkipReason(config);
const projectRoot = path.resolve(process.cwd(), "..");
const commitSha = execFileSync("git", ["rev-parse", "--short", "HEAD"], {
  cwd: projectRoot,
  encoding: "utf8",
}).trim();
const frontendPort = Number(process.env.PLAYWRIGHT_REAL_GRAND_TOUR_DEV_SERVER_PORT ?? "5175");
const frontendBaseUrl = `http://127.0.0.1:${frontendPort}`;

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

type SkillSummaryDto = {
  toolId: string;
  name: string;
  description: string;
  status: string;
  trialSuccessCount: number;
  workflowId?: string | null;
};

type SkillCategoryResponseDto = {
  category: string;
  count: number;
  items: SkillSummaryDto[];
};

type CompositionSummaryDto = {
  compositionId: string;
  name: string;
  status: string;
  displayStatus?: string;
  members: Array<{ toolId: string; name?: string; selectedOrder: number; executionOrder?: number | null }>;
};

type TeachingRunDto = {
  workflowId: string;
  mode: string;
  stage: string;
  summary: Record<string, unknown>;
};

type TauriInternals = {
  metadata: { currentWindow: { label: string }; currentWebview: { label: string } };
  invoke: (cmd: string, args?: Record<string, unknown>, options?: unknown) => Promise<unknown>;
  transformCallback: (callback: (...args: unknown[]) => void) => number;
  unregisterCallback: (id: number) => void;
  callbacks: Map<number, (...args: unknown[]) => void>;
};

type E2EWindow = Window & {
  __MEXEMPLAR_E2E_SIDECAR__?: {
    baseUrl: string;
    port: number;
    sessionToken: string;
  };
  __MEXEMPLAR_E2E_TAURI_COMMANDS__?: string[];
  __TAURI_INTERNALS__?: TauriInternals;
};

const maxRunMs = config.maxElapsedMinutes * 60 * 1000;
const assistantReplyTimeoutMs = 180_000;
const workflowTimeoutMs = Math.min(maxRunMs, 900_000);
const shortEventTimeoutMs = 120_000;
const assistantReplyBodySelector = ".assistant-message[data-role='assistant'] .assistant-markdown";
const scriptedPmReplies = [
  "The task is a safe local validation only: open the fixture form, enter the fixed request text, and submit it.",
  `Yes, confirmed. The exact request text is: ${SAFE_LIVE_JOURNEY.fixedInputText}. Do not use credentials or external accounts.`,
  "The expected terminal state is the visible status text Submitted.",
  "Name the reusable skill for local approval form submission and keep the parameters minimal.",
  "That requirement is correct. Continue to learning and create the skill.",
];
const scriptedTrialTasks = [
  `Run the safe local validation with request text: ${SAFE_LIVE_JOURNEY.fixedInputText}.`,
  `Repeat the validation against the same safe fixture and submit: ${SAFE_LIVE_JOURNEY.fixedInputText}.`,
  `Final validation pass: submit ${SAFE_LIVE_JOURNEY.fixedInputText} and report the terminal state.`,
];

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

function eventStatus(event: PublicUiEvent): string | undefined {
  return typeof event.payload.status === "string" ? event.payload.status : undefined;
}

function eventStage(event: PublicUiEvent): string | undefined {
  return typeof event.payload.stage === "string" ? event.payload.stage : undefined;
}

function eventSequence(): number {
  return scenario?.watcher.lastObservableState?.sequence ?? 0;
}

function safeEventSummary(event: PublicUiEvent): string {
  return `${event.type}:${eventStatus(event) ?? eventStage(event) ?? "observed"}`;
}

function isFailureEvent(event: PublicUiEvent, afterSequence: number): boolean {
  if (event.sequence <= afterSequence) return false;
  const status = eventStatus(event);
  const stage = eventStage(event);
  if (event.type === "assistant.error") return true;
  if (stage === "failed") return true;
  if (status && ["failed", "error", "degraded", "budget_exceeded"].includes(status)) return true;
  if (typeof event.payload.error === "string" && event.payload.error.trim()) return true;
  if (
    event.type === "trial.preview_resolved" &&
    status &&
    !["approved", "already_resolved"].includes(status)
  ) {
    return true;
  }
  return false;
}

async function waitForEventOrFail(
  watcher: EventWatcher,
  predicate: (event: PublicUiEvent) => boolean,
  timeoutMs: number,
  label: string,
  afterSequence = 0,
): Promise<PublicUiEvent> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const failure = watcher.find((event) => isFailureEvent(event, afterSequence));
    if (failure) {
      throw new Error(`real_tour_public_failure:${label}:${safeEventSummary(failure)}`);
    }
    const event = watcher.find((candidate) => candidate.sequence > afterSequence && predicate(candidate));
    if (event) return event;
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  throw new Error(`real_tour_public_event_timeout:${label}:${observableState(watcher)}`);
}

async function waitForStage(
  watcher: EventWatcher,
  stage: string,
  timeoutMs = workflowTimeoutMs,
  afterSequence = 0,
): Promise<PublicUiEvent> {
  return waitForEventOrFail(
    watcher,
    (event) => event.type === "teaching.stage_changed" && eventStage(event) === stage,
    timeoutMs,
    `stage_${stage}`,
    afterSequence,
  );
}

function isNonEmptyAssistantMessage(event: PublicUiEvent, afterSequence: number): boolean {
  return (
    event.sequence > afterSequence &&
    event.type === "assistant.message" &&
    event.payload.role === "assistant" &&
    typeof event.payload.content === "string" &&
    event.payload.content.trim().length > 0
  );
}

async function waitForAssistantReply(
  watcher: EventWatcher,
  afterSequence: number,
  timeoutMs = assistantReplyTimeoutMs,
): Promise<PublicUiEvent> {
  return waitForEventOrFail(
    watcher,
    (event) => isNonEmptyAssistantMessage(event, afterSequence),
    timeoutMs,
    "assistant_reply",
    afterSequence,
  );
}

async function waitForTrialSuccessCount(
  watcher: EventWatcher,
  expectedCount: number,
  afterSequence = 0,
): Promise<PublicUiEvent> {
  return waitForEventOrFail(
    watcher,
    (event) =>
      event.type === "trial.progress" &&
      eventStatus(event) === "succeeded" &&
      typeof event.payload.successCount === "number" &&
      event.payload.successCount >= expectedCount,
    workflowTimeoutMs,
    `trial_success_${expectedCount}`,
    afterSequence,
  );
}

async function injectRuntime(page: Page, runtime: RealGrandTourRuntime): Promise<void> {
  await page.addInitScript(
    ({ baseUrl, port, token }) => {
      const targetWindow = window as E2EWindow;
      targetWindow.__MEXEMPLAR_E2E_SIDECAR__ = { baseUrl, port, sessionToken: token };
      targetWindow.__MEXEMPLAR_E2E_TAURI_COMMANDS__ = [];
      const callbacks = new Map<number, (...args: unknown[]) => void>();
      let callbackId = 1;
      targetWindow.__TAURI_INTERNALS__ = {
        metadata: {
          currentWindow: { label: "main" },
          currentWebview: { label: "main" },
        },
        callbacks,
        transformCallback: (callback) => {
          const id = callbackId++;
          callbacks.set(id, callback);
          return id;
        },
        unregisterCallback: (id) => {
          callbacks.delete(id);
        },
        invoke: async (cmd) => {
          targetWindow.__MEXEMPLAR_E2E_TAURI_COMMANDS__?.push(cmd);
          if (cmd === "plugin:window|is_minimized") return true;
          if (cmd === "plugin:window|is_maximized") return false;
          if (cmd === "plugin:window|is_focused") return true;
          if (cmd === "plugin:window|title") return "Mexemplar";
          return null;
        },
      };
    },
    { baseUrl: runtime.baseUrl, port: runtime.port, token: runtime.token },
  );
}

async function apiFetch<T>(
  runtime: RealGrandTourRuntime,
  apiPath: string,
  init: RequestInit = {},
): Promise<T> {
  const response = await fetch(`${runtime.baseUrl}${apiPath}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      "X-Mexemplar-Session": runtime.token,
      ...init.headers,
    },
  });
  if (!response.ok) {
    throw new Error(`real_tour_api_failed:${apiPath}:${response.status}`);
  }
  return (await response.json()) as T;
}

async function listSkills(category: "pending" | "published"): Promise<SkillSummaryDto[]> {
  const activeRun = run;
  if (!activeRun) throw new Error("real_tour_runtime_unavailable");
  const response = await apiFetch<SkillCategoryResponseDto>(
    activeRun.sidecar,
    `/api/skills?category=${category}`,
  );
  return response.items ?? [];
}

async function waitForSkill(
  category: "pending" | "published",
  predicate: (skill: SkillSummaryDto) => boolean,
  timeoutMs = shortEventTimeoutMs,
): Promise<SkillSummaryDto> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const match = (await listSkills(category)).find(predicate);
    if (match) return match;
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  throw new Error(`real_tour_skill_timeout:${category}`);
}

async function waitForSkillSavedEvent(
  watcher: EventWatcher,
  afterSequence: number,
): Promise<PublicUiEvent> {
  return waitForEventOrFail(
    watcher,
    (event) =>
      event.type === "skills.changed" &&
      event.payload.status === "saved" &&
      typeof event.payload.toolId === "string" &&
      event.payload.toolId.trim().length > 0,
    shortEventTimeoutMs,
    "skill_saved_event",
    afterSequence,
  );
}

async function waitForComposition(
  predicate: (composition: CompositionSummaryDto) => boolean,
  timeoutMs = shortEventTimeoutMs,
): Promise<CompositionSummaryDto> {
  const activeRun = run;
  if (!activeRun) throw new Error("real_tour_runtime_unavailable");
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const response = await apiFetch<{ items: CompositionSummaryDto[] }>(
      activeRun.sidecar,
      "/api/compositions",
    );
    const match = (response.items ?? []).find(predicate);
    if (match) return match;
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  throw new Error("real_tour_composition_timeout");
}

function numberFromRecord(value: unknown, key: string): number | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const candidate = (value as Record<string, unknown>)[key];
  return typeof candidate === "number" && Number.isFinite(candidate) ? candidate : null;
}

async function stopRecordingIfNeeded(page: Page, watcher: EventWatcher): Promise<void> {
  const beforeStopSequence = eventSequence();
  const stopButton = page.getByRole("button", { name: "停止录制" });
  const visible = await stopButton.isVisible({ timeout: 2000 }).catch(() => false);
  if (!visible) return;
  await expect(stopButton).toBeEnabled({ timeout: shortEventTimeoutMs });
  await stopButton.click();
  await waitForEventOrFail(
    watcher,
    (event) =>
      event.type === "recording.progress" &&
      ["stopped", "completed"].includes(eventStatus(event) ?? ""),
    shortEventTimeoutMs,
    "recording_stopped",
    beforeStopSequence,
  );
}

async function selectTeachingMode(page: Page, modeName: RegExp): Promise<void> {
  await page.getByRole("button", { name: /技能教学/ }).click();
  await expect(page.getByRole("heading", { name: "技能教学" })).toBeVisible();
  await page.getByRole("tab", { name: modeName }).click();
  await page.getByRole("button", { name: "开始" }).click();
  await expect(page.getByRole("button", { name: "开始录制" })).toBeVisible({
    timeout: shortEventTimeoutMs,
  });
}

async function startTeachingRecording(page: Page, watcher: EventWatcher): Promise<void> {
  const beforeStartSequence = eventSequence();
  await page.getByRole("button", { name: "开始录制" }).click();
  await expect(page.getByRole("alertdialog", { name: "录制隐私确认" })).toContainText(
    /可见内容可能会被记录/,
  );
  await page.getByRole("button", { name: "确认并开始录制" }).click();
  await waitForEventOrFail(
    watcher,
    (event) => event.type === "recording.progress" && eventStatus(event) === "recording",
    shortEventTimeoutMs,
    "recording_started",
    beforeStartSequence,
  );
}

async function sendTeachingChat(page: Page, text: string): Promise<void> {
  const composer = page.locator(".teaching-composer textarea").last();
  await expect(composer).toBeEnabled({ timeout: workflowTimeoutMs });
  await composer.fill(text);
  await composer.press("Enter");
}

async function advanceIntentWithScript(
  page: Page,
  watcher: EventWatcher,
  startAfterSequence: number,
): Promise<void> {
  let afterSequence = startAfterSequence;
  for (const reply of scriptedPmReplies) {
    const alreadyLearning = watcher.find(
      (event) =>
        event.sequence > afterSequence &&
        event.type === "teaching.stage_changed" &&
        ["learning", "trial_validation", "published"].includes(eventStage(event) ?? ""),
    );
    if (alreadyLearning) return;

    const promptEvent = await waitForEventOrFail(
      watcher,
      (event) => {
        if (
          event.type === "teaching.stage_changed" &&
          ["learning", "trial_validation", "published"].includes(eventStage(event) ?? "")
        ) {
          return true;
        }
        return (
          event.type === "teaching.progress" &&
          eventStatus(event) === "waiting_for_user" &&
          Boolean(event.payload.question || event.payload.headline || event.payload.message)
        );
      },
      workflowTimeoutMs,
      "pm_question",
      afterSequence,
    );
    const isStageChange =
      promptEvent.type === "teaching.stage_changed" &&
      ["learning", "trial_validation", "published"].includes(eventStage(promptEvent) ?? "");
    if (isStageChange) return;
    afterSequence = promptEvent.sequence;
    await sendTeachingChat(page, reply);
    const stage = await Promise.race([
      waitForEventOrFail(
        watcher,
        (event) =>
          event.type === "teaching.stage_changed" &&
          ["learning", "trial_validation", "published"].includes(eventStage(event) ?? ""),
        10_000,
        "pm_stage_after_reply",
        afterSequence,
      ).catch(() => null),
      new Promise<null>((resolve) => setTimeout(() => resolve(null), 10_000)),
    ]);
    if (stage) return;
  }
  await waitForEventOrFail(
    watcher,
    (event) =>
      event.type === "teaching.stage_changed" &&
      ["learning", "trial_validation", "published"].includes(eventStage(event) ?? ""),
    workflowTimeoutMs,
    "pm_script_exhausted",
    afterSequence,
  );
}

async function openSkillsCategory(page: Page, tabName: RegExp): Promise<void> {
  await page.getByRole("button", { name: /技能列表/ }).click();
  await expect(page.getByRole("heading", { name: "技能列表" })).toBeVisible({
    timeout: shortEventTimeoutMs,
  });
  await page.getByRole("tab", { name: tabName }).click();
}

async function approveTrialPreviewIfVisible(page: Page): Promise<void> {
  const approve = page.getByRole("button", { name: "批准" });
  if (await approve.isVisible({ timeout: 250 }).catch(() => false)) {
    await approve.click();
  }
}

async function sendTrialTask(page: Page, text: string): Promise<void> {
  const composer = page.locator(".trial-dialog .teaching-composer textarea").last();
  await expect(composer).toBeEnabled({ timeout: workflowTimeoutMs });
  await composer.fill(text);
  await composer.press("Enter");
}

async function confirmTrialResultUntilSuccess(
  page: Page,
  watcher: EventWatcher,
  expectedCount: number,
  afterSequence: number,
): Promise<PublicUiEvent> {
  const startedAt = Date.now();
  while (Date.now() - startedAt < workflowTimeoutMs) {
    const success = watcher.find(
      (event) =>
        event.sequence > afterSequence &&
        event.type === "trial.progress" &&
        eventStatus(event) === "succeeded" &&
        typeof event.payload.successCount === "number" &&
        event.payload.successCount >= expectedCount,
    );
    if (success) return success;

    const failure = watcher.find((event) => isFailureEvent(event, afterSequence));
    if (failure) {
      throw new Error(`real_tour_public_failure:trial:${safeEventSummary(failure)}`);
    }

    await approveTrialPreviewIfVisible(page);
    const correct = page.getByRole("button", { name: "结果正确" });
    if (await correct.isVisible({ timeout: 250 }).catch(() => false)) {
      await correct.click();
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error(`real_tour_trial_verdict_timeout:${observableState(watcher)}`);
}

async function completeThreeSkillTrials(page: Page, watcher: EventWatcher, pendingSkill: SkillSummaryDto): Promise<void> {
  await openSkillsCategory(page, /待考核/);
  let pendingRow = page.locator(".skill-pending-row", { hasText: pendingSkill.name });
  if (!(await pendingRow.isVisible({ timeout: 5000 }).catch(() => false))) {
    await page.reload();
    await expect(page.getByRole("status")).toContainText(/已就绪|ready/i, { timeout: 60_000 });
    await openSkillsCategory(page, /待考核/);
    pendingRow = page.locator(".skill-pending-row", { hasText: pendingSkill.name });
  }
  await expect(pendingRow).toBeVisible({ timeout: shortEventTimeoutMs });
  await pendingRow.getByRole("button", { name: "试用" }).click();
  await expect(page.getByRole("dialog", { name: "技能试用" })).toBeVisible({
    timeout: shortEventTimeoutMs,
  });
  const trialGreetingSequence = eventSequence();
  await waitForEventOrFail(
    watcher,
    (event) =>
      event.type === "trial.progress" &&
      eventStatus(event) === "waiting_for_user",
    shortEventTimeoutMs,
    "trial_greeting",
    trialGreetingSequence,
  );
  await expect(page.locator(".trial-dialog .teaching-ai-msg")).toBeVisible({
    timeout: shortEventTimeoutMs,
  });

  for (let index = 0; index < scriptedTrialTasks.length; index += 1) {
    const expectedCount = index + 1;
    const beforeTrialSequence = eventSequence();
    await sendTrialTask(page, scriptedTrialTasks[index]);
    await confirmTrialResultUntilSuccess(page, watcher, expectedCount, beforeTrialSequence);
    await waitForTrialSuccessCount(watcher, expectedCount);
  }

  await waitForEventOrFail(
    watcher,
    (event) =>
      (event.type === "trial.progress" && event.payload.published === true) ||
      (event.type === "teaching.stage_changed" && eventStage(event) === "published"),
    shortEventTimeoutMs,
    "skill_published",
  );
}

async function createAndPublishComposition(page: Page, skill: SkillSummaryDto): Promise<CompositionSummaryDto> {
  const compositionName = `Safe Local Approval Chain ${crypto.randomUUID().slice(0, 8)}`;

  await page.getByRole("button", { name: /技能组合/ }).click();
  await expect(page.getByRole("heading", { name: "技能组合" })).toBeVisible();
  await page.getByRole("button", { name: /^新建组合$/ }).first().click();
  await page.getByRole("button", { name: /顺序型/ }).click();
  await page.getByLabel("名称").fill(compositionName);
  await page.getByLabel("描述").fill("Runs the safe local approval fixture skill.");
  await page.getByLabel("适用场景").fill("Use for the Real Grand Tour safe local approval fixture only.");
  await page.locator(".composition-skill-picker").getByLabel("搜索技能").fill(skill.name);
  await page.locator(".composition-skill-option", { hasText: skill.name }).click();
  await page.getByRole("button", { name: "保存草稿" }).click();
  await expect(page.getByText(`当前：${compositionName}`)).toBeVisible({
    timeout: shortEventTimeoutMs,
  });
  await expect(page.getByRole("button", { name: "发布" })).toBeEnabled({
    timeout: shortEventTimeoutMs,
  });
  await page.getByRole("button", { name: "发布" }).click();

  const composition = await waitForComposition(
    (item) => item.name === compositionName && item.status === "published",
  );
  await page.getByRole("button", { name: "返回列表" }).click();
  const compositionCard = page.locator(".composition-card", { hasText: compositionName });
  await expect(compositionCard).toBeVisible({ timeout: shortEventTimeoutMs });
  await expect(compositionCard).toContainText("已发布");
  return composition;
}

async function sendAssistantDispatchPrompt(page: Page, prompt: string): Promise<void> {
  await page.getByRole("button", { name: /AI 助手|AI Assistant/ }).click();
  const visibleAssistantReplies = page.locator(assistantReplyBodySelector).filter({ hasText: /\S/ });
  await expect(page.getByLabel("输入消息")).toBeEnabled({ timeout: shortEventTimeoutMs });
  const previousVisibleReplyCount = await visibleAssistantReplies.count();
  await page.getByLabel("输入消息").fill(prompt);
  await page.getByRole("button", { name: "发送" }).click();

  await expect
    .poll(async () => visibleAssistantReplies.count(), { timeout: assistantReplyTimeoutMs })
    .toBeGreaterThan(previousVisibleReplyCount);
  await expect(visibleAssistantReplies.nth(previousVisibleReplyCount)).toContainText(/\S/);
}

async function performDesktopSafeJourney(browser: Browser): Promise<void> {
  const fixturePage = await browser.newPage();
  try {
    const journey = new RealGrandTourSafeJourneyPage(fixturePage);
    await journey.openFixture(frontendBaseUrl);
    await journey.performFixedActions();
    expect(await journey.terminalState()).toBe(SAFE_LIVE_JOURNEY.terminalAssertion);
  } finally {
    await fixturePage.close();
  }
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
    await selectTeachingMode(page, /浏览器录制/);
    await startTeachingRecording(page, activeScenario.watcher);
    await stopRecordingIfNeeded(page, activeScenario.watcher);
    const intentEvent = await waitForStage(activeScenario.watcher, "intent_confirmation");

    const workflowId = intentEvent.scope.workflowId;
    const stoppedRun = await apiFetch<TeachingRunDto>(
      activeRun.sidecar,
      `/api/teaching/runs/${encodeURIComponent(workflowId)}`,
    );
    const recordingSummary = stoppedRun.summary.recording;
    const actionCount = numberFromRecord(recordingSummary, "action_count") ?? 0;
    expect(actionCount).toBeGreaterThan(0);

    const afterIntentSequence = intentEvent.sequence;
    await advanceIntentWithScript(page, activeScenario.watcher, afterIntentSequence);
    await waitForEventOrFail(
      activeScenario.watcher,
      (event) =>
        event.type === "teaching.stage_changed" &&
        ["trial_validation", "published"].includes(eventStage(event) ?? ""),
      workflowTimeoutMs,
      "learning_completed",
      afterIntentSequence,
    );
    const savedEvent = await waitForSkillSavedEvent(
      activeScenario.watcher,
      afterIntentSequence,
    );
    const savedToolId = String(savedEvent.payload.toolId);

    const pendingSkill = await waitForSkill(
      "pending",
      (skill) =>
        skill.workflowId === workflowId &&
        skill.toolId === savedToolId &&
        skill.trialSuccessCount < 3,
      shortEventTimeoutMs,
    );
    await completeThreeSkillTrials(page, activeScenario.watcher, pendingSkill);
    const publishedSkill = await waitForSkill(
      "published",
      (skill) => skill.workflowId === workflowId && skill.trialSuccessCount >= 3,
      shortEventTimeoutMs,
    );

    await page.getByRole("button", { name: /技能列表/ }).click();
    await page.getByRole("tab", { name: /已掌握/ }).click();
    const publishedCard = page.locator(".skill-mastered-card", { hasText: publishedSkill.name });
    await expect(publishedCard).toBeVisible({ timeout: shortEventTimeoutMs });
    await expect(publishedCard).toContainText(/成功\s*3\/3/);

    const composition = await createAndPublishComposition(page, publishedSkill);
    expect(composition.members.some((member) => member.toolId === publishedSkill.toolId)).toBe(true);

    await sendAssistantDispatchPrompt(
      page,
      `Use the published skill named "${publishedSkill.name}" for this safe local validation task. Submit "${SAFE_LIVE_JOURNEY.fixedInputText}" and reply with the result.`,
    );
    await sendAssistantDispatchPrompt(
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
    await selectTeachingMode(page, /桌面录制/);
    await withLiveRecordingCleanup(
      async (markStopRequired) => {
        markStopRequired();
        await startTeachingRecording(page, activeScenario.watcher);
        await performDesktopSafeJourney(browser);
      },
      () => stopRecordingIfNeeded(page, activeScenario.watcher),
    );
  });
});
