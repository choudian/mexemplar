import { GitBranch } from "lucide-react";

import type { BrainMemoryEntry } from "../../api/brain";
import { Badge } from "../../components/primitives";
import { statusToTone } from "../../components/statusTone";

interface EntryEvolutionProps {
  chain: BrainMemoryEntry[];
  loading: boolean;
}

const ENTRY_STATUS_TONES = {
  active: "ok",
  fading: "warn",
  invalidated: "warn",
  "soft-deleted": "danger",
} as const;

function changeHint(previous: BrainMemoryEntry | null, current: BrainMemoryEntry): string {
  if (!previous) return "初始版本";
  const changes: string[] = [];
  if (previous.content !== current.content) changes.push("内容更新");
  if (previous.scope !== current.scope) changes.push("适用范围调整");
  if (previous.status !== current.status) changes.push("状态变化");
  return changes.length ? changes.join(" / ") : "无显著差异";
}

export function EntryEvolution({ chain, loading }: EntryEvolutionProps): JSX.Element {
  return (
    <section className="brain-evolution" aria-label="条目演化链">
      <div className="brain-section-title">
        <GitBranch size={15} />
        <span>演化链</span>
      </div>
      {loading ? <div className="brain-empty">正在加载演化链</div> : null}
      {!loading && chain.length === 0 ? <div className="brain-empty">选择条目查看演化链</div> : null}
      <ol className="brain-evolution-list">
        {chain.map((entry, index) => (
          <li key={entry.entry_id}>
            <div className="brain-evolution-meta">
              <span className="me-mono">v{index + 1}</span>
              <Badge tone={statusToTone(entry.status, ENTRY_STATUS_TONES)}>{entry.status}</Badge>
              <small>{changeHint(index > 0 ? chain[index - 1] : null, entry)}</small>
            </div>
            <p>{entry.content}</p>
            {entry.scope ? <small>范围：{entry.scope}</small> : null}
          </li>
        ))}
      </ol>
    </section>
  );
}

export default EntryEvolution;
