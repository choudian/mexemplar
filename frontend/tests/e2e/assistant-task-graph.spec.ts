import { expect, test } from "@playwright/test";

import { installMockApi } from "./mock-api";

test("task graph snapshot renders and expands from mock API", async ({ page }) => {
  await installMockApi(page);
  await page.goto("/");

  await page.getByRole("button", { name: /E2E conversation/ }).click();

  await expect(page.getByLabel("任务进度")).toContainText("整理报销");
  await expect(page.getByLabel("任务进度")).toContainText("核对发票");
  await page.getByRole("button", { name: "展开任务详情" }).click();
  await expect(page.getByText("整理本月报销并生成摘要")).toBeVisible();
  await expect(page.getByLabel("任务看板")).toContainText("补充票据截图");
  await expect(page.getByLabel("私人清单")).toContainText("核对票据日期");
});
