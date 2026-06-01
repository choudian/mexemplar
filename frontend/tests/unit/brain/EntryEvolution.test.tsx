import { render, screen } from "@testing-library/react";
import { describe, expect, test } from "vitest";

import EntryEvolution from "../../../src/screens/BrainScreen/EntryEvolution";
import type { BrainMemoryEntry } from "../../../src/api/brain";

function makeEntry(overrides: Partial<BrainMemoryEntry> = {}): BrainMemoryEntry {
  return {
    entry_id: "entry-1",
    zone: "hot",
    entry_type: "insight",
    content: "用户偏好简洁回复",
    status: "active",
    origin: "distillation",
    reason: "测试原因",
    scope: null,
    loaded_count: 0,
    referenced_count: 0,
    superseded_by: null,
    verification_checkpoint: null,
    verification_status: null,
    verification_rationale: null,
    created_at: null,
    updated_at: null,
    ...overrides,
  };
}

describe("EntryEvolution", () => {
  test("加载状态显示加载文案", () => {
    render(<EntryEvolution chain={[]} loading={true} />);
    expect(screen.getByText("正在加载演化链")).toBeTruthy();
  });

  test("非加载且链为空显示空态", () => {
    render(<EntryEvolution chain={[]} loading={false} />);
    expect(screen.getByText("选择条目查看演化链")).toBeTruthy();
  });

  test("渲染单条记录为 v1 初始版本", () => {
    const entry = makeEntry({ entry_id: "e1", content: "第一条内容" });
    render(<EntryEvolution chain={[entry]} loading={false} />);
    expect(screen.getByText("v1")).toBeTruthy();
    expect(screen.getByText("第一条内容")).toBeTruthy();
    expect(screen.getByText("初始版本")).toBeTruthy();
  });

  test("多条记录版本号递增", () => {
    const chain = [
      makeEntry({ entry_id: "e1", content: "内容v1" }),
      makeEntry({ entry_id: "e2", content: "内容v2" }),
      makeEntry({ entry_id: "e3", content: "内容v3" }),
    ];
    render(<EntryEvolution chain={chain} loading={false} />);
    expect(screen.getByText("v1")).toBeTruthy();
    expect(screen.getByText("v2")).toBeTruthy();
    expect(screen.getByText("v3")).toBeTruthy();
  });

  test("statusTone: active 显示 ok tone", () => {
    const entry = makeEntry({ status: "active" });
    const { container } = render(<EntryEvolution chain={[entry]} loading={false} />);
    expect(container.querySelector(".me-badge-ok")).not.toBeNull();
  });

  test("statusTone: invalidated 显示 warn tone", () => {
    const entry = makeEntry({ status: "invalidated" });
    const { container } = render(<EntryEvolution chain={[entry]} loading={false} />);
    expect(container.querySelector(".me-badge-warn")).not.toBeNull();
  });

  test("statusTone: soft-deleted 显示 danger tone", () => {
    const entry = makeEntry({ status: "soft-deleted" });
    const { container } = render(<EntryEvolution chain={[entry]} loading={false} />);
    expect(container.querySelector(".me-badge-danger")).not.toBeNull();
  });

  test("changeHint: 内容变化时显示内容更新", () => {
    const chain = [
      makeEntry({ entry_id: "e1", content: "原始内容" }),
      makeEntry({ entry_id: "e2", content: "修改后内容" }),
    ];
    render(<EntryEvolution chain={chain} loading={false} />);
    expect(screen.getByText("内容更新")).toBeTruthy();
  });

  test("changeHint: scope 变化时显示适用范围调整", () => {
    const chain = [
      makeEntry({ entry_id: "e1", scope: "沟通" }),
      makeEntry({ entry_id: "e2", scope: "工作" }),
    ];
    render(<EntryEvolution chain={chain} loading={false} />);
    expect(screen.getByText("适用范围调整")).toBeTruthy();
  });

  test("changeHint: status 变化时显示状态变化", () => {
    const chain = [
      makeEntry({ entry_id: "e1", status: "active" }),
      makeEntry({ entry_id: "e2", status: "invalidated" }),
    ];
    render(<EntryEvolution chain={chain} loading={false} />);
    expect(screen.getByText(/状态变化/)).toBeTruthy();
  });

  test("changeHint: 无差异时显示无显著差异", () => {
    const base = makeEntry({ entry_id: "e1", content: "同内容", scope: "同范围", status: "active" });
    const same = makeEntry({ entry_id: "e2", content: "同内容", scope: "同范围", status: "active" });
    render(<EntryEvolution chain={[base, same]} loading={false} />);
    expect(screen.getByText("无显著差异")).toBeTruthy();
  });

  test("有 scope 时显示范围标签", () => {
    const entry = makeEntry({ scope: "沟通风格" });
    render(<EntryEvolution chain={[entry]} loading={false} />);
    expect(screen.getByText("范围：沟通风格")).toBeTruthy();
  });

  test("scope 为 null 时不显示范围标签", () => {
    const entry = makeEntry({ scope: null });
    render(<EntryEvolution chain={[entry]} loading={false} />);
    expect(screen.queryByText(/范围：/)).toBeNull();
  });
});
