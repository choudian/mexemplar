import { expect, test } from "@playwright/test";

import { installMockApi } from "./mock-api";

test("T060 drives a teaching fixture through recording and intent handoff under five minutes", async ({ page }) => {
  const start = Date.now();
  const api = await installMockApi(page);
  await page.goto("/");
  await page.getByRole("button", { name: /工具教学/ }).click();

  await expect(page.getByRole("heading", { name: "浏览器", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "开始" }).first().click();
  await expect(page.getByRole("button", { name: "开始录制" })).toBeEnabled();

  await page.getByRole("button", { name: "开始录制" }).click();
  await expect(page.getByRole("alertdialog", { name: "录制隐私确认" })).toBeVisible();
  await page.getByRole("button", { name: "确认并开始录制" }).click();
  await expect(page.getByRole("button", { name: "停止录制" })).toBeVisible();
  await page.getByRole("button", { name: "停止录制" }).click();
  await page.locator(".teaching-composer textarea").first().fill("我想录制一个自动处理邮件的流程");
  await page.locator(".teaching-composer-send").first().click();
  await expect(page.locator(".teaching-user-bubble", { hasText: "我想录制一个自动处理邮件的流程" })).toBeVisible();
  expect(api.requests.some((request) => request.method === "POST" && request.path === "/api/teaching/runs/rec_1/intent/reply")).toBe(true);

  expect(Date.now() - start).toBeLessThan(300_000);
});
