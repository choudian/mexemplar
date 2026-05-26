import { useState } from "react";

import type { ReferenceResponse } from "../../api/debug";

interface ReferencePanelProps {
  result: ReferenceResponse | null;
  onExpand: (referenceId: string) => void;
}

export function ReferencePanel({ result, onExpand }: ReferencePanelProps): JSX.Element {
  const [referenceId, setReferenceId] = useState("");

  return (
    <section className="debug-panel" aria-label="Reference expansion">
      <div className="debug-panel-header">
        <div>
          <h2>Reference</h2>
          <p>Expand current-process references while armed</p>
        </div>
        <button
          type="button"
          disabled={!referenceId.trim()}
          onClick={() => onExpand(referenceId.trim())}
        >
          Expand
        </button>
      </div>
      <input
        className="debug-reference-input"
        aria-label="Reference id"
        value={referenceId}
        onChange={(event) => setReferenceId(event.currentTarget.value)}
        placeholder="reference id"
      />
      <div className="debug-detail" aria-label="Reference detail">
        {!result ? (
          <div className="debug-detail-empty">No reference expanded.</div>
        ) : (
          <>
            <div className="debug-kv">
              <span>Reference</span>
              <strong>{result.referenceId}</strong>
            </div>
            <div className="debug-kv">
              <span>Status</span>
              <strong>{result.truncated ? "truncated" : "full"}</strong>
            </div>
            <pre>{result.content ?? ""}</pre>
          </>
        )}
      </div>
    </section>
  );
}
