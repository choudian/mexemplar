import { CheckCircle2, Play } from "lucide-react";

import { Button } from "../../components/primitives";

export function TrialStage({
  active,
  disabled,
  onStart,
}: {
  active: boolean;
  disabled: boolean;
  onStart: () => void;
}): JSX.Element {
  return (
    <section className="teaching-trial-card" aria-labelledby="teaching-trial-heading">
      <div className="teaching-trial-head">
        <div>
          <CheckCircle2 size={20} />
        </div>
        <div>
          <h3 id="teaching-trial-heading">试用验证</h3>
          <p>{active ? "正在验证技能。" : "学习完成后开始试用验证。"}</p>
        </div>
      </div>

      <div className="teaching-trial-progress" aria-label="试用进度">
        <span data-active={active} />
        <span />
        <span />
      </div>

      <div className="teaching-trial-body">
        <p>试用通过后，技能会进入待考核或已掌握流程；失败时后端会返回原因并继续修正。</p>
        <Button disabled={disabled} onClick={onStart}>
          <Play size={14} />
          <span>开始试用</span>
        </Button>
      </div>
    </section>
  );
}

export default TrialStage;
