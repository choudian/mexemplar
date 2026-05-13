import { Monitor, MousePointerClick, Puzzle } from "lucide-react";

import type { RecordingModeReadiness, TeachingMode } from "../../api/teaching";
import { Badge, Button } from "../../components/primitives";

const modeLabels: Record<TeachingMode, string> = {
  browser: "浏览器",
  extension: "浏览器扩展",
  desktop: "桌面",
};

const modeIcons = {
  browser: MousePointerClick,
  extension: Puzzle,
  desktop: Monitor,
};

export function RecordingModePicker({
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
  return (
    <div className="teaching-mode-grid">
      {modes.map((mode) => {
        const Icon = modeIcons[mode.mode];
        const selected = selectedMode === mode.mode;
        return (
          <section className="teaching-mode" data-selected={selected} key={mode.mode}>
            <div className="teaching-mode-title">
              <Icon size={18} />
              <h3>{modeLabels[mode.mode]}</h3>
              <Badge tone={mode.status === "ready" ? "ok" : "warn"}>{mode.status}</Badge>
            </div>
            <p>{mode.message}</p>
            <div className="teaching-mode-actions">
              <Button kind={selected ? "secondary" : "ghost"} onClick={() => onSelect(mode.mode)}>
                选择
              </Button>
              <Button disabled={busy || mode.status === "unavailable"} onClick={() => onCreate(mode.mode)}>
                开始
              </Button>
            </div>
          </section>
        );
      })}
    </div>
  );
}

export default RecordingModePicker;
