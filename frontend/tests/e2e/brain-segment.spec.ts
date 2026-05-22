import { test, expect } from "@playwright/test";
import { installMockApi } from "./mock-api";

test.describe("Assistant reconnect context", () => {
  test("seals the active assistant session before creating a new conversation", async ({ page }) => {
    const harness = await installMockApi(page);

    await page.goto("/");
    await expect(page.locator('[data-testid="app-shell"]')).toBeVisible();
    await expect(page.getByText("E2E conversation")).toBeVisible();

    await page.getByRole("button", { name: /E2E conversation/ }).click();
    await expect(page.getByRole("heading", { name: "Ready" })).toBeVisible();
    await page.getByRole("button", { name: "新对话" }).click();

    await expect
      .poll(() => harness.requests.some((request) => {
        const body = request.body as { session_id?: string; reason?: string } | undefined;
        return request.method === "POST"
          && request.path === "/api/assistant/segment-boundary"
          && body?.session_id === "ast_1"
          && body?.reason === "new_session";
      }))
      .toBe(true);
  });

  test("renders persisted brain zone entries in the management screen", async ({ page }) => {
    await installMockApi(page);

    await page.goto("/");
    await expect(page.locator('[data-testid="app-shell"]')).toBeVisible();

    await page.getByRole("button", { name: /大脑管理/ }).click();
    await expect(page.getByRole("heading", { name: "大脑管理" })).toBeVisible();
    await expect(page.getByRole("button", { name: /热区/ })).toBeVisible();
    await expect(page.getByRole("button", { name: /用户偏好先给结论/ })).toBeVisible();
    await expect(page.locator(".brain-entry-row small", { hasText: "多次对话沉淀" })).toBeVisible();
  });
});
