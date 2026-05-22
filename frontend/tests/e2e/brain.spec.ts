import { expect, test } from "@playwright/test";

import { installMockApi } from "./mock-api";

test.describe("brain management", () => {
  test("opens brain zones and specialist management screens", async ({ page }) => {
    await installMockApi(page);

    await page.goto("/");
    await expect(page.locator('[data-testid="app-shell"]')).toBeVisible();

    await page.getByRole("button", { name: /大脑管理/ }).click();
    await expect(page.getByRole("heading", { name: "大脑管理" })).toBeVisible();
    await expect(page.getByRole("button", { name: /用户偏好先给结论/ })).toBeVisible();
    await expect(page.locator(".brain-entry-row small", { hasText: "多次对话沉淀" })).toBeVisible();

    await page.getByRole("button", { name: /专员管理/ }).click();
    await expect(page.getByRole("heading", { name: "专员管理" })).toBeVisible();
    await expect(page.getByText("报表专员")).toBeVisible();
    await page.getByRole("button", { name: "新建专员" }).click();
    await page.getByLabel("专员名称").fill("研究专员");
    await page.getByLabel("专员描述").fill("负责资料整理");
    await page.getByLabel("专员角色定义").fill("你负责整理研究资料。");
    await page.getByRole("button", { name: "保存专员" }).click();
  });
});
