import type { FlowDetailResponse, FlowListItem } from "../../api/debug";

interface AgentFlowPanelProps {
  flows: FlowListItem[];
  selectedFlow: FlowDetailResponse | null;
  onRefresh: () => void;
  onSelect: (workflowId: string) => void;
  onOpenTrace: (traceId: string) => void;
}

export function AgentFlowPanel({
  flows,
  selectedFlow,
  onRefresh,
  onSelect,
  onOpenTrace,
}: AgentFlowPanelProps): JSX.Element {
  return (
    <section className="debug-panel" aria-label="Agent flow timeline">
      <div className="debug-panel-header">
        <div>
          <h2>Agent Flow</h2>
          <p>{flows.length} workflows</p>
        </div>
        <button type="button" onClick={onRefresh}>Refresh</button>
      </div>

      <div className="debug-list">
        {flows.length === 0 ? (
          <div className="debug-empty">No workflow transitions available.</div>
        ) : (
          flows.map((flow) => (
            <button
              key={flow.workflowId}
              className="debug-list-row"
              type="button"
              onClick={() => onSelect(flow.workflowId)}
            >
              <span>{flow.workflowId}</span>
              <strong>{flow.lastEventType}</strong>
              <small>{flow.transitionCount} transitions · {flow.linkedTraceCount} linked</small>
            </button>
          ))
        )}
      </div>

      <div className="debug-detail" aria-label="Agent flow detail">
        {!selectedFlow ? (
          <div className="debug-detail-empty">Select a workflow to inspect its timeline.</div>
        ) : selectedFlow.transitions.length === 0 ? (
          <div className="debug-detail-empty">This workflow has no projected transitions.</div>
        ) : (
          <ol className="debug-flow-timeline">
            {selectedFlow.transitions.map((transition) => (
              <li key={transition.transitionId}>
                <strong>{transition.eventType}</strong>
                <span>{transition.status} · {transition.linkStatus}</span>
                <small>{transition.detailProvenance} · {transition.detailAvailability}</small>
                {transition.detail !== null && transition.detail !== undefined ? (
                  <pre>{JSON.stringify(transition.detail, null, 2)}</pre>
                ) : null}
                {transition.traceIds.length > 0 ? (
                  <div className="debug-flow-trace-links">
                    {transition.traceIds.map((traceId) => (
                      <button
                        key={traceId}
                        type="button"
                        onClick={() => onOpenTrace(traceId)}
                      >
                        Open trace {traceId}
                      </button>
                    ))}
                  </div>
                ) : null}
              </li>
            ))}
          </ol>
        )}
      </div>
    </section>
  );
}
