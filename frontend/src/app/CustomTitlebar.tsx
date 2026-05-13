import { invoke } from "@tauri-apps/api/core";
import type { CSSProperties, ReactNode } from "react";

async function runWindowCommand(command: "close" | "minimize" | "toggle_maximize"): Promise<void> {
  try {
    await invoke(command);
  } catch {
    // Browser-based unit/dev runs do not have Tauri commands.
  }
}

function startDrag(): void {
  invoke("start_dragging").catch(() => {});
}

export function CustomTitlebar({ right, title }: { right?: ReactNode; title: string }): JSX.Element {
  return (
    <header
      className="me-titlebar"
      onMouseDown={startDrag}
    >
      <div className="me-titlebar-controls" onMouseDown={(e) => e.stopPropagation()}>
        <button
          type="button"
          aria-label="关闭窗口"
          onClick={() => void runWindowCommand("close")}
          style={dotStyle("#ff5f57")}
        />
        <button
          type="button"
          aria-label="最小化窗口"
          onClick={() => void runWindowCommand("minimize")}
          style={dotStyle("#febc2e")}
        />
        <button
          type="button"
          aria-label="最大化或还原窗口"
          onClick={() => void runWindowCommand("toggle_maximize")}
          style={dotStyle("#28c840")}
        />
      </div>
      <div className="me-titlebar-title">
        {title}
      </div>
      <div className="me-titlebar-right" onMouseDown={(e) => e.stopPropagation()}>
        {right}
      </div>
    </header>
  );
}

function dotStyle(background: string): CSSProperties {
  return {
    width: 12,
    height: 12,
    padding: 0,
    cursor: "pointer",
    border: 0,
    borderRadius: "50%",
    background,
    boxShadow: "inset 0 0 0 0.5px rgb(0 0 0 / 18%)",
  };
}
