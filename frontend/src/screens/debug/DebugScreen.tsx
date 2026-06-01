/**
 * Hidden DebugScreen — only accessible via direct /debug navigation.
 *
 * Disabled: shows warning + arm control, no raw trace data.
 * Armed: shows trace list, Agent Flow, reference expansion.
 * Raw state lives in component memory only; purge on clear/disable/route leave.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import type {
  DebugControlStatus,
  TraceDetail,
  TraceListItem,
  FlowDetailResponse,
  FlowListItem,
  ReferenceResponse,
} from "../../api/debug";
import {
  getControlStatus,
  updateControl,
  listTraces,
  getTraceDetail,
  clearTraces,
  listFlows,
  getFlowDetail,
  expandReference,
  dispatchDebugControlStatus,
  DEBUG_RAW_STATE_PURGE_EVENT,
} from "../../api/debug";
import { TracePanel } from "./TracePanel";
import { AgentFlowPanel } from "./AgentFlowPanel";
import { ReferencePanel } from "./ReferencePanel";

const REQUIRED_WARNING_COPY = [
  "调试记录可能包含原始用户和模型文本。",
  "开发者自行输入的秘密不会被启发式清除。",
  "停止、清空或重启会销毁当前记录。",
  "启用期间应用壳会显示持续停止入口。",
];

export default function DebugScreen(): JSX.Element {
  const [status, setStatus] = useState<DebugControlStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [warningAcknowledged, setWarningAcknowledged] = useState(false);

  // Trace state (memory only)
  const [traces, setTraces] = useState<TraceListItem[]>([]);
  const [selectedTrace, setSelectedTrace] = useState<TraceDetail | null>(null);

  // Flow state (memory only)
  const [flows, setFlows] = useState<FlowListItem[]>([]);
  const [selectedFlow, setSelectedFlow] = useState<FlowDetailResponse | null>(null);

  // Reference state (memory only)
  const [referenceResult, setReferenceResult] = useState<ReferenceResponse | null>(null);
  const statusRequestVersion = useRef(0);

  const purgeLocalState = useCallback(() => {
    setTraces([]);
    setSelectedTrace(null);
    setFlows([]);
    setSelectedFlow(null);
    setReferenceResult(null);
  }, []);

  const refreshStatus = useCallback(async () => {
    const requestVersion = ++statusRequestVersion.current;
    try {
      const s = await getControlStatus();
      if (requestVersion !== statusRequestVersion.current) return;
      setStatus(s);
      dispatchDebugControlStatus(s);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to fetch status");
    }
  }, []);

  useEffect(() => {
    void refreshStatus();
  }, [refreshStatus]);

  // Purge on route leave
  useEffect(() => {
    return purgeLocalState;
  }, [purgeLocalState]);

  useEffect(() => {
    const handlePurge = () => {
      purgeLocalState();
      setWarningAcknowledged(false);
      void refreshStatus();
    };
    window.addEventListener(DEBUG_RAW_STATE_PURGE_EVENT, handlePurge);
    return () => window.removeEventListener(DEBUG_RAW_STATE_PURGE_EVENT, handlePurge);
  }, [purgeLocalState, refreshStatus]);

  const handleArm = useCallback(async () => {
    if (!warningAcknowledged) return;
    setLoading(true);
    setError(null);
    const requestVersion = ++statusRequestVersion.current;
    try {
      const s = await updateControl({ enabled: true, warningAcknowledged: true });
      if (requestVersion !== statusRequestVersion.current) return;
      setStatus(s);
      dispatchDebugControlStatus(s);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to arm trace");
    } finally {
      setLoading(false);
    }
  }, [warningAcknowledged]);

  const handleStop = useCallback(async () => {
    setLoading(true);
    setError(null);
    const requestVersion = ++statusRequestVersion.current;
    try {
      const s = await updateControl({ enabled: false });
      if (requestVersion !== statusRequestVersion.current) return;
      setStatus(s);
      dispatchDebugControlStatus(s);
      purgeLocalState();
      setWarningAcknowledged(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to stop trace");
    } finally {
      setLoading(false);
    }
  }, [purgeLocalState]);

  const handleClear = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      await clearTraces();
      purgeLocalState();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to clear");
    } finally {
      setLoading(false);
    }
  }, [purgeLocalState]);

  const handleRefreshTraces = useCallback(async () => {
    try {
      const result = await listTraces({ limit: 50 });
      setTraces(result.items);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load traces");
    }
  }, []);

  const handleSelectTrace = useCallback(async (traceId: string) => {
    try {
      const detail = await getTraceDetail(traceId);
      setSelectedTrace(detail);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load trace detail");
    }
  }, []);

  const handleRefreshFlows = useCallback(async () => {
    try {
      const result = await listFlows({ limit: 20 });
      setFlows(result.items);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load flows");
    }
  }, []);

  const handleSelectFlow = useCallback(async (workflowId: string) => {
    try {
      const detail = await getFlowDetail(workflowId);
      setSelectedFlow(detail);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load flow detail");
    }
  }, []);

  const handleExpandReference = useCallback(async (referenceId: string) => {
    try {
      const result = await expandReference(referenceId);
      setReferenceResult(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to expand reference");
    }
  }, []);

  const enabled = status?.enabled ?? false;

  return (
    <div className="debug-screen">
      <div className="debug-header">
        <h1>Debug Inspector</h1>
        <span className="debug-status-badge" data-enabled={enabled}>
          {enabled ? "ARMED" : "DISABLED"}
        </span>
      </div>

      {error ? <div className="debug-error">{error}</div> : null}

      {!enabled ? (
        <div className="debug-warning-panel">
          <h2>Sensitive Content Warning</h2>
          <ul className="debug-warning-list">
            {REQUIRED_WARNING_COPY.map((text, i) => (
              <li key={i}>{text}</li>
            ))}
          </ul>
          <label className="debug-warning-checkbox">
            <input
              type="checkbox"
              checked={warningAcknowledged}
              onChange={(e) => setWarningAcknowledged(e.currentTarget.checked)}
            />
            I understand the risks and want to enable trace capture
          </label>
          <button
            className="debug-arm-btn"
            disabled={!warningAcknowledged || loading}
            onClick={handleArm}
            type="button"
          >
            {loading ? "Enabling..." : "Enable Trace Capture"}
          </button>
        </div>
      ) : (
        <div className="debug-active-panel">
          <div className="debug-toolbar">
            <button onClick={handleStop} disabled={loading} type="button">
              Stop Trace
            </button>
            <button onClick={handleClear} disabled={loading} type="button">
              Clear
            </button>
          </div>

          <div className="debug-panels">
            <TracePanel
              traces={traces}
              selectedTrace={selectedTrace}
              onRefresh={handleRefreshTraces}
              onSelect={handleSelectTrace}
            />
            <AgentFlowPanel
              flows={flows}
              selectedFlow={selectedFlow}
              onRefresh={handleRefreshFlows}
              onSelect={handleSelectFlow}
              onOpenTrace={handleSelectTrace}
            />
            <ReferencePanel
              result={referenceResult}
              onExpand={handleExpandReference}
            />
          </div>
        </div>
      )}
    </div>
  );
}
