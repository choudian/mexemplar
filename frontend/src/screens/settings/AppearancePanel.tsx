import type { UiRadius, UiTheme } from "../../api/client";
import {
  applyTheme,
  writeAppearanceMirror,
  type AppearanceSettings,
} from "../../app/applyTheme";
import { useSettingsStore } from "../../state/settingsStore";

interface ThemeOption {
  id: UiTheme;
  name: string;
  mode: string;
  swatch: string;
}

const THEME_OPTIONS: ThemeOption[] = [
  { id: "mint", name: "轻盈薄荷青", mode: "亮", swatch: "linear-gradient(140deg,#3AD0AC,#12B58F)" },
  { id: "indigo", name: "靛蓝 · 琥珀", mode: "亮", swatch: "linear-gradient(140deg,#4A5B96,#2E3A66)" },
  { id: "dark", name: "深色 · 科技", mode: "暗", swatch: "linear-gradient(140deg,#1a1d24,#4C8DFF)" },
  { id: "mono", name: "极简 · 无彩", mode: "亮", swatch: "linear-gradient(140deg,#e8e8e6,#4B5563)" },
];

const ACCENT_PRESETS = ["#14B58C", "#12B886", "#2A8DD6", "#3B4C86", "#7C5CD6", "#D6457E", "#A83246", "#E8873A"];

const RADIUS_OPTIONS: { id: UiRadius; label: string }[] = [
  { id: "sharp", label: "直角" },
  { id: "medium", label: "适中" },
  { id: "round", label: "圆润" },
];

/**
 * 外观设置面板：选基础主题 + 自定义强调色 + 圆角。改动即时 applyTheme 预览
 * （整个界面实时变），并写回后端 ui.theme / ui.accent / ui.radius 持久化。
 */
export function AppearancePanel(): JSX.Element {
  const draftValues = useSettingsStore((state) => state.draftValues);
  const setValue = useSettingsStore((state) => state.setValue);
  const saveValues = useSettingsStore((state) => state.saveValues);

  const theme = (typeof draftValues["ui.theme"] === "string" ? draftValues["ui.theme"] : "mint") as UiTheme;
  const accent = typeof draftValues["ui.accent"] === "string" ? (draftValues["ui.accent"] as string) : "";
  const radius = (typeof draftValues["ui.radius"] === "string" ? draftValues["ui.radius"] : "medium") as UiRadius;

  // 仅预览（拾色器拖动时）：套到界面但不落库。
  const preview = (patch: Partial<AppearanceSettings>) => {
    applyTheme({ theme, accent, radius, ...patch });
  };

  // 预览 + 落库：套到界面、更新首帧镜像、写后端。
  const commit = (patch: Partial<AppearanceSettings>) => {
    const applied = applyTheme({ theme, accent, radius, ...patch });
    writeAppearanceMirror(applied);
    if (patch.theme !== undefined) setValue("ui.theme", patch.theme);
    if (patch.accent !== undefined) setValue("ui.accent", patch.accent);
    if (patch.radius !== undefined) setValue("ui.radius", patch.radius);
    void saveValues();
  };

  return (
    <div className="appearance-panel">
      <p className="appearance-hint">选主题定明暗和整体气质，再拧强调色和圆角。改动即时生效并保存。</p>

      <div className="appearance-group">
        <p className="appearance-label">基础主题</p>
        <div className="appearance-themes" role="group" aria-label="基础主题">
          {THEME_OPTIONS.map((option) => (
            <button
              key={option.id}
              type="button"
              className="appearance-theme"
              aria-pressed={theme === option.id}
              onClick={() => commit({ theme: option.id })}
            >
              <span className="appearance-theme-sw" style={{ background: option.swatch }} aria-hidden="true" />
              <span className="appearance-theme-name">{option.name}</span>
              <span className="appearance-theme-mode">{option.mode}</span>
            </button>
          ))}
        </div>
      </div>

      <div className="appearance-group">
        <p className="appearance-label">强调色</p>
        <div className="appearance-accents" role="group" aria-label="强调色">
          {ACCENT_PRESETS.map((color) => (
            <button
              key={color}
              type="button"
              className="appearance-accent"
              style={{ background: color }}
              aria-pressed={accent.toLowerCase() === color.toLowerCase()}
              aria-label={`强调色 ${color}`}
              onClick={() => commit({ accent: color })}
            />
          ))}
          <label className="appearance-custom">
            自定义
            <input
              type="color"
              value={accent || "#14B58C"}
              onInput={(event) => preview({ accent: event.currentTarget.value })}
              onChange={(event) => commit({ accent: event.currentTarget.value })}
              aria-label="自定义强调色"
            />
          </label>
        </div>
      </div>

      <div className="appearance-group">
        <p className="appearance-label">圆角</p>
        <div className="appearance-radius" role="group" aria-label="圆角">
          {RADIUS_OPTIONS.map((option) => (
            <button
              key={option.id}
              type="button"
              aria-pressed={radius === option.id}
              onClick={() => commit({ radius: option.id })}
            >
              {option.label}
            </button>
          ))}
        </div>
      </div>

      <button
        type="button"
        className="appearance-reset"
        onClick={() => commit({ accent: "", radius: "medium" })}
      >
        重置强调色和圆角
      </button>
    </div>
  );
}

export default AppearancePanel;
