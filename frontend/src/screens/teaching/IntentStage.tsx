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
    <section className="teaching-stage">
      <div>
        <h3>意图确认</h3>
        <p>确认系统理解的目标，必要时补充说明。</p>
      </div>
      <textarea
        aria-label="补充意图说明"
        value={value}
        onChange={(event) => onChange(event.currentTarget.value)}
        placeholder="补充目标、边界或期望结果"
      />
      <div className="teaching-stage-actions">
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
