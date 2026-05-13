import { expect, test } from "@playwright/test";

import { installMockApi } from "./mock-api";

test("T043 sends an assistant message through a controlled backend fixture under two minutes", async ({ page }) => {
  const start = Date.now();
  await installMockApi(page);
  await page.goto("/");

  await expect(page.getByText("E2E conversation")).toBeVisible();
  await page.getByRole("button", { name: /E2E conversation/ }).click();
  await expect(page.getByRole("heading", { name: "Ready" })).toBeVisible();

  await page.getByLabel("输入消息").fill("Continue the fixture run");
  await page.getByRole("button", { name: "发送" }).click();
  await expect(page.getByLabel("输入消息")).toHaveValue("");

  expect(Date.now() - start).toBeLessThan(120_000);
});
