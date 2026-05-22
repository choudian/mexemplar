import { Bolt, Clock3, Play, RotateCcw, Trash2, X } from "lucide-react";

import type { SkillCategory, SkillSummary } from "../../api/skills";
import { Badge, Button, IconButton } from "../../components/primitives";

const TRIAL_PROGRESS_STEPS = ["first", "second", "third"] as const;

function SkillCards({
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

  if (category === "pending") {
    return (
      <div className="skills-list me-scroll">
        {skills.map((skill) => (
          <article className="skill-pending-row" key={`${category}-${skill.toolId}`}>
            <div className="skill-row-main">
              <div className="skill-row-title">
                <h3>{skill.name}</h3>
                <Badge tone="warn">待考核</Badge>
              </div>
              <p>{skill.description || "等待试用验证。"}</p>
              <div className="skill-row-meta">
                <span>
                  <Clock3 size={12} />
                  来源：{skill.source || "教学流程"}
                </span>
              </div>
            </div>
            <div className="skill-trial-progress" aria-label={`${skill.name} 试用进度`}>
              <small>试用进度</small>
              <strong className="me-mono">{skill.trialSuccessCount}/3</strong>
              <div>
                {TRIAL_PROGRESS_STEPS.map((step, index) => (
                  <i data-done={index < skill.trialSuccessCount} key={step} />
                ))}
              </div>
            </div>
            <div className="skill-row-actions">
              <Button kind="primary" onClick={() => onTrial(skill.toolId)}>
                <Play size={14} />
                <span>试用</span>
              </Button>
              <IconButton label="删除技能" onClick={() => onDelete(skill.toolId)}>
                <Trash2 size={14} />
              </IconButton>
            </div>
          </article>
        ))}
      </div>
    );
  }

  if (category === "failed") {
    return (
      <div className="skills-list me-scroll">
        {skills.map((skill) => (
          <article className="skill-failed-row" key={`${category}-${skill.toolId}`}>
            <div className="skill-failed-icon">
              <X size={15} />
            </div>
            <div className="skill-row-main">
              <h3>{skill.name}</h3>
              <p>
                失败原因：{skill.errorSummary || skill.description || "后端未返回详细原因。"}
                {skill.failureStage ? <span> · {skill.failureStage}</span> : null}
              </p>
            </div>
            <div className="skill-row-actions">
              <Button kind="secondary" onClick={() => skill.workflowId && onRetry(skill.workflowId)}>
                <RotateCcw size={14} />
                <span>重试</span>
              </Button>
              <IconButton label="忽略失败" onClick={() => skill.workflowId && onDismiss(skill.workflowId)}>
                <X size={14} />
              </IconButton>
            </div>
          </article>
        ))}
      </div>
    );
  }

  return (
    <div className="skills-mastered-grid me-scroll">
      {skills.map((skill) => {
        const needsMoreTrials = skill.trialSuccessCount < 3;
        return (
          <article className="skill-mastered-card" key={`${category}-${skill.toolId}`}>
            <div className="skill-mastered-card-top">
              <div className="skill-mastered-icon">
                <Bolt size={18} />
              </div>
              <div>
                <h3>{skill.name}</h3>
                <p>{skill.description || "可在对话和组合中复用。"}</p>
              </div>
            </div>
            <div className="skill-tags">
              {skill.source ? <span>{skill.source}</span> : null}
              <span>成功 {skill.trialSuccessCount}/3</span>
            </div>
            <div className="skill-card-footer">
              <span>状态：已掌握</span>
              <div className="skill-row-actions">
                {needsMoreTrials ? (
                  <Button kind="secondary" onClick={() => onTrial(skill.toolId)}>
                    <Play size={14} />
                    <span>试用</span>
                  </Button>
                ) : null}
                <IconButton label="删除技能" onClick={() => onDelete(skill.toolId)}>
                  <Trash2 size={14} />
                </IconButton>
              </div>
            </div>
          </article>
        );
      })}
    </div>
  );
}

export default SkillCards;
