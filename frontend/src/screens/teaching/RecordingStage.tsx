import { Square } from "lucide-react";

import type { TeachingRun } from "../../api/teaching";
import { Button } from "../../components/primitives";

export function RecordingStage({
  run,
  busy,
  onStart,
  onStop,
  onDesktopDecision,
}: {
  run: TeachingRun | null;
  busy: boolean;
  onStart: () => void;
  onStop: () => void;
  onDesktopDecision: (decision: "continue" | "discard" | "rerecord") => void;
}): JSX.Element {
  const active = run?.stage === "recording";
  return (
    <section className="teaching-stage">
      <div>
        <h3>录制</h3>
        <p>{active ? "录制进行中" : "准备好后开始录制。"}</p>
      </div>
      <div className="teaching-stage-actions">
        {active ? (
          <Button disabled={busy} kind="danger" onClick={onStop}>
            <Square size={14} />
            <span>停止录制</span>
          </Button>
        ) : (
          <Button disabled={busy || !run} onClick={onStart}>
            开始录制
          </Button>
        )}
        {run?.mode === "desktop" && run.stage === "intent_confirmation" ? (
          <>
            <Button kind="secondary" onClick={() => onDesktopDecision("continue")}>
              继续分析
            </Button>
            <Button kind="ghost" onClick={() => onDesktopDecision("rerecord")}>
              重新录制
            </Button>
          </>
        ) : null}
      </div>
    </section>
  );
}

export default RecordingStage;
