import { Gauge } from "lucide-react";

import type { TokenBudgetThresholds } from "../api/skillsMethodology";

export function TokenBudgetMeter({
  itemCount,
  tokenEstimate,
  thresholds,
}: {
  itemCount: number;
  tokenEstimate: number;
  thresholds: TokenBudgetThresholds | null;
}): JSX.Element {
  const warn = thresholds?.warn_threshold ?? Number.POSITIVE_INFINITY;
  const danger = thresholds?.danger_threshold ?? Number.POSITIVE_INFINITY;
  const denominator = Number.isFinite(danger) && danger > 0 ? danger : Math.max(tokenEstimate, 1);
  const percent = Math.min(100, Math.round((tokenEstimate / denominator) * 100));
  const tone = tokenEstimate >= danger ? "danger" : tokenEstimate >= warn ? "warn" : "ok";

  return (
    <div className="token-budget-meter" data-tone={tone}>
      <div className="token-budget-meter-head">
        <span>
          <Gauge size={14} />
          装备预算
        </span>
        <strong>{tokenEstimate} tokens</strong>
      </div>
      <div className="token-budget-track" aria-label="token 预算使用量">
        <i style={{ width: `${percent}%` }} />
      </div>
      <div className="token-budget-meter-foot">
        <span>{itemCount} 条方法论</span>
        <span>
          warn {thresholds?.warn_threshold ?? "-"} / danger {thresholds?.danger_threshold ?? "-"}
        </span>
      </div>
    </div>
  );
}

export default TokenBudgetMeter;
