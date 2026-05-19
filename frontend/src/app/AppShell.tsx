import { useEffect, useMemo } from "react";

import { configureDesktopApiFromTauri, connectEvents, getBootstrap } from "../api/client";
import type { BackendConnectionState, EventStreamCursor, UiEvent } from "../api/client";
import { getUiEventHandlerDomain, isResyncRequiredEvent } from "../api/uiEvents";
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

const TOAST_AUTO_DISMISS_MS = 8000;
const SEEN_EVENT_ID_LIMIT = 500;

const FAILED_BACKEND: BackendConnectionState = {
  status: "failed",
  message: "无法连接本地后端。请重新启动应用或查看日志。",
  checks: [{ name: "sidecar", status: "failed", message: "Sidecar request failed." }],
  serverTime: "",
};

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
  const refreshSkills = useSkillsStore((state) => state.loadCategory);
  const applyCompositionsEvent = useCompositionsStore((state) => state.applyEvent);
  const refreshCompositions = useCompositionsStore((state) => state.load);
  const applySettingsEvent = useSettingsStore((state) => state.applyEvent);
  const refreshSettings = useSettingsStore((state) => state.load);
  const applyTeachingEvent = useTeachingStore((state) => state.applyEvent);
  const refreshTeaching = useTeachingStore((state) => state.refreshCurrentRun);

  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;
    let cursor: EventStreamCursor | undefined;
    let eventProcessing = Promise.resolve();
    let resyncBlocked = false;
    const seenEventIds = new Set<string>();
    const seenEventOrder: string[] = [];

    const rememberEvent = (eventId: string) => {
      if (seenEventIds.has(eventId)) return false;
      seenEventIds.add(eventId);
      seenEventOrder.push(eventId);
      if (seenEventOrder.length > SEEN_EVENT_ID_LIMIT) {
        const oldest = seenEventOrder.shift();
        if (oldest) seenEventIds.delete(oldest);
      }
      return true;
    };

    const refreshAuthoritativeState = async (domains?: string[]) => {
      if (cancelled) return;
      if (!domains) {
        const bootstrap = await getBootstrap();
        if (cancelled) return;
        hydrate(bootstrap);
      }
      const refreshes: Promise<void>[] = [];
      if (!domains || domains.includes("teaching")) refreshes.push(refreshTeaching());
      if (!domains || domains.includes("skills")) refreshes.push(refreshSkills());
      if (!domains || domains.includes("compositions")) refreshes.push(refreshCompositions());
      if (!domains || domains.includes("settings")) refreshes.push(refreshSettings());
      await Promise.all(refreshes);
    };

    const dispatchUiEvent = (event: UiEvent) => {
      switch (getUiEventHandlerDomain(event)) {
        case "assistant":
          applyAssistantEvent(event);
          break;
        case "teaching":
          applyTeachingEvent(event);
          break;
        case "skills":
          applySkillsEvent(event);
          break;
        case "compositions":
          applyCompositionsEvent(event);
          break;
        case "settings":
          applySettingsEvent(event);
          break;
        case "resync":
          break;
      }
    };

    const applyUiEvent = (event: UiEvent) => {
      if (!rememberEvent(event.eventId)) return;
      eventProcessing = eventProcessing
        .then(async () => {
          if (isResyncRequiredEvent(event)) {
            try {
              await refreshAuthoritativeState(event.payload.domains);
              resyncBlocked = false;
            } catch {
              resyncBlocked = true;
              if (!cancelled) {
                setBackend({
                  status: "degraded",
                  message: "事件流需要重新同步，但权威状态刷新失败。",
                  checks: [{ name: "events", status: "degraded", message: "Event resync failed." }],
                  serverTime: new Date().toISOString(),
                });
              }
            }
            return;
          }
          if (resyncBlocked) return;
          dispatchUiEvent(event);
        })
        .catch(() => {
          resyncBlocked = true;
          if (!cancelled) {
            setBackend({
              status: "degraded",
              message: "事件流事件处理失败，需要重新同步。",
              checks: [{ name: "events", status: "degraded", message: "Event processing failed." }],
              serverTime: new Date().toISOString(),
            });
          }
        });
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
          void (async () => {
            while (!cancelled && !controller.signal.aborted) {
              try {
                await connectEvents(applyUiEvent, {
                  signal: controller.signal,
                  cursor,
                  onCursor: (nextCursor) => {
                    cursor = nextCursor;
                  },
                });
              } catch {
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
                  await waitForRetry(1000, controller.signal);
                }
              }
            }
          })();
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
        setBackend({ ...FAILED_BACKEND, serverTime: new Date().toISOString() });
      }
    };

    void connectBackend().catch(() => {
      if (!cancelled) {
        setBackend({ ...FAILED_BACKEND, serverTime: new Date().toISOString() });
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
    refreshCompositions,
    refreshSettings,
    refreshSkills,
    refreshTeaching,
    setBackend,
  ]);

  const route = useMemo(() => getRoute(activeRoute), [activeRoute]);
  const Screen = route.render;

  const teachingToast = useTeachingStore((state) => state.toast);
  const dismissTeachingToast = useTeachingStore((state) => state.dismissToast);
  const closeSkillTrial = useTeachingStore((state) => state.closeSkillTrial);
  const skillTrialToolId = useTeachingStore((state) => state.skillTrialToolId);

  useEffect(() => {
    if (activeRoute !== "skills" && skillTrialToolId) {
      closeSkillTrial();
    }
  }, [activeRoute, skillTrialToolId, closeSkillTrial]);

  useEffect(() => {
    if (!teachingToast) return;
    const timer = setTimeout(dismissTeachingToast, TOAST_AUTO_DISMISS_MS);
    return () => clearTimeout(timer);
  }, [teachingToast, dismissTeachingToast]);

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
        <main className="me-main-pane">
          <CustomTitlebar
            right={<BackendStatus backend={backend} />}
            title={`Mexemplar — ${route.label}`}
          />
          <div className="me-screen-host">
            <Screen />
          </div>
        </main>
      </div>
      {teachingToast ? (
        <div className="teaching-toast">
          <div className="teaching-toast-body">
            <strong>{teachingToast.title}</strong>
            <span>{teachingToast.body}</span>
          </div>
          <button className="teaching-toast-close" onClick={dismissTeachingToast} type="button">✕</button>
        </div>
      ) : null}
    </>
  );
}
