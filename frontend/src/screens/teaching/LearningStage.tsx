import { Check, Loader2, Wand2 } from "lucide-react";

import { Button } from "../../components/primitives";

const learningSteps = [
  "解析录制数据",
  "生成技能脚本",
  "自动质量检查",
  "打包并入库",
];

export function LearningStage({
  active,
  progressLog,
  onStartTrial,
}: {
  active: boolean;
  progressLog: string[];
  onStartTrial: () => void;
}): JSX.Element {
  const completedCount = Math.min(progressLog.length, learningSteps.length);
  return (
    <section className="teaching-learning-card" aria-labelledby="teaching-learning-heading">
      <div className="teaching-learning-hero">
        <div className="teaching-learning-orbit">
          <Wand2 size={28} />
          {active ? <span /> : null}
        </div>
        <h3 id="teaching-learning-heading">{active ? "正在学习技能。" : "确认意图后会进入学习阶段。"}</h3>
        <p>系统正在把录制过程转成可复用的本地技能。</p>
      </div>

      <div className="teaching-learning-steps">
        {learningSteps.map((step, index) => {
          const done = index < completedCount;
          const current = index === completedCount && active;
          return (
            <div data-active={current} data-done={done} key={step}>
              <span>
                {done ? <Check size={12} /> : current ? <Loader2 className="assistant-spin" size={12} /> : index + 1}
              </span>
              <div>
                <strong>{step}</strong>
                <small>{current ? progressLog.at(-1) ?? "等待后端进度" : done ? "完成" : "等待"}</small>
              </div>
            </div>
          );
        })}
      </div>

      <div className="teaching-learning-actions">
        <p>后端学习完成后可进入试用验证；开发和测试环境也可直接触发验证路径。</p>
        <Button onClick={onStartTrial}>开始试用</Button>
      </div>
    </section>
  );
}

export default LearningStage;
