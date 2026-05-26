import { expect, test } from "@playwright/test";

import { installMockApi } from "./mock-api";

test("Grand Tour default suite remains controlled, cost-free, and capture-free", async ({ page }) => {
  const api = await installMockApi(page);

  await page.goto("/");
  await expect(page.getByRole("status")).toContainText(/已就绪|ready/i);

  await page.getByRole("button", { name: /AI 助手/ }).click();
  await page.getByLabel("输入消息").fill("请处理这个受控测试任务");
  await page.getByRole("button", { name: "发送" }).click();

  await page.getByRole("button", { name: /技能教学/ }).click();
  await page.getByRole("button", { name: "开始" }).first().click();
  await page.getByRole("button", { name: "开始录制" }).click();
  await page.getByRole("button", { name: "确认并开始录制" }).click();
  await expect(page.getByRole("button", { name: "停止录制" })).toBeVisible();
  await page.getByRole("button", { name: "停止录制" }).click();

  await page.getByRole("button", { name: /技能列表/ }).click();
  await expect(page.getByRole("heading", { name: "技能列表" })).toBeVisible();
  await page.getByRole("button", { name: /技能组合/ }).click();
  await expect(page.getByRole("heading", { name: "技能组合" })).toBeVisible();
  await page.getByRole("button", { name: /应用设置/ }).click();
  await expect(page.getByRole("heading", { name: "应用设置" })).toBeVisible();

  expect(api.requests.some((request) => request.path.startsWith("/api/settings/secrets/"))).toBe(false);
  expect(process.env.MEXEMPLAR_REAL_GRAND_TOUR).not.toBe("1");
  expect(process.env.MEXEMPLAR_ALLOW_LIVE_CAPTURE).not.toBe("1");
});
