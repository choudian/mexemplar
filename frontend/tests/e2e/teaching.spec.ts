import { expect, test } from "@playwright/test";

import { installMockApi } from "./mock-api";

test("T060 drives a teaching fixture through trial-ready state under five minutes", async ({ page }) => {
  const start = Date.now();
  await installMockApi(page);
  await page.goto("/");
  await page.getByRole("button", { name: /技能教学/ }).click();

  await expect(page.getByRole("heading", { name: "浏览器", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "开始" }).first().click();
  await expect(page.getByRole("button", { name: "开始录制" })).toBeEnabled();

  await page.getByRole("button", { name: "开始录制" }).click();
  await expect(page.getByRole("button", { name: "停止录制" })).toBeVisible();
  await page.getByRole("button", { name: "停止录制" }).click();
  await expect(page.getByRole("button", { name: "确认并学习" })).toBeEnabled();
  await page.getByRole("button", { name: "确认并学习" }).click();
  await expect(page.getByText("正在学习技能。")).toBeVisible();
  await page.getByRole("button", { name: "开始试用" }).click();
  await expect(page.getByText("正在验证技能。")).toBeVisible();

  expect(Date.now() - start).toBeLessThan(300_000);
});
