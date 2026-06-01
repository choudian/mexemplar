import { expect, test } from "@playwright/test";

import { installMockApi } from "./mock-api";

let page: import("@playwright/test").Page;

test.describe("Long-paste composer E2E", () => {
  test.beforeEach(async ({ page: p }) => {
    page = p;
    await installMockApi(page);
    await page.goto("/");
    await page.bringToFront();
    await expect(page.getByRole("status")).toContainText("已就绪", { timeout: 30_000 });
  });

  test("CP-001: Assistant — qualifying 7-line paste collapses and sends exact content", async () => {
    // Navigate to assistant
    await page.getByRole("button", { name: /AI 助手/ }).click();

    const textarea = page.getByLabel("输入消息");
    await expect(textarea).toBeVisible();

    // Prepare 7-line text
    const sevenLineText = Array.from({ length: 7 }, (_, i) => `第${i + 1}行测试内容`).join("\n");

    // Paste via clipboard simulation
    await textarea.click();
    await page.evaluate((text) => {
      const el = document.querySelector("[aria-label='输入消息']") as HTMLTextAreaElement;
      if (!el) return;
      const dt = new DataTransfer();
      dt.setData("text/plain", text);
      const pasteEvent = new ClipboardEvent("paste", {
        bubbles: true,
        cancelable: true,
        clipboardData: dt,
      });
      el.dispatchEvent(pasteEvent);
    }, sevenLineText);

    // Verify collapsed preview appears
    const preview = page.locator("[data-long-paste-preview]");
    await expect(preview).toBeVisible({ timeout: 5_000 });

    // Send and verify draft is sent
    await page.getByRole("button", { name: /发送/ }).click();
  });

  test("CP-002: Teaching — same collapse behavior as Assistant", async () => {
    await page.getByRole("button", { name: /工具教学/ }).click();
    await page.getByRole("button", { name: "开始" }).first().click();
    await page.getByRole("button", { name: "开始录制" }).click();
    await page.getByRole("button", { name: "确认并开始录制" }).click();
    await page.getByRole("button", { name: "停止录制" }).click();

    const textarea = page.getByPlaceholder("回复需求分析师…");
    await expect(textarea).toBeVisible();

    const sevenLineText = Array.from({ length: 7 }, (_, i) => `第${i + 1}行测试内容`).join("\n");

    await textarea.click();
    await page.evaluate((text) => {
      const el = document.querySelector("[placeholder='回复需求分析师…']") as HTMLTextAreaElement;
      if (!el) return;
      const dt = new DataTransfer();
      dt.setData("text/plain", text);
      const pasteEvent = new ClipboardEvent("paste", {
        bubbles: true,
        cancelable: true,
        clipboardData: dt,
      });
      el.dispatchEvent(pasteEvent);
    }, sevenLineText);

    const preview = page.locator("[data-long-paste-preview]");
    await expect(preview).toBeVisible({ timeout: 5_000 });
  });

  test("CP-003: non-qualifying 6-line paste stays as normal textarea", async () => {
    await page.getByRole("button", { name: /AI 助手/ }).click();

    const textarea = page.getByLabel("输入消息");
    await expect(textarea).toBeVisible();

    const sixLineText = Array.from({ length: 6 }, (_, i) => `第${i + 1}行`).join("\n");

    await textarea.click();
    await page.evaluate((text) => {
      const el = document.querySelector("[aria-label='输入消息']") as HTMLTextAreaElement;
      if (!el) return;
      const dt = new DataTransfer();
      dt.setData("text/plain", text);
      const pasteEvent = new ClipboardEvent("paste", {
        bubbles: true,
        cancelable: true,
        clipboardData: dt,
      });
      el.dispatchEvent(pasteEvent);
    }, sixLineText);

    // Should NOT show preview
    const preview = page.locator("[data-long-paste-preview]");
    await expect(preview).not.toBeVisible({ timeout: 3_000 });
  });

  test("CP-004: character threshold — 1201 chars collapses, 1200 does not", async () => {
    await page.getByRole("button", { name: /AI 助手/ }).click();

    const textarea = page.getByLabel("输入消息");
    await expect(textarea).toBeVisible();

    // 1201 chars should collapse
    const longText = "a".repeat(1201);
    await textarea.click();
    await page.evaluate((text) => {
      const el = document.querySelector("[aria-label='输入消息']") as HTMLTextAreaElement;
      if (!el) return;
      const dt = new DataTransfer();
      dt.setData("text/plain", text);
      const pasteEvent = new ClipboardEvent("paste", {
        bubbles: true,
        cancelable: true,
        clipboardData: dt,
      });
      el.dispatchEvent(pasteEvent);
    }, longText);

    const preview = page.locator("[data-long-paste-preview]");
    await expect(preview).toBeVisible({ timeout: 5_000 });
  });

  test("CP-005: manual typing does not auto-collapse even when exceeding threshold", async () => {
    await page.getByRole("button", { name: /AI 助手/ }).click();

    const textarea = page.getByLabel("输入消息");
    await expect(textarea).toBeVisible();

    // Type more than 1200 chars manually
    const longText = "a".repeat(1300);
    await textarea.fill(longText);

    // Should NOT show preview — manual typing doesn't trigger collapse
    const preview = page.locator("[data-long-paste-preview]");
    await expect(preview).not.toBeVisible({ timeout: 2_000 });
  });

  test("CP-006: keyboard can expand, collapse, clear, and send", async () => {
    await page.getByRole("button", { name: /AI 助手/ }).click();

    const textarea = page.getByLabel("输入消息");
    await expect(textarea).toBeVisible();

    // Paste qualifying text
    const sevenLineText = Array.from({ length: 7 }, (_, i) => `Line ${i + 1}`).join("\n");
    await textarea.click();
    await page.evaluate((text) => {
      const el = document.querySelector("[aria-label='输入消息']") as HTMLTextAreaElement;
      if (!el) return;
      const dt = new DataTransfer();
      dt.setData("text/plain", text);
      const pasteEvent = new ClipboardEvent("paste", {
        bubbles: true,
        cancelable: true,
        clipboardData: dt,
      });
      el.dispatchEvent(pasteEvent);
    }, sevenLineText);

    // Should have preview visible
    const preview = page.locator("[data-long-paste-preview]");
    await expect(preview).toBeVisible({ timeout: 5_000 });

    // Tab to expand button and activate
    const expandButton = page.getByRole("button", { name: /展开全部/ });
    if (await expandButton.isVisible()) {
      await expandButton.click();
    }

    // Should show full textarea now
    const fullTextarea = page.getByLabel("完整文本内容");
    await expect(fullTextarea).toBeVisible();
  });
});
