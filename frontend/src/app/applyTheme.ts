import type { UiRadius, UiTheme } from "../api/client";

export interface AppearanceSettings {
  theme: UiTheme;
  accent: string;
  radius: UiRadius;
}

const THEMES: readonly UiTheme[] = ["mint", "indigo", "dark", "mono"];
const RADII: readonly UiRadius[] = ["sharp", "medium", "round"];
const ACCENT_PATTERN = /^#[0-9a-fA-F]{6}$/;

/**
 * localStorage 镜像 key。仅用于冷启动首帧防闪烁（在后端 bootstrap 到达前先套上
 * 上次的外观），权威值始终以后端为准。
 */
export const APPEARANCE_MIRROR_KEY = "mexemplar.appearance";

export const DEFAULT_APPEARANCE: AppearanceSettings = {
  theme: "mint",
  accent: "",
  radius: "medium",
};

/** 把任意来源（后端 summary / localStorage / 设置值）收敛成合法外观，非法值回落默认。 */
export function normalizeAppearance(
  input: Partial<AppearanceSettings> | null | undefined,
): AppearanceSettings {
  const theme = input && THEMES.includes(input.theme as UiTheme)
    ? (input.theme as UiTheme)
    : DEFAULT_APPEARANCE.theme;
  const radius = input && RADII.includes(input.radius as UiRadius)
    ? (input.radius as UiRadius)
    : DEFAULT_APPEARANCE.radius;
  const rawAccent = typeof input?.accent === "string" ? input.accent.trim() : "";
  const accent = ACCENT_PATTERN.test(rawAccent) ? rawAccent : "";
  return { theme, accent, radius };
}

/**
 * 把外观应用到 DOM（theme.css 据 data-theme / data-radius / --user-accent 生效）。
 * 非法输入回落默认；返回实际应用的规范化外观，供调用方写回 localStorage 镜像。
 */
export function applyTheme(
  input: Partial<AppearanceSettings> | null | undefined,
): AppearanceSettings {
  const settings = normalizeAppearance(input);
  const root = document.documentElement;
  root.setAttribute("data-theme", settings.theme);
  root.setAttribute("data-radius", settings.radius);
  if (settings.accent) {
    root.style.setProperty("--user-accent", settings.accent);
  } else {
    root.style.removeProperty("--user-accent");
  }
  return settings;
}

/** 冷启动读上次外观（仅首帧缓存）。读不到或损坏返回 null。 */
export function readAppearanceMirror(): AppearanceSettings | null {
  try {
    const raw = window.localStorage.getItem(APPEARANCE_MIRROR_KEY);
    if (!raw) return null;
    return normalizeAppearance(JSON.parse(raw) as Partial<AppearanceSettings>);
  } catch {
    return null;
  }
}

/** 写回外观镜像（best-effort；localStorage 不可用时静默跳过，后端仍是权威）。 */
export function writeAppearanceMirror(settings: AppearanceSettings): void {
  try {
    window.localStorage.setItem(APPEARANCE_MIRROR_KEY, JSON.stringify(settings));
  } catch {
    // localStorage may be unavailable (private mode / tests); backend stays authoritative.
  }
}
