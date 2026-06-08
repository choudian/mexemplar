import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { AlertTriangle, Loader2, RefreshCw, Unplug } from "lucide-react";

import type { BackendConnectionState } from "../api/client";
import { Button } from "../components/primitives";

// 连接慢到这个时长还没成时，在"连接中"界面露出手动重试入口，避免用户干等。
const SLOW_CONNECT_REVEAL_MS = 5000;

type BackendGateProps = {
  backend: BackendConnectionState | null;
  onRetry: () => void;
  children: ReactNode;
};

/**
 * 全局连接网关：把"后端整个连不上"这类阻断性故障，从散落在各屏底部的红字脚注，
 * 收敛成一张居中、说人话、能重试的恢复卡片；后端正常时原样渲染屏幕内容。
 */
export function BackendGate({ backend, onRetry, children }: BackendGateProps): JSX.Element {
  const status = backend?.status ?? "starting";

  if (status === "failed") {
    return <ConnectionBlocker variant="failed" onRetry={onRetry} />;
  }
  if (status === "starting") {
    return <ConnectionBlocker variant="starting" onRetry={onRetry} />;
  }

  return (
    <>
      {status === "degraded" ? <DegradedBanner onRetry={onRetry} /> : null}
      {children}
    </>
  );
}

function ConnectionBlocker({
  variant,
  onRetry,
}: {
  variant: "failed" | "starting";
  onRetry: () => void;
}): JSX.Element {
  if (variant === "failed") {
    return (
      <div className="backend-gate-blocker" role="alert" aria-live="assertive">
        <div className="backend-gate-card backend-gate-card-failed">
          <div className="backend-gate-icon" data-variant="failed">
            <Unplug size={26} aria-hidden="true" />
          </div>
          <div className="backend-gate-text">
            <h2 className="backend-gate-title">连不上本地服务</h2>
            <p className="backend-gate-body">
              应用的本地服务可能还没启动完，或者刚才断开了。你的数据都还在，连上之后界面会自动恢复。
            </p>
          </div>
          <Button kind="primary" onClick={onRetry}>
            <RefreshCw size={15} aria-hidden="true" />
            重新连接
          </Button>
          <p className="backend-gate-hint">如果点几次还是连不上，把应用整个关掉重开一次通常能解决。</p>
        </div>
      </div>
    );
  }

  return <ConnectingBlocker onRetry={onRetry} />;
}

function ConnectingBlocker({ onRetry }: { onRetry: () => void }): JSX.Element {
  const [showRetry, setShowRetry] = useState(false);

  useEffect(() => {
    const timer = window.setTimeout(() => setShowRetry(true), SLOW_CONNECT_REVEAL_MS);
    return () => window.clearTimeout(timer);
  }, []);

  return (
    <div className="backend-gate-blocker" role="status" aria-live="polite">
      <div className="backend-gate-card backend-gate-card-starting">
        <div className="backend-gate-icon" data-variant="starting">
          <Loader2 className="backend-gate-spin" size={26} aria-hidden="true" />
        </div>
        <div className="backend-gate-text">
          <h2 className="backend-gate-title">正在连接本地服务…</h2>
          <p className="backend-gate-body">马上就好，正在和应用的本地服务握手。</p>
        </div>
        {showRetry ? (
          <button className="backend-gate-linkbtn" type="button" onClick={onRetry}>
            连接有点慢？点这里重试
          </button>
        ) : null}
      </div>
    </div>
  );
}

function DegradedBanner({ onRetry }: { onRetry: () => void }): JSX.Element {
  return (
    <div className="backend-gate-banner" role="status" aria-live="polite">
      <AlertTriangle size={15} aria-hidden="true" />
      <span className="backend-gate-banner-text">
        和本地服务的连接不太稳定，部分更新可能会延迟。
      </span>
      <button className="backend-gate-linkbtn" type="button" onClick={onRetry}>
        重新连接
      </button>
    </div>
  );
}
