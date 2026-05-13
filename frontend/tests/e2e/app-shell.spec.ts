import { expect, test } from "@playwright/test";

import { installMockApi } from "./mock-api";

test("T027 launches the redesigned shell, navigates five routes, and exposes custom chrome", async ({ page }) => {
  await installMockApi(page);
  await page.goto("/");

  await expect(page.getByRole("status")).toContainText("已就绪");
  await expect(page.getByRole("button", { name: "关闭窗口" })).toBeVisible();
  await expect(page.getByRole("button", { name: "最小化窗口" })).toBeVisible();
  await expect(page.getByRole("button", { name: "最大化或还原窗口" })).toBeVisible();

  await page.getByRole("button", { name: /技能教学/ }).click();
  await expect(page.getByRole("heading", { name: "技能教学" })).toBeVisible();
  await page.getByRole("button", { name: /技能列表/ }).click();
  await expect(page.getByRole("heading", { name: "技能列表" })).toBeVisible();
  await page.getByRole("button", { name: /技能组合/ }).click();
  await expect(page.getByRole("heading", { name: "技能组合" })).toBeVisible();
  await page.getByRole("button", { name: /应用设置/ }).click();
  await expect(page.getByRole("heading", { name: "应用设置" })).toBeVisible();
  await page.getByRole("button", { name: /AI 助手/ }).click();
  await expect(page.getByLabel("AI 助手")).toBeVisible();

  await page.keyboard.press("Tab");
  await expect(page.locator(":focus")).toBeVisible();
  await page.getByRole("button", { name: "关闭窗口" }).click();
  await page.getByRole("button", { name: "最小化窗口" }).click();
  await page.getByRole("button", { name: "最大化或还原窗口" }).click();
});
