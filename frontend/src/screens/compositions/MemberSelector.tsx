import { ArrowDown, ArrowUp, Plus, X } from "lucide-react";
import { useMemo, useState } from "react";

import type { CompositionMember, CompositionMode } from "../../api/compositions";
import type { SkillSummary } from "../../api/skills";
import { IconButton } from "../../components/primitives";

export function MemberSelector({
  mode,
  members,
  skills,
  onAdd,
  onMove,
  onRemove,
}: {
  mode: CompositionMode;
  members: CompositionMember[];
  skills: SkillSummary[];
  onAdd: (skill: SkillSummary) => void;
  onMove: (toolId: string, direction: "up" | "down") => void;
  onRemove: (toolId: string) => void;
}): JSX.Element {
  const [query, setQuery] = useState("");
  const hasMembers = members.length > 0;
  const availableSkills = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return skills;
    return skills.filter((skill) =>
      [skill.name, skill.description, skill.source]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(needle)),
    );
  }, [query, skills]);
  const orderedReady =
    mode !== "ordered" ||
    members.every((member, index) => member.executionOrder === index + 1 || member.executionOrder == null);
  const validationText = hasMembers
    ? mode === "ordered" && orderedReady
      ? "顺序完整"
      : "可用于范围组合"
    : "至少选择一个已掌握技能";

  return (
    <div className="composition-members">
      <div>
        <h3>成员技能</h3>
        <p className={hasMembers ? "composition-validation" : "composition-validation is-warning"}>
          {validationText}
        </p>
        <div className="composition-member-list">
          {members.length === 0 ? <span className="composition-muted">至少选择一个已掌握技能</span> : null}
          {members.map((member, index) => (
            <div className="composition-member-row" key={member.toolId}>
              <span>{member.name ?? member.toolId}</span>
              <small>{mode === "ordered" ? `顺序 ${member.executionOrder ?? "-"}` : `范围 ${member.selectedOrder}`}</small>
              {mode === "ordered" ? (
                <div className="composition-member-order">
                  <IconButton label="上移成员" disabled={index === 0} onClick={() => onMove(member.toolId, "up")}>
                    <ArrowUp size={14} />
                  </IconButton>
                  <IconButton
                    label="下移成员"
                    disabled={index === members.length - 1}
                    onClick={() => onMove(member.toolId, "down")}
                  >
                    <ArrowDown size={14} />
                  </IconButton>
                </div>
              ) : null}
              <IconButton label="移除成员" onClick={() => onRemove(member.toolId)}>
                <X size={14} />
              </IconButton>
            </div>
          ))}
        </div>
      </div>
      <div>
        <h3>已掌握技能</h3>
        <label className="composition-skill-search">
          <span>搜索成员技能</span>
          <input
            aria-label="搜索成员技能"
            value={query}
            onChange={(event) => setQuery(event.currentTarget.value)}
          />
        </label>
        <div className="composition-skill-pool">
          {availableSkills.length === 0 ? <span className="composition-muted">没有匹配的已掌握技能</span> : null}
          {availableSkills.map((skill) => (
            <button key={skill.toolId} type="button" onClick={() => onAdd(skill)}>
              <Plus size={14} />
              <span>{skill.name}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

export default MemberSelector;
