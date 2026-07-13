import React from "react";
import ReactDOM from "react-dom/client";

import { AppShell } from "./app/AppShell";
import { applyTheme, readAppearanceMirror } from "./app/applyTheme";
import "./styles/theme.css";

// 冷启动首帧：先套上次的外观（localStorage 镜像），避免后端 bootstrap 到达前闪一下默认主题。
applyTheme(readAppearanceMirror());

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <AppShell />
  </React.StrictMode>,
);
