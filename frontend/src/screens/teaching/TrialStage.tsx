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
    <section className="teaching-stage">
      <div>
        <h3>试用验证</h3>
        <p>{active ? "正在验证技能。" : "学习完成后开始试用验证。"}</p>
      </div>
      <Button disabled={disabled} onClick={onStart}>
        开始试用
      </Button>
    </section>
  );
}

export default TrialStage;
