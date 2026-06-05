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
  // 发送后进入运行态（草稿已派发）：发送按钮切为停止，输入进入排队态
  await expect(page.getByRole("button", { name: "停止" })).toBeVisible();
  await expect(page.getByLabel("排队下一条消息")).toHaveValue("");

  expect(Date.now() - start).toBeLessThan(120_000);
});

test("US1 运行期发送按钮变停止，点停止调用停止端点并保留已产内容", async ({ page }) => {
  const harness = await installMockApi(page);
  await page.goto("/");

  await expect(page.getByText("E2E conversation")).toBeVisible();
  await page.getByRole("button", { name: /E2E conversation/ }).click();
  await expect(page.getByRole("heading", { name: "Ready" })).toBeVisible();

  await page.getByLabel("输入消息").fill("跑一个会持续一会的任务");
  await page.getByRole("button", { name: "发送" }).click();

  // 运行期：发送按钮切为"停止"（输入门控，无法再发新消息）
  const stopButton = page.getByRole("button", { name: "停止" });
  await expect(stopButton).toBeVisible();
  await expect(page.getByRole("button", { name: "发送" })).toHaveCount(0);

  // 点停止 → 进入"停止中"反馈 + 调用停止端点
  await stopButton.click();
  await expect(page.getByRole("button", { name: "停止" })).toHaveText(/停止中/);
  await expect
    .poll(() =>
      harness.requests.filter(
        (r) => r.method === "POST" && r.path === "/api/assistant/sessions/ast_1/stop",
      ).length,
    )
    .toBeGreaterThan(0);

  // 已产内容保留：此前的助理回复仍在对话历史中
  await expect(page.getByRole("heading", { name: "Ready" })).toBeVisible();
});

test("US2 运行期可排队下一条，回车进入排队态", async ({ page }) => {
  await installMockApi(page);
  await page.goto("/");

  await page.getByRole("button", { name: /E2E conversation/ }).click();
  await expect(page.getByRole("heading", { name: "Ready" })).toBeVisible();

  await page.getByLabel("输入消息").fill("第一条任务");
  await page.getByRole("button", { name: "发送" }).click();

  // 运行期：出现排队输入框（整框进入编辑态）
  const queueBox = page.getByLabel("排队下一条消息");
  await expect(queueBox).toBeVisible();
  await queueBox.fill("先想好的下一句");
  await queueBox.press("Enter");

  // 回车后进入"排队态"
  await expect(page.getByText(/已排队/)).toBeVisible();
});

test("US4/US5 子任务卡片权威恢复，已暂停可继续任务", async ({ page }) => {
  const harness = await installMockApi(page);
  // 贴合真实契约：真实会话必由 user 消息发起，重开会话由 listSubagents 把卡片恢复到对应回合（FR-025）。
  // 真实后端 build_subagent_list 必返回 turnStartSequence；共享夹具缺它会让卡片 fallback 到无消息锚点的
  // 合成 turn 而不渲染，故在本用例内按真实形态覆盖这两个端点（POST 仍回退共享 mock 以保留请求记录）。
  await page.route(/\/api\/assistant\/sessions\/ast_1\/messages/, async (route) => {
    if (route.request().method() !== "GET") {
      await route.fallback();
      return;
    }
    await route.fulfill({
      status: 200,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        items: [
          {
            sequence: 1,
            role: "user",
            content: "请帮我开始这个任务",
            createdAt: new Date().toISOString(),
            rendering: "plain_text",
          },
          {
            sequence: 2,
            role: "assistant",
            content: "### Ready",
            createdAt: new Date().toISOString(),
            rendering: "safe_markdown",
          },
        ],
        hasMoreBefore: false,
        nextBeforeSequence: null,
      }),
    });
  });
  await page.route(/\/api\/assistant\/sessions\/ast_1\/subagents/, async (route) => {
    await route.fulfill({
      status: 200,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        items: [
          {
            subagentId: "sub_1",
            label: "子助手",
            task: "检索季度报表",
            status: "suspended",
            lastOutput: "已检索到部分数据",
            turnStartSequence: 1,
          },
        ],
      }),
    });
  });
  await page.goto("/");

  await page.getByRole("button", { name: /E2E conversation/ }).click();
  await expect(page.getByRole("heading", { name: "Ready" })).toBeVisible();

  // 子任务卡片由权威端点（listSubagents）恢复，显示"已暂停"
  await expect(page.getByText("已暂停")).toBeVisible();
  await expect(page.getByText("检索季度报表")).toBeVisible();

  // 点"继续任务"→ 填补充（留空）→ 继续：经主助理消息派发续跑
  await page.getByRole("button", { name: "继续任务" }).click();
  await page.getByRole("button", { name: "继续" }).click();

  await expect
    .poll(() =>
      harness.requests.filter(
        (r) => r.method === "POST" && r.path === "/api/assistant/sessions/ast_1/messages",
      ).length,
    )
    .toBeGreaterThan(0);
});
