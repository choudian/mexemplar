import { useEffect, useMemo } from "react";

import { configureDesktopApiFromTauri, connectEvents, getBootstrap } from "../api/client";
import type { BackendConnectionState, UiEvent } from "../api/client";
import { useAssistantStore } from "../state/assistantStore";
import { useCompositionsStore } from "../state/compositionsStore";
import { useSettingsStore } from "../state/settingsStore";
import { useShellStore } from "../state/shellStore";
import { useSkillsStore } from "../state/skillsStore";
import { useTeachingStore } from "../state/teachingStore";
import { BackendStatus } from "./BackendStatus";
import { CustomTitlebar } from "./CustomTitlebar";
import { NavRail } from "./NavRail";
import { getRoute } from "./routes";

const BOOTSTRAP_RETRY_DELAYS_MS = [250, 500, 1000, 1500, 2000, 3000, 4000, 5000, 5000];

function waitForRetry(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const timeout = window.setTimeout(() => {
      signal.removeEventListener("abort", abort);
      resolve();
    }, ms);
    function abort() {
      window.clearTimeout(timeout);
      signal.removeEventListener("abort", abort);
      reject(new DOMException("Bootstrap retry aborted.", "AbortError"));
    }
    if (signal.aborted) {
      abort();
      return;
    }
    signal.addEventListener("abort", abort, { once: true });
  });
}

export function AppShell(): JSX.Element {
  const activeRoute = useShellStore((state) => state.activeRoute);
  const backend = useShellStore((state) => state.backend);
  const navigation = useShellStore((state) => state.navigation);
  const userDisplayName = useShellStore((state) => state.userDisplayName);
  const userStatusLabel = useShellStore((state) => state.userStatusLabel);
  const setRoute = useShellStore((state) => state.setRoute);
  const hydrate = useShellStore((state) => state.hydrate);
  const setBackend = useShellStore((state) => state.setBackend);
  const applyAssistantEvent = useAssistantStore((state) => state.applyEvent);
  const applySkillsEvent = useSkillsStore((state) => state.applyEvent);
  const applyCompositionsEvent = useCompositionsStore((state) => state.applyEvent);
  const applySettingsEvent = useSettingsStore((state) => state.applyEvent);
  const applyTeachingEvent = useTeachingStore((state) => state.applyEvent);

  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;

    const applyUiEvent = (event: UiEvent) => {
      if (event.type === "backend.health") {
        setBackend(event.payload as unknown as BackendConnectionState);
      }
      if (event.type.startsWith("assistant.")) {
        applyAssistantEvent(event);
      }
      if (
        event.type === "recording.progress" ||
        event.type === "teaching.progress" ||
        event.type === "trial.progress"
      ) {
        applyTeachingEvent(event);
      }
      if (event.type === "skills.changed") {
        applySkillsEvent(event);
      }
      if (event.type === "compositions.changed") {
        applyCompositionsEvent(event);
      }
      if (event.type === "settings.changed") {
        applySettingsEvent(event);
      }
    };

    const connectBackend = async () => {
      await configureDesktopApiFromTauri();

      for (let attempt = 0; attempt <= BOOTSTRAP_RETRY_DELAYS_MS.length; attempt += 1) {
        try {
          const bootstrap = await getBootstrap();
          if (cancelled) {
            return;
          }
          hydrate(bootstrap);
          void connectEvents(applyUiEvent, controller.signal).catch(() => {
            if (!cancelled) {
              setBackend({
                ...bootstrap.connection,
                status: bootstrap.connection.status === "failed" ? "failed" : "degraded",
                message: "事件流不可用，后台状态更新可能延迟。",
                checks: [
                  ...bootstrap.connection.checks.filter((check) => check.name !== "events"),
                  { name: "events", status: "degraded", message: "Desktop event stream failed." },
                ],
              });
            }
          });
          return;
        } catch {
          if (cancelled || attempt === BOOTSTRAP_RETRY_DELAYS_MS.length) {
            break;
          }
          setBackend({
            status: "starting",
            message: "正在等待本地后端启动...",
            checks: [{ name: "sidecar", status: "degraded", message: "Sidecar is not ready yet." }],
            serverTime: new Date().toISOString(),
          });
          await waitForRetry(BOOTSTRAP_RETRY_DELAYS_MS[attempt], controller.signal);
        }
      }

      if (!cancelled) {
        setBackend({
          status: "failed",
          message: "无法连接本地后端。请重新启动应用或查看日志。",
          checks: [{ name: "sidecar", status: "failed", message: "Sidecar request failed." }],
          serverTime: new Date().toISOString(),
        });
      }
    };

    void connectBackend().catch(() => {
      if (!cancelled) {
        setBackend({
          status: "failed",
          message: "无法连接本地后端。请重新启动应用或查看日志。",
          checks: [{ name: "sidecar", status: "failed", message: "Sidecar request failed." }],
          serverTime: new Date().toISOString(),
        });
      }
    });
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [
    applyAssistantEvent,
    applyCompositionsEvent,
    applySettingsEvent,
    applySkillsEvent,
    applyTeachingEvent,
    hydrate,
    setBackend,
  ]);

  const route = useMemo(() => getRoute(activeRoute), [activeRoute]);
  const Screen = route.render;

  return (
    <>
      <div className="me-page-bg" />
      <div className="me-shell" data-screen-label={`Mexemplar / ${route.label}`}>
        <NavRail
          activeRoute={activeRoute}
          counts={navigation}
          userDisplayName={userDisplayName}
          userStatusLabel={userStatusLabel}
          onRouteChange={setRoute}
        />
        <main style={{ display: "flex", minWidth: 0, flex: 1, flexDirection: "column", background: "var(--surface-1)" }}>
          <CustomTitlebar title={`Mexemplar — ${route.label}`} />
          <div
            style={{
              display: "flex",
              height: 54,
              alignItems: "center",
              justifyContent: "space-between",
              gap: 18,
              padding: "0 32px",
              borderBottom: "1px solid var(--border-1)",
            }}
          >
            <div>
              <div style={{ fontSize: 13, color: "var(--text-muted)" }}>当前区域</div>
              <div style={{ fontSize: 16, fontWeight: 700 }}>{route.label}</div>
            </div>
            <BackendStatus backend={backend} />
          </div>
          <div className="me-scroll" style={{ minHeight: 0, flex: 1, overflow: "auto" }}>
            <Screen />
          </div>
        </main>
      </div>
    </>
  );
}

export default AppShell;
