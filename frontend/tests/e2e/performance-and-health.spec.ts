import { expect, test } from "@playwright/test";

import { installMockApi } from "./mock-api";

test("T106 reaches interactive ready state within the launch budget", async ({ page }) => {
  const start = Date.now();
  await installMockApi(page);
  await page.goto("/");
  await expect(page.getByRole("status")).toContainText("已就绪");
  await expect(page.getByLabel("AI 助手")).toBeVisible();
  expect(Date.now() - start).toBeLessThan(15_000);
});

test("T106 surfaces degraded, failed, and shutdown backend states", async ({ browser }) => {
  for (const [status, label] of [
    ["degraded", "部分可用"],
    ["failed", "连接失败"],
    ["shutting_down", "关闭中"],
  ] as const) {
    const page = await browser.newPage();
    await installMockApi(page, { backendStatus: status, backendMessage: `Fixture ${status}` });
    await page.goto("/");
    await expect(page.getByRole("status")).toContainText(label);
    await page.close();
  }
});
