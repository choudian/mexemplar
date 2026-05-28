import { expect, test } from "@playwright/test";

import { installMockApi } from "./mock-api";

// ── TC-GT-001: 启动应用确认就绪 ──────────────────────────────
test("TC-GT-001 启动应用确认就绪", async ({ page }) => {
  await installMockApi(page);

  await page.goto("/");
  await expect(page.getByRole("status")).toContainText(/已就绪|ready/i);

  // 验证左侧导航栏五个入口
  await expect(page.getByRole("button", { name: /AI 助手/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /技能教学/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /技能列表/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /技能组合/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /应用设置/ })).toBeVisible();

  // 默认显示 AI 助手页面，会话历史面板可见
  await expect(page.getByText("E2E conversation")).toBeVisible();
});

// ── TC-GT-002: 用户浏览已有技能 ──────────────────────────────
test("TC-GT-002 用户浏览已有技能", async ({ page }) => {
  await installMockApi(page);
  await page.goto("/");

  await page.getByRole("button", { name: /技能列表/ }).click();
  await expect(page.getByRole("heading", { name: "技能列表" })).toBeVisible();

  // 默认显示待考核
  await expect(page.getByRole("tab", { name: "待考核" })).toBeVisible();
  await expect(page.getByText("Pending Skill")).toBeVisible();

  // 切换到已掌握
  await page.getByRole("tab", { name: "已掌握" }).click();
  await expect(page.getByText("Published Skill")).toBeVisible();
  await expect(page.getByText("Second Skill")).toBeVisible();

  // 切换到失败记录
  await page.getByRole("tab", { name: "失败记录" }).click();
  await expect(page.getByText("Failed Skill")).toBeVisible();
});

// ── TC-GT-003: 用户创建技能组合 ──────────────────────────────
test("TC-GT-003 用户创建技能组合", async ({ page }) => {
  await installMockApi(page);
  await page.goto("/");

  await page.getByRole("button", { name: /技能组合/ }).click();
  await expect(page.getByRole("heading", { name: "技能组合" })).toBeVisible();

  await page.getByRole("button", { name: "新建组合", exact: true }).click();
  await page.getByLabel("名称").fill("邮件处理工作流");
  await page.getByLabel("描述").fill("自动处理客户邮件并生成摘要报告");
  await page.getByRole("button", { name: /保存草稿/ }).click();
  await page.getByRole("button", { name: /发布/ }).click();
});

// ── TC-GT-004: 用户使用 AI 助手 ──────────────────────────────
test("TC-GT-004 用户使用 AI 助手", async ({ page }) => {
  await installMockApi(page);
  await page.goto("/");

  await page.getByRole("button", { name: /AI 助手/ }).click();
  await expect(page.getByText("E2E conversation")).toBeVisible();
  await page.getByText("E2E conversation").click();
  await expect(page.getByText("Ready")).toBeVisible();

  await page.getByLabel("输入消息").fill("请处理这个受控测试任务");
  await page.getByRole("button", { name: "发送" }).click();
  await expect(page.getByLabel("输入消息")).toHaveValue("");
});

// ── TC-GT-005: 用户调整应用设置 ──────────────────────────────
test("TC-GT-005 用户调整应用设置", async ({ page }) => {
  await installMockApi(page);
  await page.goto("/");

  await page.getByRole("button", { name: /应用设置/ }).click();
  await expect(page.getByRole("heading", { name: "应用设置" })).toBeVisible();

  // 修改超时值
  const timeoutInput = page.getByLabel("请求超时");
  await timeoutInput.fill("60");
  await page.getByRole("button", { name: /保存/ }).click();

  // 保存密钥
  const apiKeyInput = page.getByLabel("API Key");
  await apiKeyInput.fill("sk-test-e2e-key");
  await page.getByRole("button", { name: /保存密钥/ }).click();
});

// ── TC-GT-006: 用户尝试教学新技能 ──────────────────────────────
test("TC-GT-006 用户尝试教学新技能", async ({ page }) => {
  await installMockApi(page);
  await page.goto("/");

  await page.getByRole("button", { name: /技能教学/ }).click();
  await page.getByRole("button", { name: "开始" }).first().click();
  await page.getByRole("button", { name: "开始录制" }).click();
  await page.getByRole("button", { name: "确认并开始录制" }).click();
  await expect(page.getByRole("button", { name: "停止录制" })).toBeVisible();
  await page.getByRole("button", { name: "停止录制" }).click();
});

// ── TC-GT-007: 跨屏切换验证 ──────────────────────────────
test("TC-GT-007 跨屏切换验证", async ({ page }) => {
  const api = await installMockApi(page);
  await page.goto("/");

  // 循环切换所有屏
  const screens = [/AI 助手/, /技能教学/, /技能列表/, /技能组合/, /应用设置/];
  for (const name of screens) {
    await page.getByRole("button", { name }).click();
    await page.waitForTimeout(500);
  }

  // 回到 AI 助手确认数据仍在
  await page.getByRole("button", { name: /AI 助手/ }).click();
  await expect(page.getByText("E2E conversation")).toBeVisible();

  expect(api.requests.some((request) => request.path.startsWith("/api/settings/secrets/"))).toBe(false);
  expect(process.env.MEXEMPLAR_REAL_GRAND_TOUR).not.toBe("1");
  expect(process.env.MEXEMPLAR_ALLOW_LIVE_CAPTURE).not.toBe("1");
});
