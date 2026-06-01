import { History, Users } from "lucide-react";

import SkillDiffView from "../../components/SkillDiffView";
import type { SkillEquipmentAuditResponse, SkillHistoryResponse } from "../../api/skillsMethodology";
import { formatDateTime as formatDate } from "../../utils/dates";
import { Badge } from "../../components/primitives";

export function SkillAuditView({
  history,
  audit,
}: {
  history: SkillHistoryResponse | null;
  audit: SkillEquipmentAuditResponse | null;
}): JSX.Element {
  return (
    <section className="methodology-audit-view me-scroll" aria-label="方法论审计">
      <div className="methodology-audit-column">
        <div className="brain-section-title">
          <span><History size={14} /> 版本链</span>
          <small>{history?.nodes.length ?? 0} 个版本</small>
        </div>
        {history?.nodes.slice().reverse().map((node) => (
          <article className="methodology-version-node" key={node.skill_id}>
            <div className="methodology-version-head">
              <strong>v{node.version} · {node.name}</strong>
              <Badge tone={node.origin === "user_edit" ? "ok" : "neutral"}>{node.origin}</Badge>
            </div>
            <small>{formatDate(node.created_at)} · {node.changed_by || "unknown"}</small>
            <p>{node.change_reason || "无变更说明"}</p>
            <SkillDiffView body={node.body_markdown} diff={node.diff_from_previous} />
          </article>
        ))}
        {!history || history.nodes.length === 0 ? <div className="brain-empty">暂无版本历史</div> : null}
      </div>

      <div className="methodology-audit-column">
        <div className="brain-section-title">
          <span><Users size={14} /> 装备轨迹</span>
          <small>{audit?.rows.length ?? 0} 条</small>
        </div>
        {audit?.rows.map((row, index) => (
          <article className="methodology-equipment-audit-row" key={`${row.equipped_entity_id}-${row.equipped_at}-${index}`}>
            <div>
              <strong>{row.equipped_entity_name || row.equipped_entity_id}</strong>
              <small>{row.equipped_entity_type} · {formatDate(row.equipped_at)}</small>
            </div>
            <Badge tone={row.status === "active" ? "ok" : "neutral"}>
              {row.status === "active" ? "已装备" : row.unequipped_reason || "已卸下"}
            </Badge>
          </article>
        ))}
        {!audit || audit.rows.length === 0 ? <div className="brain-empty">暂无装备历史</div> : null}
      </div>
    </section>
  );
}

export default SkillAuditView;
