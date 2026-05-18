import { expect, test } from "@playwright/test";

/** 每个主要操作之间的停顿时间（毫秒），通过 GRAND_TOUR_DELAY 环境变量配置 */
const S = Number(process.env.GRAND_TOUR_DELAY ?? "0");
const pause = (ms?: number) => (ms ?? S) > 0 ? page.waitForTimeout(ms ?? S) : Promise.resolve();
let page: import("@playwright/test").Page;

/**
 * Grand Tour 全栈 E2E 测试
 *
 * 模拟一个真实用户从启动应用到完成所有主流程的完整旅程。
 * 前端直连真实 Python 后端，所有操作经过完整的 UI → API → 数据库链路。
 */
test("Grand Tour: 用户完成全流程操作", async ({ page: p }) => {
  page = p;

  // ═══════════════════════════════════════════════════════════
  // TC-GT-001 用户启动应用确认就绪
  // ═══════════════════════════════════════════════════════════
  await page.goto("/");
  await page.bringToFront();
  await expect(page.getByRole("status")).toContainText("已就绪", { timeout: 30_000 });

  await expect(page.getByRole("button", { name: /AI 助手/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /技能教学/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /技能列表/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /技能组合/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /应用设置/ })).toBeVisible();

  await expect(page.getByLabel("AI 助手")).toBeVisible();
  await pause();

  // ═══════════════════════════════════════════════════════════
  // TC-GT-002 用户浏览已有技能
  // ═══════════════════════════════════════════════════════════
  await page.getByRole("button", { name: /技能列表/ }).click();
  await expect(page.getByRole("heading", { name: "技能列表" })).toBeVisible();

  // 待考核分类（默认）：等待数据加载后看到种子数据中的技能
  await expect(page.getByText("数据清洗")).toBeVisible({ timeout: 10_000 });
  await pause();

  // 切换到"已掌握"分类
  await page.getByRole("tab", { name: /已掌握/ }).click();
  await expect(page.getByText("邮件分类")).toBeVisible({ timeout: 10_000 });
  await expect(page.getByText("报告生成")).toBeVisible();
  await pause();

  // 切换到"失败记录"分类
  await page.getByRole("tab", { name: /失败记录/ }).click();
  await expect(page.getByText("旧版导入")).toBeVisible({ timeout: 10_000 });
  await pause();

  // 回到已掌握，试用一个技能
  await page.getByRole("tab", { name: /已掌握/ }).click();
  await page.getByRole("button", { name: "试用" }).first().click();
  await pause();

  // ═══════════════════════════════════════════════════════════
  // TC-GT-003 用户创建技能组合
  // ═══════════════════════════════════════════════════════════
  await page.getByRole("button", { name: /技能组合/ }).click();
  await expect(page.getByRole("heading", { name: "技能组合" })).toBeVisible();

  // 等待数据加载（初始为空列表）
  await expect(page.getByText("暂无组合")).toBeVisible({ timeout: 10_000 });
  await pause();

  // 点击新建组合
  await page.getByRole("button", { name: /新建组合/ }).first().click();
  await pause();

  // 填写组合信息
  await page.getByLabel("名称").fill("邮件处理工作流");
  await page.getByLabel("描述").fill("自动处理客户邮件并生成摘要报告");

  // 选择顺序型模式
  await page.getByLabel("模式").selectOption("ordered");

  // 等待已发布技能列表加载
  await expect(page.getByRole("button", { name: /邮件分类/ })).toBeVisible({ timeout: 10_000 });
  await pause();

  // 添加两个成员技能
  await page.getByRole("button", { name: /邮件分类/ }).click();
  await pause();
  await page.getByRole("button", { name: /报告生成/ }).click();

  // 验证成员已添加
  await expect(page.getByRole("button", { name: /AI 推荐顺序/ })).toBeVisible();

  // 填写适用场景
  await page.getByLabel("适用场景").fill("当需要自动处理客户邮件并生成摘要报告时使用此组合");
  await pause();

  // 保存草稿
  await page.getByRole("button", { name: "保存草稿" }).click();
  await expect(page.getByRole("button", { name: /邮件处理工作流/ })).toBeVisible({ timeout: 5_000 });
  await pause();

  // 发布
  await page.getByRole("button", { name: "发布" }).click();
  await pause(2000);

  // ═══════════════════════════════════════════════════════════
  // TC-GT-004 用户使用 AI 助手
  // ═══════════════════════════════════════════════════════════
  await page.getByRole("button", { name: /AI 助手/ }).click();

  // 等待会话列表加载，种子会话的标题是第一条用户消息的内容
  const sessionButton = page.getByRole("button", { name: /帮我整理一下今天的任务/ }).first();
  await expect(sessionButton).toBeVisible({ timeout: 10_000 });
  await pause();

  // 点击进入会话
  await sessionButton.click();

  // 看到历史消息
  await expect(page.getByText("你好！我是你的 AI 助手")).toBeVisible({ timeout: 10_000 });
  await pause();

  // 发送新消息
  await page.getByLabel("输入消息").fill("请帮我用邮件处理工作流处理今天的邮件");
  await pause();
  await page.getByRole("button", { name: "发送" }).click();

  // 验证消息已发送（输入框清空）
  await expect(page.getByLabel("输入消息")).toHaveValue("");
  await pause();

  // ═══════════════════════════════════════════════════════════
  // TC-GT-005 用户调整设置
  // ═══════════════════════════════════════════════════════════
  await page.getByRole("button", { name: /应用设置/ }).click();
  await expect(page.getByRole("heading", { name: "应用设置" })).toBeVisible();

  // 等待设置加载
  await expect(page.getByLabel("请求超时")).toBeVisible({ timeout: 10_000 });
  await pause();

  // 修改请求超时（受控 number 输入框需要逐字符输入）
  const timeoutInput = page.getByLabel("请求超时");
  await timeoutInput.click();
  await timeoutInput.press("Control+a");
  await timeoutInput.pressSequentially("30");
  await pause();

  // 保存设置
  await page.getByRole("button", { name: /保存设置/ }).click();
  await expect(page.getByText("无未保存更改")).toBeVisible({ timeout: 5_000 });
  await pause();

  // 输入 API Key
  await page.getByLabel("API Key").fill("sk-e2e-test-key-12345");
  await pause();
  await page.getByRole("button", { name: /保存密钥/ }).click();
  await expect(page.getByText("已保存")).toBeVisible({ timeout: 5_000 });

  // 验证密钥不在页面明文显示
  await expect(page.locator("body")).not.toContainText("sk-e2e-test-key-12345");
  await pause();

  // ═══════════════════════════════════════════════════════════
  // TC-GT-006 用户尝试教学新技能
  // ═══════════════════════════════════════════════════════════
  await page.getByRole("button", { name: /技能教学/ }).click();
  await expect(page.getByRole("heading", { name: "技能教学" })).toBeVisible();

  // 等待录制就绪信息加载
  await expect(page.getByText("浏览器录制")).toBeVisible({ timeout: 10_000 });
  await pause();

  // 点击开始
  await page.getByRole("button", { name: "开始" }).first().click();

  // 进入录制阶段
  await expect(page.getByRole("button", { name: "开始录制" })).toBeEnabled({ timeout: 5_000 });
  await pause();
  await page.getByRole("button", { name: "开始录制" }).click();

  // 看到录制中状态
  await expect(page.getByText("录制中")).toBeVisible();
  await pause();

  // 停止录制
  await page.getByRole("button", { name: "停止录制" }).click();

  // 进入意图理解阶段
  await expect(page.getByText("需求分析师")).toBeVisible({ timeout: 5_000 });
  await pause();

  // 在意图对话框中输入描述
  const composer = page.locator(".teaching-composer textarea").first();
  await composer.fill("我想录制一个自动处理邮件的流程");
  await pause();
  await page.locator(".teaching-composer-send").first().click();
  await pause();

  // ═══════════════════════════════════════════════════════════
  // TC-GT-007 跨屏切换验证
  // ═══════════════════════════════════════════════════════════
  await page.getByRole("button", { name: /AI 助手/ }).click();
  await expect(page.getByLabel("AI 助手")).toBeVisible();
  await expect(page.getByRole("button", { name: /帮我整理一下今天的任务/ }).first()).toBeVisible({ timeout: 10_000 });
  await pause();

  await page.getByRole("button", { name: /技能列表/ }).click();
  await expect(page.getByRole("heading", { name: "技能列表" })).toBeVisible();
  await page.getByRole("tab", { name: /已掌握/ }).click();
  await expect(page.getByText("邮件分类")).toBeVisible({ timeout: 10_000 });
  await pause();

  await page.getByRole("button", { name: /技能组合/ }).click();
  await expect(page.getByRole("heading", { name: "技能组合" })).toBeVisible();
  await pause();

  await page.getByRole("button", { name: /应用设置/ }).click();
  await expect(page.getByRole("heading", { name: "应用设置" })).toBeVisible();
  await expect(page.getByText("已保存")).toBeVisible({ timeout: 5_000 });
  await pause();

  await page.getByRole("button", { name: /AI 助手/ }).click();
  await expect(page.getByLabel("AI 助手")).toBeVisible();

  // 结束后停顿，让用户看到最终画面
  if (S > 0) await page.waitForTimeout(3000);
});
