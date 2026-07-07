import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";

import type { SkillMethodologySummary } from "../../src/api/skillsMethodology";
import SkillCard from "../../src/components/SkillCard";

const skill: SkillMethodologySummary = {
  skill_id: "skill_alpha",
  name: "Alpha Method",
  description: "把复杂需求拆成可执行步骤",
  trigger_conditions: ["用户要求做 alpha", "需要拆解需求"],
  required_tools: ["tool_mail"],
  version: 3,
  chain_root_id: "skill_alpha",
  origin: "assistant_tool_call",
  is_protected: true,
  loaded_count: 9,
  referenced_count: 4,
  equipped_count: 2,
  last_referenced_at: "2026-06-30T00:00:00Z",
  created_at: "2026-06-01T00:00:00Z",
};

describe("SkillCard", () => {
  test("keeps methodology list cards focused on name and description", () => {
    const onOpen = vi.fn();

    render(<SkillCard onOpen={onOpen} selected skill={skill} />);

    fireEvent.click(screen.getByRole("button", { name: /Alpha Method/ }));

    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(screen.getByText("Alpha Method")).toBeInTheDocument();
    expect(screen.getByText("把复杂需求拆成可执行步骤")).toBeInTheDocument();
    expect(screen.queryByText("用户要求做 alpha")).not.toBeInTheDocument();
    expect(screen.queryByText("加载 9")).not.toBeInTheDocument();
    expect(screen.queryByText("装备 2")).not.toBeInTheDocument();
    expect(screen.queryByText("引用 4")).not.toBeInTheDocument();
    expect(screen.queryByText(/v3/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "打开" })).not.toBeInTheDocument();
  });
});
