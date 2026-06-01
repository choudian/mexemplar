import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { configureDesktopApi } from "../../src/api/client";
import type { SkillPoolItem } from "../../src/api/brain";
import type { SkillDetail } from "../../src/api/skillsMethodology";
import { SkillEditor } from "../../src/screens/SkillMethodologyScreen/SkillEditor";
import { useSkillMethodologyStore } from "../../src/state/skillMethodologyStore";
import type { SkillEditDraft } from "../../src/state/skillMethodologyStore";

const testSkillPool: SkillPoolItem[] = [
  { tool_id: "tool_mail", name: "发送邮件", description: "发送邮件工具", is_builtin: false },
];

const detail: SkillDetail = {
  skill_id: "sk_alpha",
  name: "Alpha Method",
  description: "Alpha flow",
  trigger_conditions: ["用户要求做 alpha"],
  required_tools: ["tool_mail"],
  version: 1,
  chain_root_id: "sk_alpha",
  origin: "assistant_tool_call",
  is_protected: false,
  loaded_count: 0,
  referenced_count: 0,
  equipped_count: 1,
  last_referenced_at: null,
  created_at: "2026-05-20T00:00:00Z",
  body_markdown: "# Alpha",
  parent_skill_id: null,
  status: "active",
  source_segments: [],
};

const draft: SkillEditDraft = {
  skill_id: "sk_alpha",
  name: "Alpha Method",
  description: "Alpha flow",
  trigger_conditions: ["用户要求做 alpha"],
  required_tools: ["tool_mail"],
  body_markdown: "# Alpha",
  change_reason: "",
};

function resetStore(): void {
  useSkillMethodologyStore.setState({
    items: [],
    selectedSkillId: null,
    selectedDetail: null,
    editDraft: {
      skill_id: null,
      name: "",
      description: "",
      trigger_conditions: [""],
      required_tools: [],
      body_markdown: "",
      change_reason: "",
    },
    saving: false,
    lastError: null,
  });
}

describe("SkillEditor", () => {
  beforeEach(() => {
    configureDesktopApi({ baseUrl: "http://desktop.test", sessionToken: "token" });
    resetStore();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("validates required fields before saving", async () => {
    useSkillMethodologyStore.setState({
      editDraft: {
        ...draft,
        trigger_conditions: ["  "],
      },
    });

    expect(await useSkillMethodologyStore.getState().saveDraft()).toBe(false);
    expect(useSkillMethodologyStore.getState().lastError).toBe("名称、描述、触发条件和正文必须填写。");
  });

  test("blocks duplicate active names before calling the API", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    useSkillMethodologyStore.setState({
      items: [
        { ...detail, skill_id: "sk_alpha" },
        { ...detail, skill_id: "sk_beta", name: "Beta Method", chain_root_id: "sk_beta" },
      ],
      editDraft: {
        ...draft,
        name: " beta method ",
      },
    });

    expect(await useSkillMethodologyStore.getState().saveDraft()).toBe(false);
    expect(fetchMock).not.toHaveBeenCalled();
    expect(useSkillMethodologyStore.getState().lastError).toContain("sk_beta");
  });

  test("edits trigger list and toggles required tool checkboxes", () => {
    const onDraftField = vi.fn();
    render(
      <SkillEditor
        detail={detail}
        draft={draft}
        loadingSkillPool={false}
        onDraftField={onDraftField}
        onSave={vi.fn()}
        onSoftDelete={vi.fn()}
        saving={false}
        skillPool={testSkillPool}
      />,
    );

    fireEvent.change(screen.getByLabelText("触发条件 1"), { target: { value: "用户要求做 alpha 报表" } });
    expect(onDraftField).toHaveBeenCalledWith("trigger_conditions", ["用户要求做 alpha 报表"]);

    fireEvent.click(screen.getAllByRole("button", { name: "添加" })[0]);
    expect(onDraftField).toHaveBeenCalledWith("trigger_conditions", ["用户要求做 alpha", ""]);

    // required_tools 改为 checkbox — tool_mail 已在 draft 中故初始为 checked，取消勾选触发更新
    const toolCheckbox = screen.getByRole("checkbox");
    expect(toolCheckbox).toBeChecked();
    fireEvent.click(toolCheckbox);
    expect(onDraftField).toHaveBeenCalledWith("required_tools", []);
  });

  test("hides soft delete for protected bootstrap methodology", () => {
    render(
      <SkillEditor
        detail={{ ...detail, is_protected: true, origin: "system_bootstrap" }}
        draft={draft}
        loadingSkillPool={false}
        onDraftField={vi.fn()}
        onSave={vi.fn()}
        onSoftDelete={vi.fn()}
        saving={false}
        skillPool={testSkillPool}
      />,
    );

    expect(screen.queryByRole("button", { name: "软删除" })).not.toBeInTheDocument();
    expect(screen.getByText("受保护")).toBeInTheDocument();
  });
});
