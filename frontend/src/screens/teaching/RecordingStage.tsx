import { useMemo, useState } from "react";
import { CheckCircle2, Monitor, MousePointerClick, Square } from "lucide-react";

import type { TeachingRun } from "../../api/teaching";
import { MODE_NAMES } from "./RecordingModePicker";
import { Button } from "../../components/primitives";

function RecordingStage({
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
  const [consentVisible, setConsentVisible] = useState(false);
  const active = run?.stage === "recording";
  const capturedCount = progressLog.length;
  const visibleProgressLog = useMemo(() => {
    const startSeq = Math.max(1, progressLog.length - 5);
    return progressLog.slice(-6).map((item, offset) => ({ item, sequence: startSeq + offset }));
  }, [progressLog]);
  const modeLabel = run?.mode ? MODE_NAMES[run.mode] : "浏览器录制";

  const requestStart = () => {
    setConsentVisible(true);
  };

  const confirmStart = () => {
    setConsentVisible(false);
    onStart();
  };

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
            <Button disabled={busy || !run} onClick={requestStart}>
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

      {consentVisible && !active ? (
        <div className="teaching-recording-consent" role="alertdialog" aria-modal="true" aria-labelledby="teaching-recording-consent-title">
          <h4 id="teaching-recording-consent-title">录制隐私确认</h4>
          <p>
            当前屏幕或浏览器中的可见内容可能会被记录，并在后续工具教学流程中交给已配置的模型处理。
            请只录制为本次验收或教学准备的无敏感内容目标。
          </p>
          <div className="teaching-recording-consent-actions">
            <Button kind="ghost" onClick={() => setConsentVisible(false)}>
              取消
            </Button>
            <Button disabled={busy || !run} onClick={confirmStart}>
              确认并开始录制
            </Button>
          </div>
        </div>
      ) : null}

      <div className="teaching-event-log">
        <div>
          <CheckCircle2 size={14} />
          实时事件流
        </div>
        {progressLog.length > 0 ? (
          <ul>
            {visibleProgressLog.map((entry) => (
              <li key={`progress-${entry.sequence}`}>
                <span className="me-mono">{String(entry.sequence).padStart(2, "0")}</span>
                <p>{entry.item}</p>
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
