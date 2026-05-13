import { ShieldAlert } from "lucide-react";

import type { AssistantConfirmation } from "../../api/assistant";
import { Button } from "../../components/primitives";

export function ConfirmationToast({
  confirmation,
  onDecision,
}: {
  confirmation: AssistantConfirmation;
  onDecision: (requestId: string, decision: "approve" | "deny") => void;
}): JSX.Element {
  return (
    <div className="assistant-confirmation" role="alert" aria-live="assertive">
      <div className="assistant-confirmation-title">
        <ShieldAlert size={16} />
        <span>高风险操作确认</span>
      </div>
      <p>{confirmation.sanitizedSummary}</p>
      <div className="assistant-confirmation-actions">
        <Button kind="secondary" onClick={() => onDecision(confirmation.requestId, "deny")}>
          拒绝
        </Button>
        <Button kind="primary" onClick={() => onDecision(confirmation.requestId, "approve")}>
          允许
        </Button>
      </div>
    </div>
  );
}

export default ConfirmationToast;
