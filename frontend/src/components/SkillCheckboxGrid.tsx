import { useMemo } from "react";

import type { SkillPoolItem } from "../api/brain";
import { Badge } from "./primitives";

export function SkillCheckboxGrid({
  skills,
  selectedIds,
  loading = false,
  loadingLabel,
  emptyLabel,
  onToggle,
}: {
  skills: SkillPoolItem[];
  selectedIds: string[];
  loading?: boolean;
  loadingLabel: string;
  emptyLabel: string;
  onToggle: (toolId: string) => void;
}): JSX.Element {
  const selected = useMemo(() => new Set(selectedIds), [selectedIds]);

  return (
    <>
      {loading ? <div className="brain-empty">{loadingLabel}</div> : null}
      <div className="specialist-skill-grid">
        {skills.map((skill) => {
          const checked = selected.has(skill.tool_id);
          return (
            <label className="specialist-skill-option" data-active={checked} key={skill.tool_id}>
              <input
                checked={checked}
                onChange={() => onToggle(skill.tool_id)}
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
        {!loading && skills.length === 0 ? <div className="brain-empty">{emptyLabel}</div> : null}
      </div>
    </>
  );
}

export default SkillCheckboxGrid;
