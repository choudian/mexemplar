import { ArrowDown, ArrowUp, Save } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import TokenBudgetMeter from "../../components/TokenBudgetMeter";
import { Button, IconButton } from "../../components/primitives";
import { estimateEquipmentTokens, useSkillMethodologyStore } from "../../state/skillMethodologyStore";
import type { SkillMethodologySummary } from "../../api/skillsMethodology";

export function EquipmentPanel({
  entityId,
  compact = false,
}: {
  entityId: string;
  compact?: boolean;
}): JSX.Element {
  const items = useSkillMethodologyStore((state) => state.items);
  const equipment = useSkillMethodologyStore((state) => state.equipmentByEntity[entityId]);
  const tokenBudgetThresholds = useSkillMethodologyStore((state) => state.tokenBudgetThresholds);
  const saving = useSkillMethodologyStore((state) => state.saving);
  const load = useSkillMethodologyStore((state) => state.load);
  const loadEquipment = useSkillMethodologyStore((state) => state.loadEquipment);
  const saveEquipment = useSkillMethodologyStore((state) => state.saveEquipment);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);

  useEffect(() => {
    void load();
    void loadEquipment(entityId);
  }, [entityId, load, loadEquipment]);

  useEffect(() => {
    if (!equipment) return;
    const active = Array.isArray(equipment.active_equipment) ? equipment.active_equipment : [];
    setSelectedIds(active.map((item) => item.skill_id));
  }, [equipment]);

  const selectedItems = useMemo(
    () => selectedIds
      .map((id) => items.find((item) => item.skill_id === id))
      .filter((item): item is SkillMethodologySummary => Boolean(item)),
    [items, selectedIds],
  );
  const tokenEstimate = useMemo(() => estimateEquipmentTokens(selectedItems), [selectedItems]);
  const missingRequiredTools = (equipment?.active_equipment ?? []).flatMap((item) =>
    item.missing_required_tools.map((tool) => `${item.name}: ${tool}`),
  );

  const toggleSkill = (skillId: string) => {
    setSelectedIds((current) =>
      current.includes(skillId)
        ? current.filter((id) => id !== skillId)
        : [...current, skillId],
    );
  };
  const move = (skillId: string, direction: -1 | 1) => {
    setSelectedIds((current) => {
      const index = current.indexOf(skillId);
      const nextIndex = index + direction;
      if (index < 0 || nextIndex < 0 || nextIndex >= current.length) return current;
      const next = [...current];
      [next[index], next[nextIndex]] = [next[nextIndex], next[index]];
      return next;
    });
  };

  return (
    <section className={compact ? "equipment-panel equipment-panel-compact" : "equipment-panel"} aria-label="方法论装备">
      <div className="brain-section-title">
        <span>方法论装备</span>
        <small>{selectedIds.length} 条已选</small>
      </div>
      <TokenBudgetMeter
        itemCount={selectedIds.length}
        thresholds={tokenBudgetThresholds ?? equipment?.token_budget_thresholds ?? null}
        tokenEstimate={tokenEstimate}
      />
      {missingRequiredTools.length > 0 ? (
        <div className="equipment-warning">
          {missingRequiredTools.map((item) => <span key={item}>{item}</span>)}
        </div>
      ) : null}
      <div className="equipment-skill-list">
        {items.map((skill) => {
          const checked = selectedIds.includes(skill.skill_id);
          return (
            <label className="equipment-skill-option" data-active={checked} key={skill.skill_id}>
              <input checked={checked} onChange={() => toggleSkill(skill.skill_id)} type="checkbox" />
              <span>
                <strong>{skill.name}</strong>
                <small>{skill.description || "无描述"}</small>
              </span>
              {checked ? (
                <span className="equipment-order-actions">
                  <IconButton label={`上移 ${skill.name}`} onClick={() => move(skill.skill_id, -1)}>
                    <ArrowUp size={13} />
                  </IconButton>
                  <IconButton label={`下移 ${skill.name}`} onClick={() => move(skill.skill_id, 1)}>
                    <ArrowDown size={13} />
                  </IconButton>
                </span>
              ) : null}
            </label>
          );
        })}
        {items.length === 0 ? <div className="brain-empty">暂无 active 方法论</div> : null}
      </div>
      <Button
        disabled={saving}
        kind="primary"
        onClick={() => {
          void saveEquipment(entityId, selectedIds);
        }}
      >
        <Save size={14} />
        保存装备
      </Button>
    </section>
  );
}

export default EquipmentPanel;
