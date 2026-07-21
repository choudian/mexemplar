import { expect, test } from "@playwright/test";

import { installMockApi } from "./mock-api";

test("navigates to scheduling center and shows task list", async ({ page }) => {
  await installMockApi(page);
  await page.goto("/");

  await expect(page.getByRole("status")).toContainText("已就绪");

  // 导航到调度中心
  await page.getByRole("button", { name: /调度中心/ }).click();
  await expect(page.getByRole("heading", { name: "调度中心" })).toBeVisible();

  // 列表展示两条任务
  await expect(page.getByText("每天查竞品价格")).toBeVisible();
  await expect(page.getByText("整理周报")).toBeVisible();

  // 状态标签
  await expect(page.getByText("运行中").first()).toBeVisible();

  // 免确认标记（FR-019）
  await expect(page.getByText("已授权免确认")).toBeVisible();
});

test("expands task detail and shows run history", async ({ page }) => {
  await installMockApi(page);
  await page.goto("/scheduled");

  await expect(page.getByText("每天查竞品价格")).toBeVisible();

  // 展开详情
  await page
    .getByRole("button", { name: /展开任务执行记录/ })
    .first()
    .click();

  // 免确认授权区域
  await expect(page.getByText("免确认授权")).toBeVisible();
  await expect(page.getByText(/未开启/)).toBeVisible();
  await expect(page.getByRole("button", { name: "开启授权" })).toBeVisible();

  // 执行记录 — Badge 里的"成功"
  await expect(page.locator(".me-badge-ok", { hasText: "成功" })).toBeVisible();
});

test("unattended task detail shows close-unattended toggle", async ({
  page,
}) => {
  await installMockApi(page);
  await page.goto("/scheduled");

  await expect(page.getByText("整理周报")).toBeVisible();

  // 展开第二条（已授权免确认）
  const expandButtons = page.getByRole("button", { name: /展开任务执行记录/ });
  await expandButtons.nth(1).click();

  // 详情显示已开启 + 收回授权按钮
  await expect(page.getByText(/已开启/)).toBeVisible();
  await expect(page.getByRole("button", { name: "收回授权" })).toBeVisible();
});

test("resets the reused task session from expanded detail", async ({ page }) => {
  const api = await installMockApi(page);
  await page.goto("/scheduled");

  await page
    .getByRole("button", { name: /展开任务执行记录/ })
    .first()
    .click();
  await page.getByRole("button", { name: "重开一轮" }).click();

  await expect(page.getByText(/下一次会使用新会话/)).toBeVisible();
  await expect
    .poll(() =>
      api.requests.some(
        (request) =>
          request.method === "POST" &&
          request.path === "/api/scheduled-tasks/sch_e2e_1/reset-session",
      ),
    )
    .toBe(true);
});

test("pause button is visible for active tasks", async ({ page }) => {
  await installMockApi(page);
  await page.goto("/scheduled");

  await expect(page.getByText("每天查竞品价格")).toBeVisible();

  // active 任务有暂停按钮
  await expect(
    page.getByRole("button", { name: "暂停" }).first(),
  ).toBeVisible();

  // 所有任务都有"现在跑一次"和"删除"
  const fireButtons = page.getByRole("button", { name: "现在跑一次" });
  await expect(fireButtons.first()).toBeVisible();
});

test("empty state shows when no tasks exist", async ({ page }) => {
  await installMockApi(page);

  // Override the scheduled-tasks list to return empty
  await page.route("**/api/scheduled-tasks*", async (route) => {
    const url = new URL(route.request().url());
    if (
      url.pathname === "/api/scheduled-tasks" &&
      route.request().method() === "GET"
    ) {
      return route.fulfill({
        status: 200,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ items: [], total: 0, limit: 200, offset: 0 }),
      });
    }
    return route.fallback();
  });

  await page.goto("/scheduled");

  await expect(page.getByText("还没有定时任务")).toBeVisible();
  // 例句引导
  await expect(page.getByText(/现在就帮我看一下今天的会议安排/)).toBeVisible();
});
