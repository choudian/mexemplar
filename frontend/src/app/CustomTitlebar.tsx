import { invoke } from "@tauri-apps/api/core";
import type { CSSProperties } from "react";

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

export function CustomTitlebar({ title }: { title: string }): JSX.Element {
  return (
    <header
      onMouseDown={startDrag}
      style={{
        display: "flex",
        height: 38,
        flexShrink: 0,
        alignItems: "center",
        gap: 8,
        padding: "0 14px",
        borderBottom: "1px solid var(--border-1)",
        background: "var(--titlebar-bg)",
      }}
    >
      <div style={{ display: "flex", gap: 8 }} onMouseDown={(e) => e.stopPropagation()}>
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
      <div
        style={{
          flex: 1,
          overflow: "hidden",
          textAlign: "center",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
          color: "var(--text-2)",
          fontSize: 12,
          fontWeight: 600,
        }}
      >
        {title}
      </div>
      <div style={{ width: 60 }} />
    </header>
  );
}

function dotStyle(background: string): CSSProperties {
  return {
    width: 12,
    height: 12,
    padding: 0,
    cursor: "pointer",
    border: "1px solid rgb(0 0 0 / 18%)",
    borderRadius: "50%",
    background,
  };
}
