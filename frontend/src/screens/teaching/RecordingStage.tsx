import { CheckCircle2, Monitor, MousePointerClick, Square } from "lucide-react";

import type { TeachingRun } from "../../api/teaching";
import { Button } from "../../components/primitives";

export function RecordingStage({
  run,
  busy,
  progressLog,
  onStart,
  onStop,
  onDesktopDecision,
}: {
  run: TeachingRun | null;
  busy: boolean;
  progressLog: string[];
  onStart: () => void;
  onStop: () => void;
  onDesktopDecision: (decision: "continue" | "discard" | "rerecord") => void;
}): JSX.Element {
  const active = run?.stage === "recording";
  const capturedCount = progressLog.length;
  const modeLabel = run?.mode === "desktop" ? "桌面录制" : run?.mode === "extension" ? "插件录制" : "浏览器录制";
  return (
    <section className="teaching-recording-view" aria-labelledby="teaching-recording-heading">
      <div className="teaching-recording-surface">
        <div className="teaching-recording-window">
          <div className="teaching-recording-window-bar">
            <i />
            <i />
            <i />
            <span>
              {run?.mode === "desktop" ? <Monitor size={11} /> : <MousePointerClick size={11} />}
              目标操作窗口
            </span>
          </div>
          <div className="teaching-recording-window-body">
            <div className="teaching-recording-sidebar-preview" />
            <div className="teaching-recording-content-preview">
              <span />
              <span />
              <span />
              <span />
            </div>
            <div className="teaching-recording-cursor" aria-hidden="true" />
          </div>
        </div>
        <div className="teaching-recording-hud" data-active={active}>
          <span />
          {active ? "录制中" : "待开始"}
        </div>
      </div>

      <div className="teaching-recording-footer">
        <div>
          <h3 id="teaching-recording-heading">{active ? "正在记录你的操作" : "准备开始录制"}</h3>
          <p>
            {modeLabel} · 已捕获 <strong className="me-mono">{capturedCount}</strong> 条事件线索
          </p>
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
      </div>

      <div className="teaching-event-log">
        <div>
          <CheckCircle2 size={14} />
          实时事件流
        </div>
        {progressLog.length > 0 ? (
          <ul>
            {progressLog.slice(-6).map((item, index) => (
              <li key={`${item}-${index}`}>
                <span className="me-mono">{String(index + 1).padStart(2, "0")}</span>
                <p>{item}</p>
              </li>
            ))}
          </ul>
        ) : (
          <p>开始录制后，这里会显示后端事件进度。</p>
        )}
      </div>
    </section>
  );
}

export default RecordingStage;
