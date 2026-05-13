import { Loader2 } from "lucide-react";

export function LearningStage({ active, progressLog }: { active: boolean; progressLog: string[] }): JSX.Element {
  return (
    <section className="teaching-stage">
      <div>
        <h3>学习</h3>
        <p>{active ? "正在学习技能。" : "确认意图后会进入学习阶段。"}</p>
      </div>
      <div className="teaching-progress">
        {active ? <Loader2 className="assistant-spin" size={16} /> : null}
        <span>{progressLog.at(-1) ?? "等待事件"}</span>
      </div>
    </section>
  );
}

export default LearningStage;
