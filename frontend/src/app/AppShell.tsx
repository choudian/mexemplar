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
import StructuredConfirmationCard from "../components/StructuredConfirmationCard";
import { useAssistantStore } from "../state/assistantStore";
import { useAssistantTaskStore } from "../state/assistantTaskStore";
import { useBrainStore } from "../state/brainStore";
import { useCompositionsStore } from "../state/compositionsStore";
import { useScheduledStore } from "../state/scheduledStore";
import { useSettingsStore } from "../state/settingsStore";
import { useShellStore } from "../state/shellStore";
import { useSkillMethodologyStore } from "../state/skillMethodologyStore";
import { useSkillsStore } from "../state/skillsStore";
import { useSpecialistStore } from "../state/specialistStore";
import { useMcpStore } from "../state/mcpStore";
import { useTeachingStore } from "../state/teachingStore";
import { BackendGate } from "./BackendGate";
import { BackendStatus } from "./BackendStatus";
import { ErrorToastHost } from "./ErrorToastHost";
import { InfoToastHost } from "./InfoToastHost";
import { CustomTitlebar } from "./CustomTitlebar";
import { NavRail } from "./NavRail";
import { applyTheme, writeAppearanceMirror } from "./applyTheme";
import { getHiddenRoute, getRoute, redirectPathFor, routeIdFromPath, routePaths } from "./routes";
import { isToolRenameToastDismissed, markToolRenameToastDismissed } from "./toolRenameToastStorage";

const BOOTSTRAP_RETRY_DELAYS_MS = [250, 500, 1000, 1500, 2000, 3000, 4000, 5000, 5000];

const TOAST_AUTO_DISMISS_MS = 8000;
const SEEN_EVENT_ID_LIMIT = 500;
const TEACHING_STAGE_REDIRECT_MS = 3000;
const AUTHORITATIVE_RESYNC_MAX_ATTEMPTS = 3;

const FAILED_BACKEND: BackendConnectionState = {
  status: "failed",
  message: "无法连接本地后端。请重新启动应用或查看日志。",
  checks: [{ name: "sidecar", status: "failed", message: "Sidecar request failed." }],
  serverTime: "",
};

const TASK_COLLAB_EVENT_TYPES = new Set([
  "assistant.task_graph.changed",
  "assistant.task_board.changed",
  "assistant.task_question.changed",
  "assistant.meeting.changed",
  "assistant.todo.changed",
  "user_task.changed",
]);

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

function isSavedTeachingToolEvent(event: UiEvent): boolean {
  return event.type === "tools.changed" &&
    event.payload.status === "saved" &&
    typeof event.scope.workflowId === "string" &&
    event.scope.workflowId.length > 0;
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
  const applyMcpEvent = useMcpStore((state) => state.applyEvent);
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
  const refreshExecutionReviews = useBrainStore((state) => state.loadExecutionReviews);
  const refreshImprovementProposals = useBrainStore((state) => state.loadImprovementProposals);
  const refreshBrainSkillPool = useBrainStore((state) => state.loadSkillPool);
  const applySpecialistEvent = useSpecialistStore((state) => state.applyEvent);
  const refreshSpecialists = useSpecialistStore((state) => state.load);
  const applyScheduledEvent = useScheduledStore((state) => state.applyEvent);
  const refreshScheduled = useScheduledStore((state) => state.load);
  const refreshScheduledPending = useScheduledStore((state) => state.refreshPendingConfirmation);
  const [debugTraceActive, setDebugTraceActive] = useState(false);
  const [retryNonce, setRetryNonce] = useState(0);
  const [pathname, setPathname] = useState(() => window.location.pathname);
  const [toolRenameToastOpen, setToolRenameToastOpen] = useState(
    () => !isToolRenameToastDismissed(),
  );
  const debugStatusVersion = useRef(0);
  const pendingSkillRedirectTimer = useRef<number | undefined>(undefined);

  const navigateVisibleRoute = useCallback((nextRoute: Parameters<typeof setRoute>[0]) => {
    const nextPath = routePaths[nextRoute];
    if (nextPath && window.location.pathname !== nextPath) {
      window.history.pushState({}, "", nextPath);
      setPathname(nextPath);
    }
    setRoute(nextRoute);
  }, [setRoute]);

  const schedulePendingSkillRedirect = useCallback((workflowId: string) => {
    if (pendingSkillRedirectTimer.current !== undefined) {
      window.clearTimeout(pendingSkillRedirectTimer.current);
    }
    pendingSkillRedirectTimer.current = window.setTimeout(() => {
      const teachingState = useTeachingStore.getState();
      if (teachingState.skillTrialToolId || teachingState.run?.workflowId !== workflowId) {
        return;
      }
      useSkillsStore.getState().setCategory("pending");
      void useSkillsStore.getState().loadAllCategories();
      navigateVisibleRoute("skills");
    }, TEACHING_STAGE_REDIRECT_MS);
  }, [navigateVisibleRoute]);

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
        writeAppearanceMirror(applyTheme(bootstrap.settingsSummary));
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
          // FR-022：transport 级 resync（SSE 重连/缺口）也要刷新任务协作权威快照。
          // graph/board/meeting/todos 由 store 的 executeResync 统一重拉
          // （它持有具体 channelId/taskId）；这里置标记触发它，避免重连后任务面板停留
          // 在陈旧快照。通过 store 方法设置，不直接 setState。
          useAssistantTaskStore.getState().markNeedsResync();
        }
      }
      if (!domains || domains.includes("brain")) {
        const activeBrainZone = useBrainStore.getState().activeZone ?? "hot";
        refreshes.push(refreshBrainZones());
        refreshes.push(refreshBrainEntries(activeBrainZone));
        refreshes.push(refreshBrainSegments());
        refreshes.push(refreshExecutionReviews());
        refreshes.push(refreshImprovementProposals());
        refreshes.push(refreshBrainSkillPool());
        refreshes.push(refreshSpecialists());
      }
      if (!domains || domains.includes("scheduled") || domains.includes("scheduling")) {
        refreshes.push(refreshScheduled());
        refreshes.push(refreshScheduledPending());
      }
      await Promise.all(refreshes);
    };

    const refreshAuthoritativeStateWithRetry = async (domains?: string[]) => {
      let lastError: unknown;
      for (let attempt = 1; attempt <= AUTHORITATIVE_RESYNC_MAX_ATTEMPTS; attempt += 1) {
        try {
          await refreshAuthoritativeState(domains);
          return;
        } catch (error) {
          lastError = error;
          if (cancelled || controller.signal.aborted) {
            throw error;
          }
        }
      }
      throw lastError;
    };

    const dispatchUiEvent = (event: UiEvent) => {
      switch (getUiEventHandlerDomain(event)) {
        case "assistant":
          applyAssistantEvent(event);
          if (TASK_COLLAB_EVENT_TYPES.has(event.type)) {
            useAssistantTaskStore.getState().applyEvent(event);
          }
          break;
        case "teaching":
          applyTeachingEvent(event);
          break;
        case "skills":
          applySkillsEvent(event);
          applyMcpEvent(event);
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
        case "scheduled":
          applyScheduledEvent(event);
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
              await refreshAuthoritativeStateWithRetry(event.payload.domains);
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
          if (isSavedTeachingToolEvent(event)) {
            schedulePendingSkillRedirect(event.scope.workflowId);
          }
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
          writeAppearanceMirror(applyTheme(bootstrap.settingsSummary));
          void loadSkillBootstrapStatus();
          // FR-020：启动即加载改进提案，使全局大脑导航的 pending_review 徽标在用户
          // 进入 Brain 屏之前就可见，避免提案静悄悄躺在管理屏无人知。
          void useBrainStore.getState().loadImprovementProposals();
          // 调度确认卡是跨屏全局挂载：启动即拉 pending，断连/重启后用户仍能看到待确认任务。
          void useScheduledStore
            .getState()
            .refreshPendingConfirmation()
            .catch(() => undefined);
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
    applyScheduledEvent,
    hydrate,
    refreshBrainEntries,
    refreshBrainSegments,
    refreshExecutionReviews,
    refreshImprovementProposals,
    refreshBrainSkillPool,
    refreshBrainZones,
    refreshCompositions,
    refreshSettings,
    refreshSkillMethodologies,
    refreshSkills,
    refreshSpecialists,
    refreshTeaching,
    refreshScheduled,
    refreshScheduledPending,
    setBackend,
    setAssistantIdleThresholdSeconds,
    loadSkillBootstrapStatus,
    schedulePendingSkillRedirect,
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
  const teachingStage = useTeachingStore((state) => state.stage);
  const teachingWorkflowId = useTeachingStore((state) => state.run?.workflowId ?? null);
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
    if (!teachingWorkflowId || skillTrialToolId || teachingStage !== "learning") return;
    const timer = window.setTimeout(() => {
      navigateVisibleRoute("assistant");
    }, TEACHING_STAGE_REDIRECT_MS);
    return () => window.clearTimeout(timer);
  }, [navigateVisibleRoute, skillTrialToolId, teachingStage, teachingWorkflowId]);

  useEffect(() => {
    return () => {
      if (pendingSkillRedirectTimer.current !== undefined) {
        window.clearTimeout(pendingSkillRedirectTimer.current);
        pendingSkillRedirectTimer.current = undefined;
      }
    };
  }, []);

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
      <ScheduledConfirmationOverlay />
      <ErrorToastHost />
      <InfoToastHost />
    </>
  );
}

/**
 * 调度确认卡全局浮层。创建定时任务的确认可能发生在任意路由（用户正对话时跨屏），
 * 因此挂到 AppShell 而不是具体屏；payload 与提交决策都走 scheduledStore。
 */
function ScheduledConfirmationOverlay(): JSX.Element | null {
  const pendingConfirmation = useScheduledStore((state) => state.pendingConfirmation);
  const submitting = useScheduledStore((state) => state.submittingConfirmation);
  const submitConfirmation = useScheduledStore((state) => state.submitConfirmation);
  const cancelConfirmation = useScheduledStore((state) => state.cancelConfirmation);

  if (!pendingConfirmation) return null;
  const { requestId, draft, expiresAt, unattendedAutoApprove } = pendingConfirmation;

  return (
    <div className="scheduled-confirmation-overlay" aria-live="polite">
      <StructuredConfirmationCard
        requestId={requestId}
        draft={draft}
        expiresAt={expiresAt}
        unattendedAutoApprove={unattendedAutoApprove}
        submitting={submitting}
        onSubmit={(editedDraft, autoApprove) =>
          void submitConfirmation(requestId, "confirm", editedDraft, autoApprove)
        }
        onCancel={() => void cancelConfirmation(requestId)}
      />
    </div>
  );
}
