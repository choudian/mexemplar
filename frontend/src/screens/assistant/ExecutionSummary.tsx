import { ChevronDown, ChevronRight, Loader2 } from "lucide-react";
import { useState } from "react";

function ExecutionSummary({
  status,
  headline,
}: {
  status: string;
  headline: string;
}): JSX.Element | null {
  const [expanded, setExpanded] = useState(false);
  if (!headline && status === "idle") {
    return null;
  }

  const running = status === "running";
  return (
    <div className="assistant-execution-summary" data-status={status}>
      <button type="button" onClick={() => setExpanded((value) => !value)}>
        {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        {running ? <Loader2 className="assistant-spin" size={14} /> : null}
        <span>{headline || "执行状态已更新"}</span>
      </button>
      {expanded ? (
        <div className="assistant-execution-details">
          <span>状态</span>
          <strong>{status}</strong>
        </div>
      ) : null}
    </div>
  );
}

export default ExecutionSummary;
