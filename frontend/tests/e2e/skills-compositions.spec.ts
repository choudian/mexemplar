import { expect, test } from "@playwright/test";

import { installMockApi } from "./mock-api";

test("T076 inspects skill states and creates range plus ordered compositions", async ({ page }) => {
  await installMockApi(page);
  await page.goto("/");

  await page.getByRole("button", { name: /技能列表/ }).click();
  await expect(page.getByText("Pending Skill")).toBeVisible();
  await page.getByRole("tab", { name: /已掌握/ }).click();
  await expect(page.getByText("Published Skill")).toBeVisible();
  await page.getByRole("tab", { name: /失败记录/ }).click();
  await expect(page.getByText("Failed Skill")).toBeVisible();

  await page.getByRole("button", { name: /技能组合/ }).click();
  await expect(page.getByText("Published Skill")).toBeVisible();
  await page.getByLabel("名称").fill("Range fixture");
  await page.getByLabel("描述").fill("Range composition");
  await page.getByLabel("适用场景").fill("When any reusable skill can solve the task");
  await page.getByRole("button", { name: /Published Skill/ }).click();
  await page.getByRole("button", { name: "保存草稿" }).click();
  await expect(page.getByText("当前：Range fixture")).toBeVisible();

  await page.getByRole("button", { name: "新建" }).click();
  await page.getByLabel("名称").fill("Ordered fixture");
  await page.getByLabel("描述").fill("Ordered composition");
  await page.getByLabel("模式").selectOption("ordered");
  await page.getByLabel("适用场景").fill("When the steps must run in order");
  await page.getByRole("button", { name: /Published Skill/ }).click();
  await page.getByRole("button", { name: /Second Skill/ }).click();
  await page.getByRole("button", { name: "下移成员" }).first().click();
  await expect(page.getByText("顺序完整")).toBeVisible();
  await page.getByRole("button", { name: "保存草稿" }).click();
  await expect(page.getByText("当前：Ordered fixture")).toBeVisible();
});
