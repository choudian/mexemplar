import { Search, ShieldAlert, Trash2, X } from "lucide-react";
import { useMemo, useState } from "react";

import type { AffectedSpecialist, SkillPoolItem } from "../../api/brain";
import { Badge, Button, IconButton } from "../../components/primitives";

interface SkillPoolPanelProps {
  skills: SkillPoolItem[];
  loading: boolean;
  pendingRemoval: {
    toolId: string;
    affectedSpecialists: AffectedSpecialist[];
  } | null;
  onRemove: (toolId: string, force?: boolean) => void;
  onCancelPending: () => void;
}

export function SkillPoolPanel({
  skills,
  loading,
  pendingRemoval,
  onRemove,
  onCancelPending,
}: SkillPoolPanelProps): JSX.Element {
  const [query, setQuery] = useState("");
  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return skills;
    return skills.filter((skill) =>
      [skill.name, skill.description, skill.tool_id]
        .filter(Boolean)
        .some((value) => value.toLowerCase().includes(needle)),
    );
  }, [query, skills]);

  return (
    <section className="brain-skill-pool" aria-label="工具池">
      <div className="brain-section-title">
        <span>工具池</span>
        <small>{skills.length} 个可授予能力</small>
      </div>
      <label className="brain-search">
        <Search size={14} />
        <input
          aria-label="搜索工具池"
          onChange={(event) => setQuery(event.currentTarget.value)}
          placeholder="搜索工具"
          value={query}
        />
      </label>
      {pendingRemoval ? (
        <div className="brain-skill-conflict" role="alert">
          <div>
            <strong>工具正被专员使用</strong>
            <small>
              {pendingRemoval.affectedSpecialists
                .map((specialist) => specialist.name || specialist.specialist_id)
                .join("、") || "未知专员"}
            </small>
          </div>
          <div className="brain-row-actions">
            <Button kind="danger" onClick={() => onRemove(pendingRemoval.toolId, true)}>
              <ShieldAlert size={14} />
              强制移除
            </Button>
            <Button kind="secondary" onClick={onCancelPending}>
              <X size={14} />
              取消
            </Button>
          </div>
        </div>
      ) : null}
      {loading ? <div className="brain-empty">正在加载工具池</div> : null}
      <div className="brain-skill-list">
        {filtered.map((skill) => (
          <div className="brain-skill-row" key={skill.tool_id}>
            <div>
              <strong>{skill.name || skill.tool_id}</strong>
              {skill.is_builtin ? <Badge tone="neutral">内置</Badge> : null}
              <small>{skill.description || "无描述"}</small>
            </div>
            <div className="brain-row-actions">
              {!skill.is_builtin ? (
                <IconButton label={`移除 ${skill.name || skill.tool_id}`} onClick={() => onRemove(skill.tool_id)}>
                  <Trash2 size={14} />
                </IconButton>
              ) : null}
            </div>
          </div>
        ))}
        {!loading && filtered.length === 0 ? <div className="brain-empty">暂无匹配工具</div> : null}
      </div>
    </section>
  );
}

export default SkillPoolPanel;
