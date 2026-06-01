import { ShieldAlert } from "lucide-react";

import { Button } from "../../components/primitives";

export function SkillDangerConfirm({
  title,
  message,
  affectedNames,
  onCancel,
  onConfirm,
}: {
  title: string;
  message: string;
  affectedNames: string[];
  onCancel: () => void;
  onConfirm: () => void;
}): JSX.Element {
  return (
    <div className="methodology-danger-backdrop" role="presentation">
      <section className="methodology-danger-dialog" role="alertdialog" aria-modal="true" aria-label={title}>
        <div className="assistant-confirmation-title">
          <ShieldAlert size={16} />
          <span>{title}</span>
        </div>
        <p>{message}</p>
        {affectedNames.length > 0 ? (
          <div className="methodology-danger-list">
            {affectedNames.map((name) => <span key={name}>{name}</span>)}
          </div>
        ) : null}
        <div className="assistant-confirmation-actions">
          <Button kind="secondary" onClick={onCancel}>取消</Button>
          <Button kind="danger" onClick={onConfirm}>确认</Button>
        </div>
      </section>
    </div>
  );
}

export default SkillDangerConfirm;
