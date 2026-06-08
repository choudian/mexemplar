import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useAutoDismissToast } from "../hooks/useAutoDismissToast";

import { triggerAssistantSegmentBoundary } from "../api/assistant";
import { configureDesktopApiFromTauri, connectEvents, getBootstrap } from "../api/client";
import type { BackendConnectionState, EventStreamCursor, UiEvent } from "../api/client";
import {
  DEBUG_CONTROL_STATUS_EVENT,
  dispatchDebugRawStatePurge,
  getControlStatus,
  updateControl,
} from "../api/debug";
import { getUiEventHandlerDomain, isResyncRequiredEvent } from "../api/uiEvents";
import BrainToast from "../components/BrainToast";
import { useAssistantStore } from "../state/assistantStore";
import { useBrainStore } from "../state/brainStore";
import { useCompositionsStore } from "../state/compositionsStore";
import { useSettingsStore } from "../state/settingsStore";
import { useShellStore } from "../state/shellStore";
import { useSkillMethodologyStore } from "../state/skillMethodologyStore";
import { useSkillsStore } from "../state/skillsStore";
import { useSpecialistStore } from "../state/specialistStore";
import { useTeachingStore } from "../state/teachingStore";
import { BackendGate } from "./BackendGate";
import { BackendStatus } from "./BackendStatus";
import { ErrorToastHost } from "./ErrorToastHost";
import { CustomTitlebar } from "./CustomTitlebar";
import { NavRail } from "./NavRail";
import { getHiddenRoute, getRoute, redirectPathFor, routeIdFromPath, routePaths } from "./routes";
import { isToolRenameToastDismissed, markToolRenameToastDismissed } from "./toolRenameToastStorage";

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
  const activeAssistantSessionId = useAssistantStore((state) => state.activeSessionId);
  const setAssistantIdleThresholdSeconds = useAssistantStore((state) => state.setIdleThresholdSeconds);
  const applyAssistantEvent = useAssistantStore((state) => state.applyEvent);
  const applySkillsEvent = useSkillsStore((state) => state.applyEvent);
  const refreshSkills = useSkillsStore((state) => state.loadAllCategories);
  const applySkillMethodologyEvent = useSkillMethodologyStore((state) => state.applyEvent);
  const refreshSkillMethodologies = useSkillMethodologyStore((state) => state.load);
  const loadSkillBootstrapStatus = useSkillMethodologyStore((state) => state.loadBootstrapStatus);
  const skillBootstrapWarning = useSkillMethodologyStore((state) => state.bootstrapWarning);
  const dismissSkillBootstrapWarning = useSkillMethodologyStore((state) => state.dismissBootstrapWarning);
  const applyCompositionsEvent = useCompositionsStore((state) => state.applyEvent);
  const refreshCompositions = useCompositionsStore((state) => state.load);
  const applySettingsEvent = useSettingsStore((state) => state.applyEvent);
  const refreshSettings = useSettingsStore((state) => state.load);
  const applyTeachingEvent = useTeachingStore((state) => state.applyEvent);
  const refreshTeaching = useTeachingStore((state) => state.refreshCurrentRun);
  const applyBrainEvent = useBrainStore((state) => state.applyEvent);
  const refreshBrainZones = useBrainStore((state) => state.loadZones);
  const refreshBrainEntries = useBrainStore((state) => state.loadEntries);
  const refreshBrainSegments = useBrainStore((state) => state.loadSegments);
  const refreshBrainSkillPool = useBrainStore((state) => state.loadSkillPool);
  const applySpecialistEvent = useSpecialistStore((state) => state.applyEvent);
  const refreshSpecialists = useSpecialistStore((state) => state.load);
  const [debugTraceActive, setDebugTraceActive] = useState(false);
  const [retryNonce, setRetryNonce] = useState(0);
  const [pathname, setPathname] = useState(() => window.location.pathname);
  const [toolRenameToastOpen, setToolRenameToastOpen] = useState(
    () => !isToolRenameToastDismissed(),
  );
  const debugStatusVersion = useRef(0);

  const refreshDebugTraceStatus = useCallback(async () => {
    const requestVersion = ++debugStatusVersion.current;
    try {
      const status = await getControlStatus();
      if (requestVersion !== debugStatusVersion.current) return;
      setDebugTraceActive(status.enabled);
    } catch {
      if (requestVersion !== debugStatusVersion.current) return;
      setDebugTraceActive(false);
    }
  }, []);

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
        setAssistantIdleThresholdSeconds(bootstrap.brain.segmentIdleThresholdSeconds);
      }
      const refreshes: Promise<void>[] = [];
      if (!domains || domains.includes("teaching")) refreshes.push(refreshTeaching());
      if (!domains || domains.includes("tools")) refreshes.push(refreshSkills());
      if (!domains || domains.includes("skill")) refreshes.push(refreshSkillMethodologies());
      if (!domains || domains.includes("compositions")) refreshes.push(refreshCompositions());
      if (!domains || domains.includes("settings")) refreshes.push(refreshSettings());
      if (!domains || domains.includes("assistant")) {
        const assistantState = useAssistantStore.getState();
        const sessionId = assistantState.activeSessionId;
        if (sessionId) {
          refreshes.push(assistantState.refreshSubagents(sessionId));
          refreshes.push(assistantState.refreshActivityTranscript(sessionId));
        }
      }
      if (!domains || domains.includes("brain")) {
        const activeBrainZone = useBrainStore.getState().activeZone ?? "hot";
        refreshes.push(refreshBrainZones());
        refreshes.push(refreshBrainEntries(activeBrainZone));
        refreshes.push(refreshBrainSegments());
        refreshes.push(refreshBrainSkillPool());
        refreshes.push(refreshSpecialists());
      }
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
        case "skill":
          applySkillMethodologyEvent(event);
          break;
        case "compositions":
          applyCompositionsEvent(event);
          break;
        case "settings":
          applySettingsEvent(event);
          break;
        case "brain":
          applyBrainEvent(event);
          applySpecialistEvent(event);
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
          setAssistantIdleThresholdSeconds(bootstrap.brain.segmentIdleThresholdSeconds);
          void loadSkillBootstrapStatus();
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
    applySkillMethodologyEvent,
    applyTeachingEvent,
    applyBrainEvent,
    applySpecialistEvent,
    hydrate,
    refreshBrainEntries,
    refreshBrainSegments,
    refreshBrainSkillPool,
    refreshBrainZones,
    refreshCompositions,
    refreshSettings,
    refreshSkillMethodologies,
    refreshSkills,
    refreshSpecialists,
    refreshTeaching,
    setBackend,
    setAssistantIdleThresholdSeconds,
    loadSkillBootstrapStatus,
    retryNonce,
  ]);

  const reconnectBackend = useCallback(() => {
    setBackend({
      status: "starting",
      message: "正在重新连接本地后端...",
      checks: [{ name: "sidecar", status: "degraded", message: "Reconnecting to sidecar." }],
      serverTime: new Date().toISOString(),
    });
    setRetryNonce((nonce) => nonce + 1);
  }, [setBackend]);

  const teachingToast = useTeachingStore((state) => state.toast);
  const dismissTeachingToast = useTeachingStore((state) => state.dismissToast);
  const recruitmentToast = useSpecialistStore((state) => state.recruitmentToast);
  const dismissRecruitmentToast = useSpecialistStore((state) => state.dismissRecruitmentToast);
  const closeSkillTrial = useTeachingStore((state) => state.closeSkillTrial);
  const skillTrialToolId = useTeachingStore((state) => state.skillTrialToolId);
  const dismissToolRenameToast = useCallback(() => {
    markToolRenameToastDismissed();
    setToolRenameToastOpen(false);
  }, []);

  useEffect(() => {
    if (activeRoute !== "skills" && skillTrialToolId) {
      closeSkillTrial();
    }
  }, [activeRoute, skillTrialToolId, closeSkillTrial]);

  useAutoDismissToast(teachingToast, dismissTeachingToast, TOAST_AUTO_DISMISS_MS);
  useAutoDismissToast(recruitmentToast, dismissRecruitmentToast, TOAST_AUTO_DISMISS_MS);
  useAutoDismissToast(toolRenameToastOpen, dismissToolRenameToast, TOAST_AUTO_DISMISS_MS);
  useAutoDismissToast(skillBootstrapWarning, dismissSkillBootstrapWarning, TOAST_AUTO_DISMISS_MS);

  useEffect(() => {
    const handleLocationChange = () => setPathname(window.location.pathname);
    window.addEventListener("popstate", handleLocationChange);
    return () => window.removeEventListener("popstate", handleLocationChange);
  }, []);

  useEffect(() => {
    const curPath = window.location.pathname;
    const redirect = redirectPathFor(curPath, window.location.search);
    if (redirect) {
      window.history.replaceState({}, "", redirect);
      setPathname(window.location.pathname);
      return;
    }
    const routeId = routeIdFromPath(curPath);
    if (routeId && routeId !== activeRoute) {
      setRoute(routeId);
    }
  }, [activeRoute, setRoute, pathname]);

  const hiddenRoute = useMemo(() => getHiddenRoute(pathname), [pathname]);
  const visibleRoute = useMemo(() => getRoute(activeRoute), [activeRoute]);
  const routeForScreen = hiddenRoute ?? visibleRoute;
  const Screen = routeForScreen.render;

  const changeVisibleRoute = useCallback((nextRoute: Parameters<typeof setRoute>[0]) => {
    if (hiddenRoute) {
      dispatchDebugRawStatePurge();
    }
    const nextPath = routePaths[nextRoute];
    const currentPath = window.location.pathname;
    if (nextPath && (currentPath !== nextPath || hiddenRoute)) {
      if (hiddenRoute) {
        window.history.replaceState({}, "", nextPath);
      } else {
        window.history.pushState({}, "", nextPath);
      }
      setPathname(nextPath);
    } else if (hiddenRoute && !nextPath) {
      window.history.replaceState({}, "", "/");
      setPathname("/");
    }
    setRoute(nextRoute);
  }, [hiddenRoute, setRoute]);

  useEffect(() => {
    void refreshDebugTraceStatus();
  }, [refreshDebugTraceStatus]);

  useEffect(() => {
    const handleDebugControlStatus = (event: Event) => {
      const status = (event as CustomEvent<{ enabled?: unknown }>).detail;
      if (typeof status?.enabled === "boolean") {
        debugStatusVersion.current += 1;
        setDebugTraceActive(status.enabled);
      }
    };
    window.addEventListener(DEBUG_CONTROL_STATUS_EVENT, handleDebugControlStatus);
    return () => window.removeEventListener(DEBUG_CONTROL_STATUS_EVENT, handleDebugControlStatus);
  }, []);

  const isDebugRoute = hiddenRoute?.id === "debug";
  useEffect(() => {
    if (!debugTraceActive && !isDebugRoute) return;
    const interval = window.setInterval(() => {
      void refreshDebugTraceStatus();
    }, 5000);
    return () => window.clearInterval(interval);
  }, [debugTraceActive, isDebugRoute, refreshDebugTraceStatus]);

  const stopDebugTrace = useCallback(async () => {
    const requestVersion = ++debugStatusVersion.current;
    try {
      const status = await updateControl({ enabled: false });
      if (requestVersion !== debugStatusVersion.current) return;
      setDebugTraceActive(status.enabled);
      dispatchDebugRawStatePurge();
    } catch {
      await refreshDebugTraceStatus();
    }
  }, [refreshDebugTraceStatus]);

  return (
    <>
      <div className="me-page-bg" />
      <div className="me-shell" data-testid="app-shell" data-screen-label={`Mexemplar / ${routeForScreen.label}`}>
        <NavRail
          activeRoute={activeRoute}
          counts={navigation}
          userDisplayName={userDisplayName}
          userStatusLabel={userStatusLabel}
          onRouteChange={changeVisibleRoute}
        />
        <main className="me-main-pane">
          <CustomTitlebar
            onBeforeClose={async () => {
              if (activeAssistantSessionId) {
                const CLOSE_TIMEOUT_MS = 5000;
                try {
                  await Promise.race([
                    triggerAssistantSegmentBoundary(activeAssistantSessionId, "window_close"),
                    new Promise<void>((_, reject) =>
                      setTimeout(() => reject(new Error("segment boundary timeout")), CLOSE_TIMEOUT_MS),
                    ),
                  ]);
                } catch {
                  // Segment boundary is best-effort on close; backend recovers via idle timeout.
                }
              }
            }}
            right={<BackendStatus backend={backend} />}
            title={`Mexemplar — ${routeForScreen.label}`}
          />
          {debugTraceActive ? (
            <div className="debug-trace-banner" role="status">
              <span>Debug trace capture is active for this sidecar session.</span>
              <button type="button" onClick={stopDebugTrace}>Stop trace</button>
            </div>
          ) : null}
          <div className="me-screen-host">
            <BackendGate backend={backend} onRetry={reconnectBackend}>
              <Screen />
            </BackendGate>
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
      {toolRenameToastOpen ? (
        <div className="teaching-toast tool-rename-toast">
          <div className="teaching-toast-body">
            <strong>Skill 已重命名为 Tool</strong>
            <span>教学、列表和组合屏现在使用 Tool 命名；方法论屏继续使用 Skill。</span>
          </div>
          <button className="teaching-toast-close" onClick={dismissToolRenameToast} type="button">✕</button>
        </div>
      ) : null}
      {skillBootstrapWarning ? (
        <div className="teaching-toast skill-bootstrap-toast" role="status">
          <div className="teaching-toast-body">
            <strong>方法论 seed 加载失败</strong>
            <span>
              已启用 fallback。请检查 {skillBootstrapWarning.seedFilePath || "seed 文件"}，或在方法论屏编辑修复。
            </span>
          </div>
          <button className="teaching-toast-close" onClick={dismissSkillBootstrapWarning} type="button">✕</button>
        </div>
      ) : null}
      <BrainToast
        onDismiss={dismissRecruitmentToast}
        onOpen={() => {
          setRoute("brain-specialists");
          dismissRecruitmentToast();
        }}
        toast={recruitmentToast}
      />
      <ErrorToastHost />
    </>
  );
}
