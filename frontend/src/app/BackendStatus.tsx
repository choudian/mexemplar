import { AlertCircle, CheckCircle2, Loader2, Power } from "lucide-react";

import type { BackendConnectionState, BackendStatus as BackendStatusValue } from "../api/client";
import { Badge } from "../components/primitives";

const labels: Record<BackendStatusValue, string> = {
  starting: "启动中",
  ready: "已就绪",
  degraded: "部分可用",
  failed: "连接失败",
  shutting_down: "关闭中",
};

export function BackendStatus({ backend }: { backend: BackendConnectionState | null }): JSX.Element {
  const status = backend?.status ?? "starting";
  const Icon = status === "ready" ? CheckCircle2 : status === "failed" ? AlertCircle : status === "shutting_down" ? Power : Loader2;
  const tone = status === "ready" ? "ok" : status === "failed" ? "danger" : status === "degraded" ? "warn" : "neutral";

  return (
    <div
      className="me-backend-status"
      role="status"
      aria-live="polite"
    >
      <Icon size={14} aria-hidden="true" />
      <Badge tone={tone}>{labels[status]}</Badge>
      <span className="me-backend-message">{backend?.message ?? "正在连接本地后端"}</span>
    </div>
  );
}
