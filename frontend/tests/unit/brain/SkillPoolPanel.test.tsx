import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";

import SkillPoolPanel from "../../../src/screens/BrainScreen/SkillPoolPanel";
import type { SkillPoolItem } from "../../../src/api/brain";

function makeSkill(overrides: Partial<SkillPoolItem> = {}): SkillPoolItem {
  return {
    tool_id: "tool-1",
    name: "测试工具",
    description: "一个工具",
    ...overrides,
  };
}

describe("SkillPoolPanel", () => {
  test("渲染工具列表", () => {
    render(
      <SkillPoolPanel
        loading={false}
        onCancelPending={vi.fn()}
        onRemove={vi.fn()}
        pendingRemoval={null}
        skills={[makeSkill({ tool_id: "t1", name: "工具A" }), makeSkill({ tool_id: "t2", name: "工具B" })]}
      />,
    );
    expect(screen.getByText("工具A")).toBeTruthy();
    expect(screen.getByText("工具B")).toBeTruthy();
  });

  test("搜索过滤：按名称过滤", () => {
    render(
      <SkillPoolPanel
        loading={false}
        onCancelPending={vi.fn()}
        onRemove={vi.fn()}
        pendingRemoval={null}
        skills={[makeSkill({ tool_id: "t1", name: "Excel工具" }), makeSkill({ tool_id: "t2", name: "邮件工具" })]}
      />,
    );
    fireEvent.change(screen.getByRole("textbox", { name: "搜索工具池" }), {
      target: { value: "Excel" },
    });
    expect(screen.getByText("Excel工具")).toBeTruthy();
    expect(screen.queryByText("邮件工具")).toBeNull();
  });

  test("搜索过滤：按描述过滤", () => {
    render(
      <SkillPoolPanel
        loading={false}
        onCancelPending={vi.fn()}
        onRemove={vi.fn()}
        pendingRemoval={null}
        skills={[makeSkill({ tool_id: "t1", name: "工具X", description: "处理报表" })]}
      />,
    );
    fireEvent.change(screen.getByRole("textbox", { name: "搜索工具池" }), {
      target: { value: "报表" },
    });
    expect(screen.getByText("工具X")).toBeTruthy();
  });

  test("搜索结果为空时显示空态", () => {
    render(
      <SkillPoolPanel
        loading={false}
        onCancelPending={vi.fn()}
        onRemove={vi.fn()}
        pendingRemoval={null}
        skills={[makeSkill({ tool_id: "t1", name: "工具A" })]}
      />,
    );
    fireEvent.change(screen.getByRole("textbox", { name: "搜索工具池" }), {
      target: { value: "不存在的关键词xyz" },
    });
    expect(screen.getByText("暂无匹配工具")).toBeTruthy();
  });

  test("点击移除按钮调用 onRemove", () => {
    const onRemove = vi.fn();
    render(
      <SkillPoolPanel
        loading={false}
        onCancelPending={vi.fn()}
        onRemove={onRemove}
        pendingRemoval={null}
        skills={[makeSkill({ tool_id: "tool-abc", name: "目标工具" })]}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "移除 目标工具" }));
    expect(onRemove).toHaveBeenCalledWith("tool-abc");
  });

  test("冲突解决 UI：显示受影响专员", () => {
    render(
      <SkillPoolPanel
        loading={false}
        onCancelPending={vi.fn()}
        onRemove={vi.fn()}
        pendingRemoval={{
          toolId: "tool-x",
          affectedSpecialists: [
            { specialist_id: "s1", name: "报表专员" },
            { specialist_id: "s2", name: "邮件专员" },
          ],
        }}
        skills={[makeSkill({ tool_id: "tool-x" })]}
      />,
    );
    const alert = screen.getByRole("alert");
    expect(within(alert).getByText(/报表专员/)).toBeTruthy();
    expect(within(alert).getByText(/邮件专员/)).toBeTruthy();
  });

  test("冲突解决 UI：强制移除调用 onRemove(toolId, true)", () => {
    const onRemove = vi.fn();
    render(
      <SkillPoolPanel
        loading={false}
        onCancelPending={vi.fn()}
        onRemove={onRemove}
        pendingRemoval={{
          toolId: "tool-x",
          affectedSpecialists: [{ specialist_id: "s1", name: "专员A" }],
        }}
        skills={[makeSkill({ tool_id: "tool-x" })]}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "强制移除" }));
    expect(onRemove).toHaveBeenCalledWith("tool-x", true);
  });

  test("冲突解决 UI：取消调用 onCancelPending", () => {
    const onCancelPending = vi.fn();
    render(
      <SkillPoolPanel
        loading={false}
        onCancelPending={onCancelPending}
        onRemove={vi.fn()}
        pendingRemoval={{
          toolId: "tool-x",
          affectedSpecialists: [],
        }}
        skills={[makeSkill({ tool_id: "tool-x" })]}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    expect(onCancelPending).toHaveBeenCalled();
  });

  test("加载状态显示加载文案", () => {
    render(
      <SkillPoolPanel
        loading={true}
        onCancelPending={vi.fn()}
        onRemove={vi.fn()}
        pendingRemoval={null}
        skills={[]}
      />,
    );
    expect(screen.getByText("正在加载工具池")).toBeTruthy();
  });

  test("技能数量显示在标题中", () => {
    render(
      <SkillPoolPanel
        loading={false}
        onCancelPending={vi.fn()}
        onRemove={vi.fn()}
        pendingRemoval={null}
        skills={[makeSkill({ tool_id: "t1" }), makeSkill({ tool_id: "t2" }), makeSkill({ tool_id: "t3" })]}
      />,
    );
    expect(screen.getByText("3 个可授予能力")).toBeTruthy();
  });
});
