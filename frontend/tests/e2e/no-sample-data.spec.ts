import { expect, test, type Page } from "@playwright/test";

import { installMockApi } from "./mock-api";

const forbiddenPrototypeText = [
  "TODO",
  "scaffolded",
  "示例数据",
  "样例数据",
  "Lorem ipsum",
  "placeholder",
  "fake count",
  "mock state",
];

async function expectNoPrototypeText(page: Page) {
  const body = page.locator("body");
  for (const text of forbiddenPrototypeText) {
    await expect(body).not.toContainText(text);
  }
}

test("T105 normal primary-screen states do not expose prototype sample data or fake counts", async ({ page }) => {
  await installMockApi(page);
  await page.goto("/");

  await expect(page.getByRole("button", { name: /工具列表/ })).toBeVisible();
  for (const route of [/AI 助手/, /工具教学/, /工具列表/, /工具组合/, /大脑管理/, /专员管理/, /方法论/, /应用设置/]) {
    await page.getByRole("button", { name: route }).click();
    await expectNoPrototypeText(page);
  }
});

test("T105 empty and degraded states stay product-specific without sample records", async ({ page }) => {
  await installMockApi(page, {
    backendStatus: "degraded",
    backendMessage: "Fixture degraded backend.",
  });
  await page.goto("/");

  await expect(page.getByRole("status")).toContainText("部分可用");
  await page.getByRole("button", { name: /工具组合/ }).click();
  await expect(page.getByText("暂无组合")).toBeVisible();
  await expectNoPrototypeText(page);
});

test("T105 failed backend state is recoverable UI copy, not scaffold data", async ({ page }) => {
  await installMockApi(page, {
    backendStatus: "failed",
    backendMessage: "Fixture failed backend.",
  });
  await page.goto("/");

  await expect(page.getByRole("status")).toContainText("失败");
  await expectNoPrototypeText(page);
});
