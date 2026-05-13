import { Play, RotateCcw, Trash2, X } from "lucide-react";

import type { SkillCategory, SkillSummary } from "../../api/skills";
import { Badge, Button, IconButton } from "../../components/primitives";

export function SkillCards({
  category,
  skills,
  onTrial,
  onDelete,
  onRetry,
  onDismiss,
}: {
  category: SkillCategory;
  skills: SkillSummary[];
  onTrial: (toolId: string) => void;
  onDelete: (toolId: string) => void;
  onRetry: (workflowId: string) => void;
  onDismiss: (workflowId: string) => void;
}): JSX.Element {
  if (skills.length === 0) {
    return <div className="skills-empty">暂无内容</div>;
  }

  return (
    <div className="skills-grid">
      {skills.map((skill) => (
        <article className="skill-card" key={`${category}-${skill.toolId}`}>
          <div className="skill-card-header">
            <h3>{skill.name}</h3>
            <Badge tone={skill.status === "published" ? "ok" : skill.status === "failed" ? "danger" : "warn"}>
              {skill.status}
            </Badge>
          </div>
          <p>{skill.description || skill.errorSummary}</p>
          <div className="skill-card-meta">
            <span>成功 {skill.trialSuccessCount}/3</span>
            {skill.failureStage ? <span>{skill.failureStage}</span> : null}
          </div>
          <div className="skill-card-actions">
            {category === "failed" ? (
              <>
                <Button kind="secondary" onClick={() => skill.workflowId && onRetry(skill.workflowId)}>
                  <RotateCcw size={14} />
                  <span>重试</span>
                </Button>
                <IconButton label="忽略失败" onClick={() => skill.workflowId && onDismiss(skill.workflowId)}>
                  <X size={14} />
                </IconButton>
              </>
            ) : (
              <>
                <Button kind="secondary" onClick={() => onTrial(skill.toolId)}>
                  <Play size={14} />
                  <span>试用</span>
                </Button>
                <IconButton label="删除技能" onClick={() => onDelete(skill.toolId)}>
                  <Trash2 size={14} />
                </IconButton>
              </>
            )}
          </div>
        </article>
      ))}
    </div>
  );
}

export default SkillCards;
