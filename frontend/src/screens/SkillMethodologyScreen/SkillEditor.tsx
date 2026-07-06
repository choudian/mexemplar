import { ChevronDown, ChevronRight, Plus, Save, Trash2, X } from "lucide-react";
import { useEffect, useState } from "react";

import type { SkillPoolItem } from "../../api/brain";
import type { SkillDetail } from "../../api/skillsMethodology";
import SkillCheckboxGrid from "../../components/SkillCheckboxGrid";
import { Badge, Button, IconButton } from "../../components/primitives";
import type { SkillEditDraft } from "../../state/skillMethodologyStore";
import { useSkillMethodologyStore } from "../../state/skillMethodologyStore";
import { useSkillStoreStore } from "../../state/skillStoreStore";

function originLabel(origin: string): string {
  if (origin === "system_bootstrap") return "系统内置";
  if (origin === "user_edit") return "用户编辑";
  if (origin === "assistant_tool_call") return "Assistant 创建";
  if (origin === "specialist_tool_call") return "专员创建";
  if (origin === "external_import") return "外部导入";
  return origin || "未知来源";
}

function ExternalSourceStrip({ skillId }: { skillId: string }): JSX.Element | null {
  const installed = useSkillStoreStore((s) => s.installed);
  const loadInstalled = useSkillStoreStore((s) => s.loadInstalled);
  const uninstall = useSkillStoreStore((s) => s.uninstall);
  const [removing, setRemoving] = useState(false);

  useEffect(() => {
    void loadInstalled();
  }, [loadInstalled]);

  const install = installed.find((item) => item.skillId === skillId);
  if (!install) return null;
  const sourceLabel = install.sourceType === "skills_sh" ? "skills.sh" : "GitHub";
  return (
    <div className="methodology-external-strip">
      <Badge tone="neutral">来自 {sourceLabel}</Badge>
      <a href={install.sourceUrl} rel="noreferrer" target="_blank">
        {install.sourceRef}
      </a>
      <Button
        disabled={removing}
        kind="ghost"
        onClick={() => {
          void (async () => {
            setRemoving(true);
            try {
              await uninstall(install.installId);
              await useSkillMethodologyStore.getState().load();
              await useSkillMethodologyStore.getState().selectSkill(null);
            } finally {
              setRemoving(false);
            }
          })();
        }}
      >
        {removing ? "卸载中…" : "卸载"}
      </Button>
    </div>
  );
}

function EditableList({
  label,
  values,
  onChange,
}: {
  label: string;
  values: string[];
  onChange: (values: string[]) => void;
}): JSX.Element {
  const safeValues = values.length > 0 ? values : [""];
  return (
    <div className="methodology-list-editor">
      <div className="methodology-editor-label">
        <span>{label}</span>
        <Button kind="ghost" onClick={() => onChange([...safeValues, ""])}>
          <Plus size={13} />
          添加
        </Button>
      </div>
      {safeValues.map((value, index) => (
        <label className="methodology-list-editor-row" key={`${label}-${index}`}>
          <input
            aria-label={`${label} ${index + 1}`}
            onChange={(event) => {
              const next = [...safeValues];
              next[index] = event.currentTarget.value;
              onChange(next);
            }}
            value={value}
          />
          <IconButton
            label={`移除${label} ${index + 1}`}
            onClick={() => onChange(safeValues.filter((_, itemIndex) => itemIndex !== index))}
          >
            <X size={13} />
          </IconButton>
        </label>
      ))}
    </div>
  );
}

export function SkillEditor({
  detail,
  draft,
  saving,
  skillPool,
  loadingSkillPool,
  onDraftField,
  onSave,
  onSoftDelete,
}: {
  detail: SkillDetail | null;
  draft: SkillEditDraft;
  saving: boolean;
  skillPool: SkillPoolItem[];
  loadingSkillPool: boolean;
  onDraftField: <K extends keyof SkillEditDraft>(field: K, value: SkillEditDraft[K]) => void;
  onSave: () => void;
  onSoftDelete: () => void;
}): JSX.Element {
  const [toolsCollapsed, setToolsCollapsed] = useState(false);
  const [sourcesCollapsed, setSourcesCollapsed] = useState(false);

  if (!detail) {
    return <section className="methodology-editor-panel"><div className="brain-empty">选择一个方法论查看详情</div></section>;
  }

  return (
    <section className="methodology-editor-panel me-scroll" aria-label="方法论编辑器">
      <div className="brain-section-title">
        <span>编辑方法论</span>
        <Badge tone={detail.is_protected ? "warn" : "neutral"}>
          {detail.is_protected ? "受保护" : `v${detail.version}`}
        </Badge>
      </div>

      <div className="methodology-system-strip">
        <span>状态：{detail.status}</span>
        <span>来源：{originLabel(detail.origin)}</span>
        <span>版本：v{detail.version}{detail.parent_skill_id ? " (演进版本)" : " (初始版本)"}</span>
      </div>
      {detail.origin === "external_import" ? (
        <ExternalSourceStrip skillId={detail.skill_id} />
      ) : null}

      <div className="methodology-form-grid">
        <label>
          <span>名称</span>
          <input
            aria-label="方法论名称"
            onChange={(event) => onDraftField("name", event.currentTarget.value)}
            value={draft.name}
          />
        </label>
        <label>
          <span>描述</span>
          <input
            aria-label="方法论描述"
            onChange={(event) => onDraftField("description", event.currentTarget.value)}
            value={draft.description}
          />
        </label>
        <div className="methodology-full-field">
          <EditableList
            label="触发条件"
            onChange={(values) => onDraftField("trigger_conditions", values)}
            values={draft.trigger_conditions}
          />
        </div>
        <div className="methodology-full-field">
          <div className="methodology-list-editor">
            <button
              className="methodology-section-toggle"
              onClick={() => setToolsCollapsed((v) => !v)}
              type="button"
            >
              {toolsCollapsed ? <ChevronRight size={13} /> : <ChevronDown size={13} />}
              <span>所需工具</span>
              <small>{draft.required_tools.length} 个已选</small>
            </button>
            {!toolsCollapsed ? (
              <SkillCheckboxGrid
                emptyLabel="暂无可用工具"
                loading={loadingSkillPool}
                loadingLabel="正在加载工具"
                onToggle={(toolId) => {
                  const next = draft.required_tools.includes(toolId)
                    ? draft.required_tools.filter((id) => id !== toolId)
                    : [...draft.required_tools, toolId];
                  onDraftField("required_tools", next);
                }}
                selectedIds={draft.required_tools}
                skills={skillPool}
              />
            ) : null}
          </div>
        </div>
        <label className="methodology-full-field">
          <span>正文</span>
          <textarea
            aria-label="方法论正文"
            onChange={(event) => onDraftField("body_markdown", event.currentTarget.value)}
            value={draft.body_markdown}
          />
        </label>
        <label className="methodology-full-field">
          <span>变更原因</span>
          <input
            aria-label="方法论变更原因"
            onChange={(event) => onDraftField("change_reason", event.currentTarget.value)}
            placeholder="说明这次调整的原因"
            value={draft.change_reason}
          />
        </label>
      </div>

      <section className="methodology-source-panel" aria-label="素材来源">
        <button
          className="methodology-section-toggle"
          onClick={() => setSourcesCollapsed((v) => !v)}
          type="button"
        >
          {sourcesCollapsed ? <ChevronRight size={13} /> : <ChevronDown size={13} />}
          <span>素材来源</span>
          <small>{detail.source_segments.length} 条</small>
        </button>
        {!sourcesCollapsed ? (
          <>
            {detail.source_segments.map((source) => {
              const sourceDeleted = source.segment_status === "soft-deleted";
              return (
                <div className="methodology-source-row" data-deleted={sourceDeleted} key={source.segment_id}>
                  <strong>{source.source_zone} · {source.segment_id}</strong>
                  <small>{sourceDeleted ? "来源已删除" : source.segment_summary || "无摘要"}</small>
                </div>
              );
            })}
            {detail.source_segments.length === 0 ? <div className="brain-empty">暂无素材来源</div> : null}
          </>
        ) : null}
      </section>

      <div className="specialist-editor-actions">
        <Button disabled={saving} kind="primary" onClick={onSave}>
          <Save size={14} />
          保存为新版本
        </Button>
        {!detail.is_protected ? (
          <Button disabled={saving} kind="danger" onClick={onSoftDelete}>
            <Trash2 size={14} />
            软删除
          </Button>
        ) : null}
      </div>
    </section>
  );
}

export default SkillEditor;
