import { Play } from "lucide-react";
import { useState } from "react";

import type { SettingDescriptor, SettingsActionResponse } from "../../api/settings";
import { Badge, Button } from "../../components/primitives";

function tone(status: SettingsActionResponse["status"] | undefined) {
  if (status === "completed") return "ok";
  if (status === "failed") return "danger";
  if (status === "unavailable") return "warn";
  return "neutral";
}

function SettingsActions({
  actions,
  results,
  busy,
  onRun,
}: {
  actions: SettingDescriptor[];
  results: Record<string, SettingsActionResponse>;
  busy: boolean;
  onRun: (actionName: string, options?: { confirmed?: boolean }) => void;
}): JSX.Element {
  const [pendingConfirmation, setPendingConfirmation] = useState<string | null>(null);

  return (
    <section className="settings-actions" aria-label="设置动作">
      {actions.map((action) => {
        const result = results[action.key];
        const unavailable = action.status === "unavailable";
        const destructive = action.key === "clear_assistant_memory";
        const confirming = pendingConfirmation === action.key;
        return (
          <div className="settings-action-row" key={action.key}>
            <div>
              <strong>{action.label}</strong>
              {unavailable ? <span>{action.description || "当前版本暂不可用。"}</span> : null}
              {destructive && confirming ? <span>再次点击确认执行。</span> : null}
              {result ? <span>{result.message}</span> : null}
            </div>
            <Badge tone={tone(result?.status)}>{result?.status ?? action.status}</Badge>
            <Button
              disabled={busy || unavailable}
              kind={destructive && confirming ? "danger" : "secondary"}
              onClick={() => {
                if (destructive && !confirming) {
                  setPendingConfirmation(action.key);
                  return;
                }
                setPendingConfirmation(null);
                onRun(action.key, { confirmed: destructive });
              }}
            >
              <Play size={14} />
              <span>{destructive && confirming ? "确认清空" : "执行"}</span>
            </Button>
          </div>
        );
      })}
    </section>
  );
}

export default SettingsActions;
