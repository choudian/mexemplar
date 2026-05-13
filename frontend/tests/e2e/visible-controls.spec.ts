import { expect, test, type Page } from "@playwright/test";

import { installMockApi, type MockApiHarness } from "./mock-api";

function expectRequest(api: MockApiHarness, method: string, path: string) {
  expect(api.requests.some((request) => request.method === method && request.path === path)).toBe(true);
}

async function expectNamedButtons(page: Page) {
  const unnamedButtons = await page.locator("button").evaluateAll((buttons) =>
    buttons.filter((button) => !button.textContent?.trim() && !button.getAttribute("aria-label")).length,
  );
  expect(unnamedButtons).toBe(0);
}

test("T107 visible controls across five screens invoke real bridge paths or explicit unavailable states", async ({
  page,
}) => {
  const api = await installMockApi(page);
  await page.goto("/");

  await page.getByRole("button", { name: /AI 助手/ }).click();
  await expectNamedButtons(page);
  await page.getByRole("button", { name: "新对话" }).click();
  await page.getByLabel("搜索对话").fill("conversation");
  await page.getByRole("button", { name: /E2E conversation/ }).click();
  await page.getByLabel("输入消息").fill("control audit message");
  await page.getByRole("button", { name: "发送" }).click();
  await expect(page.getByRole("button", { name: "附件暂不可用" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "语音输入暂不可用" })).toBeDisabled();
  await page.getByRole("button", { name: "重命名对话" }).click();
  await page.getByLabel("会话标题").fill("Renamed audit conversation");
  await page.getByRole("button", { name: "保存标题" }).click();
  await page.getByRole("button", { name: "删除对话" }).click();
  expectRequest(api, "POST", "/api/assistant/sessions");
  expectRequest(api, "POST", "/api/assistant/sessions/ast_1/messages");
  expectRequest(api, "PATCH", "/api/assistant/sessions/ast_1");
  expectRequest(api, "DELETE", "/api/assistant/sessions/ast_1");

  await page.getByRole("button", { name: /技能教学/ }).click();
  await expectNamedButtons(page);
  await page.getByRole("button", { name: "开始" }).first().click();
  await page.getByRole("button", { name: "开始录制" }).click();
  await page.getByRole("button", { name: "停止录制" }).click();
  await page.getByLabel("补充意图说明").fill("Add a boundary for the workflow");
  await page.getByRole("button", { name: "发送说明" }).click();
  await page.getByRole("button", { name: "确认并学习" }).click();
  await page.getByRole("button", { name: "开始试用" }).click();
  expectRequest(api, "POST", "/api/teaching/runs");
  expectRequest(api, "POST", "/api/teaching/runs/rec_1/recording/start");
  expectRequest(api, "POST", "/api/teaching/runs/rec_1/recording/stop");
  expectRequest(api, "POST", "/api/teaching/runs/rec_1/intent/reply");
  expectRequest(api, "POST", "/api/teaching/runs/rec_1/intent/confirm");
  expectRequest(api, "POST", "/api/teaching/runs/rec_1/trial/start");

  await page.getByRole("button", { name: /技能列表/ }).click();
  await expectNamedButtons(page);
  await expect(page.getByText("Pending Skill")).toBeVisible();
  await page.getByRole("button", { name: "试用" }).click();
  await page.getByRole("button", { name: "删除技能" }).click();
  await page.getByRole("tab", { name: /已掌握/ }).click();
  await expect(page.getByText("Published Skill")).toBeVisible();
  await page.getByRole("tab", { name: /失败记录/ }).click();
  await expect(page.getByText("Failed Skill")).toBeVisible();
  await page.getByRole("button", { name: "重试" }).click();
  await page.getByRole("button", { name: "忽略失败" }).click();
  expectRequest(api, "POST", "/api/skills/tool_pending/trial");
  expectRequest(api, "DELETE", "/api/skills/tool_pending");
  expectRequest(api, "POST", "/api/skills/failures/wf_failed/retry");
  expectRequest(api, "POST", "/api/skills/failures/wf_failed/dismiss");

  await page.getByRole("button", { name: /技能组合/ }).click();
  await expectNamedButtons(page);
  await page.getByLabel("名称").fill("Audit composition");
  await page.getByLabel("描述").fill("Visible control audit");
  await page.getByLabel("模式").selectOption("ordered");
  await page.getByLabel("适用场景").fill("When a visible control audit needs ordered steps");
  await page.getByRole("button", { name: /Published Skill/ }).click();
  await page.getByRole("button", { name: /Second Skill/ }).click();
  await page.getByRole("button", { name: "下移成员" }).first().click();
  await page.getByRole("button", { name: "移除成员" }).first().click();
  await page.getByRole("button", { name: /Published Skill/ }).click();
  await page.getByRole("button", { name: "保存草稿" }).click();
  await page.getByRole("button", { name: "试用" }).click();
  await page.getByRole("button", { name: "发布" }).click();
  expectRequest(api, "POST", "/api/compositions");
  expectRequest(api, "POST", "/api/compositions/comp_1/trial");
  expectRequest(api, "POST", "/api/compositions/comp_1/publish");

  await page.getByRole("button", { name: /应用设置/ }).click();
  await expectNamedButtons(page);
  await page.getByLabel("请求超时").fill("120");
  await page.getByLabel("主模型").fill("gpt-5.1");
  await page.getByRole("button", { name: /保存设置/ }).click();
  await page.getByLabel("API Key").fill("sk-control-audit");
  await page.getByRole("button", { name: /保存密钥/ }).click();
  await page.getByRole("button", { name: "删除密钥" }).click();
  await page.getByRole("button", { name: /执行/ }).click();
  await page.getByRole("tab", { name: "关于" }).click();
  await page.getByRole("button", { name: /执行/ }).click();
  await expect(page.getByText("当前构建未配置更新通道。")).toBeVisible();
  expectRequest(api, "PATCH", "/api/settings/values");
  expectRequest(api, "POST", "/api/settings/secrets/ai.api_key");
  expectRequest(api, "DELETE", "/api/settings/secrets/ai.api_key");
  expectRequest(api, "POST", "/api/settings/actions/test_ai_connection");
  expectRequest(api, "POST", "/api/settings/actions/check_updates");
});
