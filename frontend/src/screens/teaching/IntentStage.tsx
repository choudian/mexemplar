import { Brain, Sparkles } from "lucide-react";

import { Button } from "../../components/primitives";

export function IntentStage({
  value,
  disabled,
  onChange,
  onReply,
  onConfirm,
}: {
  value: string;
  disabled: boolean;
  onChange: (value: string) => void;
  onReply: () => void;
  onConfirm: () => void;
}): JSX.Element {
  return (
    <section className="teaching-intent-card" aria-labelledby="teaching-intent-heading">
      <div className="teaching-intent-head">
        <div>
          <Brain size={20} />
        </div>
        <div>
          <h3 id="teaching-intent-heading">AI 正在理解你刚才的操作</h3>
          <p>确认系统理解的目标，必要时补充说明。</p>
        </div>
      </div>

      <div className="teaching-intent-summary">
        <strong>初步理解：</strong>
        <span>系统已完成录制数据整理，正在把关键步骤、可变参数和执行边界转换成可复用技能。</span>
      </div>

      <div className="teaching-intent-question">
        <Sparkles size={15} />
        <div>
          <p>是否需要补充目标、边界或期望结果？如果没有，可以直接确认并进入学习阶段。</p>
          <textarea
            aria-label="补充意图说明"
            value={value}
            onChange={(event) => onChange(event.currentTarget.value)}
            placeholder="补充目标、边界或期望结果"
          />
        </div>
      </div>

      <div className="teaching-stage-actions teaching-intent-actions">
        <Button disabled={disabled || !value.trim()} kind="secondary" onClick={onReply}>
          发送说明
        </Button>
        <Button disabled={disabled} onClick={onConfirm}>
          确认并学习
        </Button>
      </div>
    </section>
  );
}

export default IntentStage;
