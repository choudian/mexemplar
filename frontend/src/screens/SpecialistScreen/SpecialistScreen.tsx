import { Plus, Save, Search, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import type { BrainSpecialist } from "../../api/brain";
import { Badge, Button, IconButton } from "../../components/primitives";
import { useBrainStore } from "../../state/brainStore";
import { useSpecialistStore } from "../../state/specialistStore";
import AssistantEquipmentCard from "./AssistantEquipmentCard";
import EquipmentPanel from "./EquipmentPanel";

function originLabel(origin: string): string {
  if (origin === "auto_recruitment") return "自动招募";
  if (origin === "user_management_ui") return "手动创建";
  if (origin === "user_conversation") return "对话创建";
  return origin || "未知来源";
}

export function SpecialistScreen(): JSX.Element {
  const items = useSpecialistStore((state) => state.items);
  const selectedId = useSpecialistStore((state) => state.selectedId);
  const draft = useSpecialistStore((state) => state.draft);
  const skillPool = useBrainStore((state) => state.skillPool);
  const versions = useSpecialistStore((state) => state.versions);
  const loading = useSpecialistStore((state) => state.loading);
  const loadingSkillPool = useBrainStore((state) => state.loadingSkillPool);
  const saving = useSpecialistStore((state) => state.saving);
  const lastError = useSpecialistStore((state) => state.lastError);
  const load = useSpecialistStore((state) => state.load);
  const select = useSpecialistStore((state) => state.select);
  const setDraftField = useSpecialistStore((state) => state.setDraftField);
  const toggleWhitelist = useSpecialistStore((state) => state.toggleWhitelist);
  const saveDraft = useSpecialistStore((state) => state.saveDraft);
  const deleteById = useSpecialistStore((state) => state.deleteById);

  const loadSkillPool = useBrainStore((state) => state.loadSkillPool);

  const [query, setQuery] = useState("");

  useEffect(() => {
    void load();
    void loadSkillPool();
  }, [load, loadSkillPool]);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return items;
    return items.filter((item) =>
      [item.name, item.description, item.reason, item.role_definition]
        .some((value) => value.toLowerCase().includes(needle)),
    );
  }, [items, query]);

  return (
    <section className="specialist-screen" aria-label="专员管理">
      <header className="specialist-header">
        <div>
          <h2>专员管理</h2>
          <p>管理固定专员的职责、版本、可用工具白名单和方法论装备</p>
        </div>
        <Button kind="primary" onClick={() => select(null)}>
          <Plus size={14} />
          新建专员
        </Button>
      </header>

      <AssistantEquipmentCard />

      <div className="specialist-workspace">
        <aside className="specialist-list-pane">
          <label className="brain-search">
            <Search size={14} />
            <input
              aria-label="搜索专员"
              onChange={(event) => setQuery(event.currentTarget.value)}
              placeholder="搜索专员"
              value={query}
            />
          </label>
          {loading ? <div className="brain-empty">正在加载专员</div> : null}
          <div className="specialist-list me-scroll">
            {filtered.map((item) => (
              <SpecialistRow
                item={item}
                key={item.specialist_id}
                onDelete={() => {
                  void deleteById(item.specialist_id);
                }}
                onSelect={() => select(item.specialist_id)}
                selected={item.specialist_id === selectedId}
              />
            ))}
            {!loading && filtered.length === 0 ? <div className="brain-empty">暂无专员</div> : null}
          </div>
        </aside>

        <main className="specialist-editor me-scroll">
          <div className="brain-section-title">
            <span>{draft.specialist_id ? "编辑专员" : "新建专员"}</span>
            {draft.specialist_id ? <Badge tone="neutral">v{versions[0]?.version ?? 1}</Badge> : null}
          </div>
          <div className="specialist-form-grid">
            <label>
              <span>名称</span>
              <input
                aria-label="专员名称"
                onChange={(event) => setDraftField("name", event.currentTarget.value)}
                value={draft.name}
              />
            </label>
            <label>
              <span>描述</span>
              <input
                aria-label="专员描述"
                onChange={(event) => setDraftField("description", event.currentTarget.value)}
                value={draft.description}
              />
            </label>
            <label className="specialist-full-field">
              <span>角色定义</span>
              <textarea
                aria-label="专员角色定义"
                onChange={(event) => setDraftField("role_definition", event.currentTarget.value)}
                value={draft.role_definition}
              />
            </label>
            {draft.specialist_id ? (
              <label className="specialist-full-field">
                <span>变更理由</span>
                <input
                  aria-label="专员变更理由"
                  onChange={(event) => setDraftField("change_reason", event.currentTarget.value)}
                  placeholder="说明这次调整的原因"
                  value={draft.change_reason}
                />
              </label>
            ) : null}
          </div>

          <section className="specialist-whitelist" aria-label="工具白名单">
            <div className="brain-section-title">
              <span>工具白名单</span>
              <small>{draft.tool_whitelist.length} 个已选</small>
            </div>
            {loadingSkillPool ? <div className="brain-empty">正在加载工具池</div> : null}
            <div className="specialist-skill-grid">
              {skillPool.map((skill) => {
                const checked =
                  draft.tool_whitelist.includes(skill.tool_id);
                return (
                  <label className="specialist-skill-option" data-active={checked} key={skill.tool_id}>
                    <input
                      checked={checked}
                      onChange={() => toggleWhitelist(skill.tool_id)}
                      type="checkbox"
                    />
                    <span>
                      <div className="tool-card-title">
                        <strong>{skill.name || skill.tool_id}</strong>
                        {skill.is_builtin ? <Badge tone="neutral">内置</Badge> : null}
                      </div>
                      <small>{skill.description || "无描述"}</small>
                    </span>
                  </label>
                );
              })}
              {!loadingSkillPool && skillPool.length === 0 ? <div className="brain-empty">暂无可授予工具</div> : null}
            </div>
          </section>

          {draft.specialist_id ? <EquipmentPanel entityId={draft.specialist_id} /> : null}

          <div className="specialist-editor-actions">
            <Button kind="primary" disabled={saving} onClick={() => {
              void saveDraft();
            }}>
              <Save size={14} />
              保存专员
            </Button>
            {draft.specialist_id ? (
              <Button kind="danger" onClick={() => {
                void deleteById(draft.specialist_id || "");
              }}>
                <Trash2 size={14} />
                删除专员
              </Button>
            ) : null}
          </div>

          <section className="specialist-version-panel" aria-label="版本历史">
            <div className="brain-section-title">
              <span>版本历史</span>
              <small>{versions.length} 条</small>
            </div>
            {versions.map((version) => (
              <div className="specialist-version-row" key={version.version_id}>
                <strong>v{version.version} · {version.name}</strong>
                <small>{version.change_reason || "无变更说明"}</small>
              </div>
            ))}
            {draft.specialist_id && versions.length === 0 ? <div className="brain-empty">暂无版本记录</div> : null}
          </section>
        </main>
      </div>
      {lastError ? <div className="brain-error">{lastError}</div> : null}
    </section>
  );
}

function SpecialistRow({
  item,
  selected,
  onSelect,
  onDelete,
}: {
  item: BrainSpecialist;
  selected: boolean;
  onSelect: () => void;
  onDelete: () => void;
}) {
  return (
    <article className="specialist-row" data-selected={selected}>
      <button onClick={onSelect} type="button">
        <span className="specialist-row-title">
          <strong>{item.name}</strong>
          <Badge tone={item.origin === "auto_recruitment" ? "ok" : "neutral"}>
            {originLabel(item.origin)}
          </Badge>
        </span>
        <small>{item.description || "无描述"}</small>
        <small>{item.reason || "无创建原因"}</small>
      </button>
      <IconButton label={`删除 ${item.name}`} onClick={onDelete}>
        <Trash2 size={14} />
      </IconButton>
    </article>
  );
}

export default SpecialistScreen;
