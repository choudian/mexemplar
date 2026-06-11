import { expect, test } from "@playwright/test";

import { installMockApi } from "./mock-api";

test("T094 saves settings, masks secrets, shows validation, and runs visible actions", async ({ page }) => {
  await installMockApi(page);
  await page.goto("/");
  await page.getByRole("button", { name: /应用设置/ }).click();

  await expect(page.getByLabel("主模型")).toBeVisible();
  await page.getByLabel("请求超时").fill("0");
  await expect(page.getByText("不能小于 1。")).toBeVisible();
  await page.getByLabel("请求超时").fill("120");
  await page.getByLabel("主模型").fill("gpt-5.1");
  await page.getByRole("button", { name: /保存设置/ }).click();
  await expect(page.getByText("无未保存更改")).toBeVisible();

  await page.getByLabel("API Key").fill("sk-e2e-secret");
  await page.getByRole("button", { name: /保存密钥/ }).click();
  await expect(page.getByText("已保存")).toBeVisible();
  await expect(page.locator("body")).not.toContainText("sk-e2e-secret");

  await page.getByRole("tab", { name: "工具输出" }).click();
  await expect(page.getByLabel("触发字符数")).toBeHidden();
  await page.getByText("高级参数").click();
  await expect(page.getByLabel("触发字符数")).toBeVisible();
  await page.getByLabel("摘要模型").fill("summary-model");
  await page.getByRole("button", { name: /保存设置/ }).click();
  await page.getByLabel("摘要 API Key").fill("sk-summary-e2e");
  await page.getByRole("button", { name: /保存密钥/ }).click();
  await expect(page.locator("body")).not.toContainText("sk-summary-e2e");
  await page.getByRole("button", { name: /执行/ }).click();
  await expect(page.getByText("摘要模型连接成功。")).toBeVisible();
  await page.getByRole("button", { name: "删除密钥" }).click();
  await page.getByRole("button", { name: /执行/ }).click();
  await expect(page.getByText("缺少摘要 API Key。")).toBeVisible();

  const aboutTab = page.getByRole("tab", { name: "关于" });
  await aboutTab.focus();
  await page.keyboard.press("Enter");
  await aboutTab.click();
  await page.getByRole("button", { name: /执行/ }).click();
  await expect(page.getByText("当前构建未配置更新通道。")).toBeVisible();
});
