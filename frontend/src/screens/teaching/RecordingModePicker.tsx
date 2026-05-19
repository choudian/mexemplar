import { Check, Monitor, MousePointerClick, Play, Puzzle, ShieldCheck } from "lucide-react";

import type { RecordingModeReadiness, TeachingMode } from "../../api/teaching";
import { Badge, Button } from "../../components/primitives";

const modeLabels: Record<TeachingMode, string> = {
  browser: "浏览器",
  extension: "浏览器扩展",
  desktop: "桌面",
};

export const MODE_NAMES: Record<TeachingMode, string> = {
  browser: "浏览器录制",
  extension: "插件录制",
  desktop: "桌面录制",
};

const modeDescriptions: Record<TeachingMode, string> = {
  browser: "启动专用浏览器进行录制，自动记录点击、输入、跳转和网络请求。",
  extension: "在日常使用的 Chrome 中直接录制，不需要切换到专用浏览器。",
  desktop: "记录任意桌面应用中的鼠标、键盘、窗口切换和截图。",
};

const modePros: Record<TeachingMode, string[]> = {
  browser: ["记录完整", "推荐网页任务", "隔离录制环境"],
  extension: ["沿用日常浏览器", "减少上下文切换"],
  desktop: ["支持桌面应用", "包含截图线索"],
};

const modeIcons = {
  browser: MousePointerClick,
  extension: Puzzle,
  desktop: Monitor,
};

function RecordingModePicker({
  modes,
  selectedMode,
  busy,
  onSelect,
  onCreate,
}: {
  modes: RecordingModeReadiness[];
  selectedMode: TeachingMode | null;
  busy: boolean;
  onSelect: (mode: TeachingMode) => void;
  onCreate: (mode: TeachingMode) => void;
}): JSX.Element {
  const activeMode = selectedMode ?? modes[0]?.mode ?? "browser";
  const selected = modes.find((mode) => mode.mode === activeMode) ?? modes[0];
  const SelectedIcon = modeIcons[activeMode];

  if (!selected) {
    return <div className="teaching-empty">正在加载录制方式</div>;
  }

  return (
    <div className="teaching-method-picker">
      <div className="teaching-method-label">录制方式</div>
      <div className="teaching-method-tabs" role="tablist" aria-label="录制方式">
        {modes.map((mode) => {
          const Icon = modeIcons[mode.mode];
          const active = activeMode === mode.mode;
          const unavailable = mode.status === "unavailable";
          return (
            <button
              aria-selected={active}
              className="teaching-method-tab"
              data-active={active}
              disabled={unavailable}
              key={mode.mode}
              onClick={() => onSelect(mode.mode)}
              role="tab"
              type="button"
            >
              <Icon size={15} />
              <span>{MODE_NAMES[mode.mode]}</span>
              {mode.mode === "browser" ? <em>推荐</em> : null}
            </button>
          );
        })}
      </div>

      <section className="teaching-method-card" aria-labelledby={`teaching-${activeMode}-heading`}>
        <div className="teaching-method-card-main">
          <div className="teaching-method-icon">
            <SelectedIcon size={22} />
          </div>
          <div>
            <div className="teaching-method-title-row">
              <h3 id={`teaching-${activeMode}-heading`}>{modeLabels[activeMode]}</h3>
              <Badge tone={selected.status === "ready" ? "ok" : "warn"}>{selected.status}</Badge>
            </div>
            <p>{modeDescriptions[activeMode]}</p>
          </div>
        </div>

        <div className="teaching-method-pros">
          {modePros[activeMode].map((item) => (
            <span key={item}>
              <Check size={11} />
              {item}
            </span>
          ))}
        </div>

        <div className="teaching-method-setup">
          <ShieldCheck size={14} />
          <span>{selected.message}</span>
        </div>

        <div className="teaching-method-footer">
          <p>录制开始后，正常完成一遍操作即可。数据只通过本地后端处理。</p>
          <Button disabled={busy || selected.status === "unavailable"} onClick={() => onCreate(activeMode)}>
            <Play size={14} />
            <span>开始</span>
          </Button>
        </div>
      </section>
    </div>
  );
}

export default RecordingModePicker;
