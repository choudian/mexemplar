import { BookOpenCheck, GitBranch, ShieldCheck } from "lucide-react";

import type { SkillMethodologySummary } from "../api/skillsMethodology";
import { formatDate } from "../utils/dates";
import { Badge, Button } from "./primitives";

export function SkillCard({
  skill,
  selected,
  onOpen,
}: {
  skill: SkillMethodologySummary;
  selected?: boolean;
  onOpen: () => void;
}): JSX.Element {
  return (
    <article className="methodology-card" data-selected={Boolean(selected)}>
      <div className="methodology-card-head">
        <span className="methodology-card-icon">
          <BookOpenCheck size={18} />
        </span>
        <div>
          <div className="methodology-card-title">
            <h3>{skill.name}</h3>
            {skill.is_protected ? (
              <Badge tone="warn">
                <ShieldCheck size={12} />
                受保护
              </Badge>
            ) : null}
          </div>
          <p>{skill.description || "未填写描述"}</p>
        </div>
      </div>
      <div className="methodology-trigger-list">
        {skill.trigger_conditions.slice(0, 3).map((trigger) => (
          <span key={trigger}>{trigger}</span>
        ))}
        {skill.trigger_conditions.length > 3 ? <span>+{skill.trigger_conditions.length - 3}</span> : null}
      </div>
      <div className="methodology-card-metrics">
        <span>加载 {skill.loaded_count}</span>
        <span>装备 {skill.equipped_count}</span>
        <span>引用 {skill.referenced_count}</span>
      </div>
      <div className="methodology-card-footer">
        <span>
          <GitBranch size={12} />
          v{skill.version} · {formatDate(skill.created_at)}
        </span>
        <Button kind="ghost" onClick={onOpen}>
          打开
        </Button>
      </div>
    </article>
  );
}

export default SkillCard;
