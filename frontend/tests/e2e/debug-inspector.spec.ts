import { expect, test } from "@playwright/test";

import { installMockApi } from "./mock-api";

test("Debug Inspector locates and expands a completed trace within the UX budget", async ({ page }) => {
  await installMockApi(page);

  const startedAt = Date.now();
  await page.goto("/debug");
  await expect(page.getByRole("heading", { name: "Debug Inspector" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "主导航" })).not.toContainText("Debug Inspector");

  await page.getByRole("checkbox", { name: /I understand the risks/ }).check();
  await page.getByRole("button", { name: "Enable Trace Capture" }).click();
  await expect(page.getByText("ARMED", { exact: true })).toBeVisible();

  const tracePanel = page.getByRole("region", { name: "LLM trace records" });
  await tracePanel.getByRole("button", { name: "Refresh" }).click();
  await expect(page.getByRole("button", { name: /agent_loop/ })).toBeVisible();
  await page.getByRole("button", { name: /agent_loop/ }).click();
  await expect(page.getByText("fixture answer")).toBeVisible();

  const flowPanel = page.getByRole("region", { name: "Agent flow timeline" });
  await flowPanel.getByRole("button", { name: "Refresh" }).click();
  await page.getByRole("button", { name: /wf_fixture/ }).click();
  await expect(
    flowPanel.getByLabel("Agent flow detail").getByText("assistant_delegation_completed"),
  ).toBeVisible();

  await page.getByLabel("Reference id").fill("REF::msg_1");
  await page.getByRole("button", { name: "Expand" }).click();
  await expect(page.getByText("fixture expanded reference")).toBeVisible();

  expect(Date.now() - startedAt).toBeLessThan(30_000);
});
