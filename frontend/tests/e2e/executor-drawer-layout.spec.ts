import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test } from "@playwright/test";

/**
 * 详情抽屉的布局回归：标题区承载的是执行体的任务描述，而任务描述可能是
 * 整份任务书。曾经它不截断也不限高，把整个抽屉顶满，过程列表被挤出视口——
 * 用户点开子助手卡片只看得到一个超高标题和一个关闭按钮。
 *
 * jsdom 不算布局，这类问题只有真实浏览器量得出来，所以这里注入真实
 * theme.css 后量高度，而不是断言 class 名。
 */

const here = path.dirname(fileURLToPath(import.meta.url));
const themeCss = fs.readFileSync(path.resolve(here, "../../src/styles/theme.css"), "utf8");

/** 一份长到足以压垮标题区的任务描述（真机上是完整任务书）。 */
const LONG_TASK =
  "### 任务初书 - 对项目进行全面的模块分析，产出分析报告。需求：1）先探索项目目录结构；2）识别各模块；3）逐个分析职责、依赖、代码规模；4）梳理调用关系；5）汇总为结构化报告。".repeat(
    20,
  );

/** 复刻 ExecutorDrawer / SubagentDetailDrawer 共用的抽屉骨架。 */
const drawerMarkup = (task: string) => `
<div id="stage" style="position:relative;height:100vh">
  <div class="assistant-drawer-scrim">
    <aside class="assistant-drawer" role="dialog" aria-label="执行体详情：子助手">
      <header class="assistant-drawer-head">
        <div class="assistant-drawer-title">
          <svg width="16" height="16"></svg>
          <div>
            <strong>子助手</strong>
            <small title="${task.slice(0, 40)}">${task}</small>
          </div>
        </div>
        <button type="button" class="me-icon-button" aria-label="关闭">x</button>
      </header>
      <div class="assistant-drawer-body me-scroll">
        <p class="assistant-drawer-hint">这是它自己的完整过程，包含调用的工具和原文。</p>
        <ol class="assistant-steplist">
          ${Array.from({ length: 8 }, (_, i) => `<li class="assistant-step">步骤 ${i + 1}</li>`).join("")}
        </ol>
      </div>
    </aside>
  </div>
</div>`;

async function measure(page: import("@playwright/test").Page, task: string) {
  await page.setContent(drawerMarkup(task));
  await page.addStyleTag({ content: themeCss });
  return page.evaluate(() => {
    const rect = (sel: string) => document.querySelector(sel)!.getBoundingClientRect();
    const steps = rect(".assistant-steplist");
    return {
      drawerHeight: rect(".assistant-drawer").height,
      headHeight: rect(".assistant-drawer-head").height,
      bodyHeight: rect(".assistant-drawer-body").height,
      // 步骤列表真正落在视口内的高度：0 表示用户什么也看不到
      stepsVisibleHeight: Math.max(
        0,
        Math.min(steps.bottom, window.innerHeight) - Math.max(steps.top, 0),
      ),
    };
  });
}

test.describe("详情抽屉布局", () => {
  test("任务描述极长时，过程列表仍然可见", async ({ page }) => {
    const m = await measure(page, LONG_TASK);

    // 标题区不许吃掉整个抽屉
    expect(m.headHeight).toBeLessThan(m.drawerHeight / 2);
    // 过程列表必须真的看得见
    expect(m.stepsVisibleHeight).toBeGreaterThan(100);
    // body 拿到抽屉的绝大部分高度
    expect(m.bodyHeight).toBeGreaterThan(m.drawerHeight * 0.6);
  });

  test("任务描述很短时标题区不塌陷", async ({ page }) => {
    const m = await measure(page, "整理一下昨天的会议纪要");

    expect(m.headHeight).toBeGreaterThan(30);
    expect(m.stepsVisibleHeight).toBeGreaterThan(100);
  });

  test("关闭按钮停在抽屉顶部，不随标题变长下滑", async ({ page }) => {
    await page.setContent(drawerMarkup(LONG_TASK));
    await page.addStyleTag({ content: themeCss });
    const button = await page.locator(".assistant-drawer-head .me-icon-button").boundingBox();
    expect(button!.y).toBeLessThan(60);
  });
});
