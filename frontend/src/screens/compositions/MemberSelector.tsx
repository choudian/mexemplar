import { ArrowDown, ArrowUp, Bolt, Check, Plus, Search, Wand2, X } from "lucide-react";
import { useMemo, useState } from "react";

import type { CompositionMember, CompositionMode } from "../../api/compositions";
import type { SkillSummary } from "../../api/skills";
import { Button, IconButton } from "../../components/primitives";

function MemberSelector({
  mode,
  members,
  busy,
  onMove,
  onRemove,
  onRecommendOrder,
}: {
  mode: CompositionMode;
  members: CompositionMember[];
  busy: boolean;
  onMove: (toolId: string, direction: "up" | "down") => void;
  onRemove: (toolId: string) => void;
  onRecommendOrder: () => void;
}): JSX.Element {
  return (
    <div className="composition-members">
      <section className="composition-builder-card composition-member-panel">
        <div className="composition-section-header">
          <div>
            <span>成员技能（{members.length}）</span>
          </div>
          {mode === "ordered" ? (
            <Button disabled={busy || members.length < 2} kind="ghost" onClick={onRecommendOrder}>
              <Wand2 size={14} />
              AI 推荐顺序
            </Button>
          ) : null}
        </div>
        <div className="composition-member-list">
          {members.length === 0 ? <span className="composition-empty-members">从右侧选择要加入此组合的技能</span> : null}
          {members.map((member, index) => (
            <div className="composition-member-row" key={member.toolId}>
              {mode === "ordered" ? <span className="composition-member-index">{index + 1}</span> : null}
              <Bolt className="composition-member-bolt" size={14} />
              <span className="composition-member-copy">
                <strong>{member.name ?? member.toolId}</strong>
              </span>
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
      </section>
    </div>
  );
}

export function SkillPicker({
  members,
  skills,
  onToggle,
}: {
  members: CompositionMember[];
  skills: SkillSummary[];
  onToggle: (skill: SkillSummary) => void;
}): JSX.Element {
  const [query, setQuery] = useState("");
  const selectedToolIds = useMemo(() => new Set(members.map((member) => member.toolId)), [members]);
  const availableSkills = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return skills;
    return skills.filter((skill) =>
      [skill.name, skill.description, skill.source]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(needle)),
    );
  }, [query, skills]);

  return (
    <aside className="composition-builder-card composition-skill-picker">
      <div className="composition-skill-picker-heading">
        <strong>已发布技能</strong>
        <span>勾选后加入组合</span>
      </div>
      <label className="composition-skill-search">
        <Search size={13} />
        <span>搜索技能</span>
        <input aria-label="搜索技能" value={query} onChange={(event) => setQuery(event.currentTarget.value)} />
      </label>
      <div className="composition-skill-pool">
        {availableSkills.length === 0 ? <span className="composition-muted">没有匹配的已掌握工具</span> : null}
        {availableSkills.map((skill) => {
          const selected = selectedToolIds.has(skill.toolId);
          return (
            <button
              aria-pressed={selected}
              className="composition-skill-option"
              key={skill.toolId}
              type="button"
              onClick={() => onToggle(skill)}
            >
              <span className="composition-skill-check">
                {selected ? <Check size={10} strokeWidth={3} /> : <Plus size={12} />}
              </span>
              <Bolt size={13} />
              <span>
                <strong>{skill.name}</strong>
                <small>{skill.description}</small>
              </span>
            </button>
          );
        })}
      </div>
    </aside>
  );
}

export default MemberSelector;
