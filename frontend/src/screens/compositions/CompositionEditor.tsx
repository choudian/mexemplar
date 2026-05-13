import type { CompositionInput, CompositionMember, CompositionMode } from "../../api/compositions";
import type { SkillSummary } from "../../api/skills";
import { Button } from "../../components/primitives";
import MemberSelector from "./MemberSelector";

export function CompositionEditor({
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
  return (
    <section className="composition-editor">
      <div className="composition-form-grid">
        <label>
          名称
          <input value={draft.name} onChange={(event) => onField("name", event.currentTarget.value)} />
        </label>
        <label>
          模式
          <select value={draft.mode} onChange={(event) => onMode(event.currentTarget.value as CompositionMode)}>
            <option value="range">范围型</option>
            <option value="ordered">顺序型</option>
          </select>
        </label>
        <label>
          描述
          <input
            value={draft.description}
            onChange={(event) => onField("description", event.currentTarget.value)}
          />
        </label>
        <label>
          适用场景
          <textarea
            value={draft.applicability}
            onChange={(event) => onField("applicability", event.currentTarget.value)}
          />
        </label>
      </div>
      <div className="composition-helper-actions">
        <Button disabled={busy || !draft.name.trim() || draft.members.length === 0} kind="secondary" onClick={onGenerateApplicability}>
          生成适用场景
        </Button>
        <Button disabled={busy || draft.mode !== "ordered" || draft.members.length < 2} kind="secondary" onClick={onRecommendOrder}>
          推荐顺序
        </Button>
      </div>
      <MemberSelector
        mode={draft.mode}
        members={draft.members}
        skills={skills}
        onAdd={(skill) =>
          onAddMember({
            toolId: skill.toolId,
            name: skill.name,
            description: skill.description,
            selectedOrder: draft.members.length + 1,
          })
        }
        onMove={onMoveMember}
        onRemove={onRemoveMember}
      />
      <div className="composition-editor-actions">
        <Button disabled={busy || !draft.name.trim() || !draft.applicability.trim()} onClick={onSave}>
          保存草稿
        </Button>
        <Button disabled={busy || !canPublish} kind="secondary" onClick={onTrial}>
          试用
        </Button>
        <Button disabled={busy || !canPublish} kind="primary" onClick={onPublish}>
          发布
        </Button>
      </div>
    </section>
  );
}

export default CompositionEditor;
