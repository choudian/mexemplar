import { BookOpenCheck, ShieldCheck } from "lucide-react";

import type { SkillMethodologySummary } from "../api/skillsMethodology";

export function SkillCard({
  skill,
  selected,
  onOpen,
}: {
  skill: SkillMethodologySummary;
  selected?: boolean;
  onOpen: () => void;
}): JSX.Element {
  const description = skill.description || "未填写描述";

  return (
    <button className="methodology-card" data-selected={Boolean(selected)} onClick={onOpen} type="button">
      <span className="methodology-card-icon" aria-hidden="true">
        <BookOpenCheck size={16} />
      </span>
      <span className="methodology-card-copy">
        <span className="methodology-card-title">
          <span className="methodology-card-name">{skill.name}</span>
          {skill.is_protected ? (
            <span className="methodology-card-protected" aria-label="受保护方法论" title="受保护方法论">
              <ShieldCheck size={12} />
            </span>
          ) : null}
        </span>
        <span className="methodology-card-description">{description}</span>
      </span>
    </button>
  );
}

export default SkillCard;
