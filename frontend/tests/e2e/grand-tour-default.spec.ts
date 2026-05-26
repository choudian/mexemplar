import { expect, test } from "@playwright/test";

import { installMockApi } from "./mock-api";

test("default E2E remains mock-backed and real-tour opt-in is absent", async ({ page }) => {
  const harness = await installMockApi(page);

  expect(process.env.MEXEMPLAR_REAL_GRAND_TOUR).not.toBe("1");
  await page.goto("/");
  await expect(page.getByRole("status")).toContainText(/ready|已就绪/i);

  await page.getByRole("button", { name: /AI 助手/ }).click();
  await page.getByLabel("输入消息").fill("default mock request");
  await page.getByRole("button", { name: "发送" }).click();
  await expect(page.getByLabel("输入消息")).toHaveValue("");

  expect(harness.requests.some((request) => request.path.startsWith("/api/settings/secrets/"))).toBe(false);
});
