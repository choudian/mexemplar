import { Play, Shuffle, UploadCloud, Wand2, Workflow } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import type { CompositionInput, CompositionMember, CompositionMode } from "../../api/compositions";
import type { SkillSummary } from "../../api/skills";
import { Button } from "../../components/primitives";
import MemberSelector, { SkillPicker } from "./MemberSelector";

const modeOptions: Array<{
  id: CompositionMode;
  title: string;
  description: string;
  icon: LucideIcon;
}> = [
  {
    id: "range",
    title: "范围型",
    description: "定义工具池，AI 自主选择调用，不限定顺序。",
    icon: Shuffle,
  },
  {
    id: "ordered",
    title: "顺序型",
    description: "按固定顺序执行，前一步输出作为后一步输入。",
    icon: Workflow,
  },
];

function CompositionEditor({
  draft,
  skills,
  busy,
  canPublish,
  onField,
  onMode,
  onAddMember,
  onMoveMember,
  onRemoveMember,
  onGenerateApplicability,
  onRecommendOrder,
  onSave,
  onPublish,
  onTrial,
}: {
  draft: CompositionInput;
  skills: SkillSummary[];
  busy: boolean;
  canPublish: boolean;
  onField: <K extends keyof CompositionInput>(key: K, value: CompositionInput[K]) => void;
  onMode: (mode: CompositionMode) => void;
  onAddMember: (member: CompositionMember) => void;
  onMoveMember: (toolId: string, direction: "up" | "down") => void;
  onRemoveMember: (toolId: string) => void;
  onGenerateApplicability: () => void;
  onRecommendOrder: () => void;
  onSave: () => void;
  onPublish: () => void;
  onTrial: () => void;
}): JSX.Element {
  const toggleMember = (skill: SkillSummary) => {
    const existing = draft.members.some((member) => member.toolId === skill.toolId);
    if (existing) {
      onRemoveMember(skill.toolId);
      return;
    }

    onAddMember({
      toolId: skill.toolId,
      name: skill.name,
      description: skill.description,
      selectedOrder: draft.members.length + 1,
    });
  };

  return (
    <section className="composition-editor">
      <div className="composition-editor-layout">
        <div className="composition-editor-main">
          <section className="composition-builder-card">
            <div className="composition-section-header">
              <div>
                <span>组合模式</span>
                <small>决定成员技能的调度方式</small>
              </div>
              <label className="composition-mode-select">
                模式
                <select value={draft.mode} onChange={(event) => onMode(event.currentTarget.value as CompositionMode)}>
                  <option value="range">范围型</option>
                  <option value="ordered">顺序型</option>
                </select>
              </label>
            </div>
            <div className="composition-mode-options">
              {modeOptions.map((option) => {
                const Icon = option.icon;
                const selected = draft.mode === option.id;
                return (
                  <button
                    className="composition-mode-option"
                    data-active={selected}
                    key={option.id}
                    onClick={() => onMode(option.id)}
                    type="button"
                  >
                    <span>
                      <Icon size={16} />
                    </span>
                    <div>
                      <strong>{option.title}</strong>
                      <small>{option.description}</small>
                    </div>
                  </button>
                );
              })}
            </div>
          </section>

          <MemberSelector
            mode={draft.mode}
            members={draft.members}
            busy={busy}
            onMove={onMoveMember}
            onRemove={onRemoveMember}
            onRecommendOrder={onRecommendOrder}
          />

          <section className="composition-builder-card">
            <div className="composition-section-header">
              <div>
                <span>基础信息</span>
                <small>用于 AI 判断何时使用该组合</small>
              </div>
            </div>
            <div className="composition-form-grid">
              <label>
                <span>名称</span>
                <input
                  aria-label="名称"
                  value={draft.name}
                  onChange={(event) => onField("name", event.currentTarget.value)}
                />
              </label>
              <label>
                <span>描述</span>
                <input
                  aria-label="描述"
                  value={draft.description}
                  onChange={(event) => onField("description", event.currentTarget.value)}
                />
              </label>
              <div className="composition-field composition-field-full">
                <div className="composition-field-label">
                  <label htmlFor="composition-applicability">适用场景</label>
                  <Button
                    disabled={busy || !draft.name.trim() || draft.members.length === 0}
                    kind="ghost"
                    onClick={onGenerateApplicability}
                  >
                    <Wand2 size={14} />
                    生成适用场景
                  </Button>
                </div>
                <textarea
                  id="composition-applicability"
                  value={draft.applicability}
                  onChange={(event) => onField("applicability", event.currentTarget.value)}
                />
              </div>
            </div>
          </section>

          <div className="composition-editor-actions">
            <Button
              disabled={busy || !draft.name.trim() || !draft.applicability.trim() || draft.members.length < 2}
              title={draft.members.length < 2 ? "技能组合至少要添加 2 个技能" : undefined}
              onClick={onSave}
            >
              保存草稿
            </Button>
            {draft.members.length < 2 ? (
              <small className="composition-editor-hint">技能组合至少要添加 2 个技能</small>
            ) : null}
            <Button disabled={busy || !canPublish} kind="secondary" onClick={onTrial}>
              <Play size={14} />
              试用
            </Button>
            <Button disabled={busy || !canPublish} kind="primary" onClick={onPublish}>
              <UploadCloud size={14} />
              发布
            </Button>
          </div>
        </div>

        <SkillPicker members={draft.members} skills={skills} onToggle={toggleMember} />
      </div>
    </section>
  );
}

export default CompositionEditor;
