import type { TraceDetail, TraceListItem } from "../../api/debug";

interface TracePanelProps {
  traces: TraceListItem[];
  selectedTrace: TraceDetail | null;
  onRefresh: () => void;
  onSelect: (traceId: string) => void;
}

export function TracePanel({
  traces,
  selectedTrace,
  onRefresh,
  onSelect,
}: TracePanelProps): JSX.Element {
  return (
    <section className="debug-panel" aria-label="LLM trace records">
      <div className="debug-panel-header">
        <div>
          <h2>Trace</h2>
          <p>{traces.length} records in memory</p>
        </div>
        <button type="button" onClick={onRefresh}>Refresh</button>
      </div>

      <div className="debug-list">
        {traces.length === 0 ? (
          <div className="debug-empty">No trace records captured in this epoch.</div>
        ) : (
          traces.map((trace) => (
            <button
              key={trace.traceId}
              className="debug-list-row"
              type="button"
              onClick={() => onSelect(trace.traceId)}
            >
              <span>{trace.source || "unknown"}</span>
              <strong>{trace.method}</strong>
              <small>{trace.outcome} · {trace.detailAvailability}</small>
            </button>
          ))
        )}
      </div>

      <TraceDetailView trace={selectedTrace} />
    </section>
  );
}

function TraceDetailView({ trace }: { trace: TraceDetail | null }): JSX.Element {
  if (!trace) {
    return <div className="debug-detail-empty">Select a trace to inspect retained detail.</div>;
  }

  return (
    <div className="debug-detail" aria-label="Trace detail">
      <div className="debug-kv">
        <span>Trace</span>
        <strong>{trace.traceId}</strong>
      </div>
      <div className="debug-kv">
        <span>Source</span>
        <strong>{trace.source || "unknown"}</strong>
      </div>
      <div className="debug-kv">
        <span>Retained</span>
        <strong>{trace.retainedBytes} bytes</strong>
      </div>
      <pre>{JSON.stringify({
        inputMessages: trace.inputMessages,
        inputMedia: trace.inputMedia,
        inputTools: trace.inputTools,
        outputContent: trace.outputContent,
        outputToolCalls: trace.outputToolCalls,
        errorSummary: trace.errorSummary,
      }, null, 2)}</pre>
    </div>
  );
}
