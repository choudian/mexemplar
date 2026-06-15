import { expect, test, type Page, type Route } from "@playwright/test";

import { installMockApi } from "./mock-api";

const failure = {
  category: "network",
  message: "连接模型服务时中断了。",
  suggestion: "请检查网络连接后重试。",
  attemptCount: 1,
  failedAt: "2026-06-15T00:00:01Z",
};

const failedMessage = {
  sequence: 1,
  role: "user",
  content: "完成季度报告",
  createdAt: "2026-06-15T00:00:00Z",
  rendering: "plain_text",
  failure,
};

function json(route: Route, payload: unknown): Promise<void> {
  return route.fulfill({
    status: 200,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

async function installFailedHistory(page: Page): Promise<void> {
  await page.route(/\/api\/assistant\/sessions\/ast_1\/messages(?:\?|$)/, async (route) => {
    if (route.request().method() !== "GET") {
      await route.fallback();
      return;
    }
    await json(route, {
      items: [failedMessage],
      hasMoreBefore: false,
      nextBeforeSequence: null,
    });
  });
}

async function openFailedConversation(page: Page): Promise<void> {
  await page.goto("/");
  await page.getByRole("button", { name: /E2E conversation/ }).click();
  await expect(page.getByText("这条消息没有完成")).toBeVisible();
}

function eventFrame(event: Record<string, unknown>): string {
  return `id: ${event.sessionId}:${event.sequence}\nevent: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`;
}

test("failed Assistant history restores the inline recovery card", async ({ page }) => {
  await installMockApi(page);
  await installFailedHistory(page);

  await openFailedConversation(page);

  await expect(page.getByText(failure.message)).toBeVisible();
  await expect(page.getByRole("button", { name: "重试", exact: true })).toBeEnabled();
  await expect(page.getByRole("button", { name: "编辑后重试" })).toBeEnabled();
});

test("unchanged retry submits the original sequence and authoritative success removes the card", async ({
  page,
}) => {
  await installMockApi(page);
  await installFailedHistory(page);

  let releaseEvents!: () => void;
  const retryStarted = new Promise<void>((resolve) => {
    releaseEvents = resolve;
  });
  let retryBody: unknown;

  await page.route(/\/api\/assistant\/sessions\/ast_1\/retry$/, async (route) => {
    retryBody = route.request().postDataJSON();
    releaseEvents();
    await json(route, { accepted: true, sessionId: "ast_1", messageSequence: 1 });
  });
  await page.route(/\/api\/events(?:\?|$)/, async (route) => {
    await retryStarted;
    const now = "2026-06-15T00:00:02Z";
    const frames = [
      eventFrame({
        eventId: "evt_retry_message",
        sequence: 1,
        sessionId: "ui_retry",
        causationId: null,
        type: "assistant.message",
        scope: { sessionId: "ast_1" },
        payload: { ...failedMessage, failure: undefined },
        createdAt: now,
      }),
      eventFrame({
        eventId: "evt_retry_done",
        sequence: 2,
        sessionId: "ui_retry",
        causationId: null,
        type: "assistant.progress",
        scope: { sessionId: "ast_1" },
        payload: { status: "succeeded", headline: "已完成" },
        createdAt: now,
      }),
    ].join("");
    await route.fulfill({
      status: 200,
      headers: { "Content-Type": "text/event-stream" },
      body: frames,
    });
  });

  await openFailedConversation(page);
  await page.getByRole("button", { name: "重试", exact: true }).click();

  await expect(page.getByText("这条消息没有完成")).toHaveCount(0);
  expect(retryBody).toEqual({ messageSequence: 1 });
});

test("edited retry submits new content without changing the original bubble", async ({ page }) => {
  await installMockApi(page);
  await installFailedHistory(page);

  let retryBody: unknown;
  await page.route(/\/api\/assistant\/sessions\/ast_1\/retry$/, async (route) => {
    retryBody = route.request().postDataJSON();
    await json(route, { accepted: true, sessionId: "ast_1", messageSequence: 1 });
  });

  await openFailedConversation(page);
  await page.getByRole("button", { name: "编辑后重试" }).click();
  await page.getByLabel("编辑后重试").fill("缩小范围后重新完成报告");
  await page.getByRole("button", { name: "提交重试" }).click();

  await expect.poll(() => retryBody).toEqual({
    messageSequence: 1,
    content: "缩小范围后重新完成报告",
  });
  await expect(page.getByText("完成季度报告")).toBeVisible();
});

test("debug action opens the Inspector filtered by the failed session", async ({ page }) => {
  await installMockApi(page);
  await installFailedHistory(page);

  await openFailedConversation(page);
  await page.getByRole("button", { name: "查看调试信息" }).click();

  await expect(page).toHaveURL(/\/debug\?sessionId=ast_1$/);
  await expect(page.getByRole("heading", { name: "Debug Inspector" })).toBeVisible();
  const sessionFilter = page.getByRole("status").filter({ hasText: "会话筛选" });
  await expect(sessionFilter.getByText("ast_1")).toBeVisible();
  await expect(page.getByText(/失败发生前的原始调试详情无法补录/)).toBeVisible();
});
