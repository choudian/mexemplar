import { expect, test } from "@playwright/test";

import { installMockApi } from "./mock-api";

test("T070 covers Skill Methodology navigation, edit, equipment, audit, and Tool regression smoke", async ({ page }) => {
  const api = await installMockApi(page);
  await page.goto("/");

  await expect(page.getByRole("status")).toContainText("已就绪");
  await expect(page.getByRole("button", { name: /工具教学/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /工具列表/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /工具组合/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /方法论/ })).toBeVisible();

  await page.getByLabel("输入消息").fill("把刚才处理邮件的流程做成方法论");
  await page.getByRole("button", { name: "发送" }).click();
  await expect(page.getByLabel("输入消息")).toHaveValue("");

  await page.getByRole("button", { name: "方法论", exact: true }).click();
  await expect(page.getByRole("heading", { name: "方法论", exact: true })).toBeVisible();
  const createdCard = page.locator(".methodology-card", { hasText: "E2E 新建方法论" });
  await expect(createdCard).toBeVisible();
  await createdCard.getByRole("button", { name: "打开" }).click();
  await expect(page.getByLabel("方法论名称")).toHaveValue("E2E 新建方法论");

  await page.getByLabel("方法论名称").fill("如何创建方法论");
  await page.getByRole("button", { name: "保存为新版本" }).click();
  await expect(page.getByText(/方法论名称已被占用.*sk_bootstrap/)).toBeVisible();

  await page.getByLabel("方法论名称").fill("E2E 更新方法论");
  await page.getByLabel("方法论描述").fill("编辑后的方法论说明");
  await page.getByRole("textbox", { name: "触发条件 1" }).fill("用户要求处理周期邮件并输出摘要");
  await page.getByLabel("方法论变更原因").fill("E2E edit reason");
  await page.getByRole("button", { name: "保存为新版本" }).click();

  await expect(page.locator(".methodology-card", { hasText: "E2E 更新方法论" })).toBeVisible();
  expect(api.requests.some((request) => request.method === "PUT" && request.path === "/api/skills/methodology/sk_created")).toBe(true);

  await page.getByRole("button", { name: "审计" }).click();
  await expect(page.getByText("E2E edit reason")).toBeVisible();
  await expect(page.getByText("报表专员")).toBeVisible();

  await page.getByRole("button", { name: /专员管理/ }).click();
  await expect(page.getByRole("heading", { name: "专员管理" })).toBeVisible();
  await expect(page.getByRole("button", { name: /创建方法论|新建方法论/ })).toHaveCount(0);
  await page.locator(".specialist-row", { hasText: "报表专员" }).locator("button").first().click();

  const equipmentPanel = page.getByRole("region", { name: "方法论装备" });
  await expect(equipmentPanel.getByText("warn 4096 / danger 8192")).toBeVisible();
  await expect(equipmentPanel.getByText("1 条已选")).toBeVisible();
  const beforeTokens = await equipmentPanel.locator(".token-budget-meter strong").textContent();
  await equipmentPanel
    .locator(".equipment-skill-option", { hasText: "如何创建方法论" })
    .locator("input")
    .evaluate((node) => (node as HTMLInputElement).click());
  await expect(equipmentPanel.getByText("2 条已选")).toBeVisible();
  await expect(equipmentPanel.locator(".token-budget-meter strong")).not.toHaveText(beforeTokens ?? "");
  await equipmentPanel.getByRole("button", { name: "保存装备" }).click();
  expect(api.requests.some((request) => request.method === "PUT" && request.path === "/api/specialists/spec_1/equipment")).toBe(true);

  await page.getByRole("button", { name: "方法论", exact: true }).click();
  const bootstrapCard = page.locator(".methodology-card", { hasText: "如何创建方法论" });
  await bootstrapCard.getByRole("button", { name: "打开" }).click();
  await expect(page.getByLabel("方法论编辑器").getByText("受保护")).toBeVisible();
  await expect(page.getByRole("button", { name: "软删除" })).toHaveCount(0);

  await page.getByRole("button", { name: /工具教学/ }).click();
  await expect(page.getByRole("heading", { name: "工具教学" })).toBeVisible();
  await page.getByRole("button", { name: /工具列表/ }).click();
  await expect(page.getByText("Pending Skill")).toBeVisible();
  await page.getByRole("button", { name: /工具组合/ }).click();
  await expect(page.getByRole("heading", { name: "工具组合" })).toBeVisible();
});
