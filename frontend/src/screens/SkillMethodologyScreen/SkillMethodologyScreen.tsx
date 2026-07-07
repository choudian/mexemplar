import { AlertTriangle, BookOpenCheck, GitBranch, ListChecks, Store } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Button } from "../../components/primitives";
import { useAssistantStore } from "../../state/assistantStore";
import { useBrainStore } from "../../state/brainStore";
import { useSkillMethodologyStore } from "../../state/skillMethodologyStore";
import SkillActiveList from "./SkillActiveList";
import SkillAuditView from "./SkillAuditView";
import SkillDangerConfirm from "./SkillDangerConfirm";
import SkillEditor from "./SkillEditor";
import { SkillStoreTab } from "../skills/SkillStoreTab";

export function SkillMethodologyScreen(): JSX.Element {
  const items = useSkillMethodologyStore((state) => state.items);
  const selectedSkillId = useSkillMethodologyStore((state) => state.selectedSkillId);
  const selectedDetail = useSkillMethodologyStore((state) => state.selectedDetail);
  const history = useSkillMethodologyStore((state) => state.history);
  const equipmentAudit = useSkillMethodologyStore((state) => state.equipmentAudit);
  const sortKey = useSkillMethodologyStore((state) => state.sortKey);
  const filterKey = useSkillMethodologyStore((state) => state.filterKey);
  const editDraft = useSkillMethodologyStore((state) => state.editDraft);
  const hydrated = useSkillMethodologyStore((state) => state.hydrated);
  const loading = useSkillMethodologyStore((state) => state.loading);
  const loadingDetail = useSkillMethodologyStore((state) => state.loadingDetail);
  const saving = useSkillMethodologyStore((state) => state.saving);
  const bootstrapWarning = useSkillMethodologyStore((state) => state.bootstrapWarning);
  const load = useSkillMethodologyStore((state) => state.load);
  const loadBootstrapStatus = useSkillMethodologyStore((state) => state.loadBootstrapStatus);
  const selectSkill = useSkillMethodologyStore((state) => state.selectSkill);
  const setSortKey = useSkillMethodologyStore((state) => state.setSortKey);
  const setFilterKey = useSkillMethodologyStore((state) => state.setFilterKey);
  const setDraftField = useSkillMethodologyStore((state) => state.setDraftField);
  const saveDraft = useSkillMethodologyStore((state) => state.saveDraft);
  const softDeleteSelected = useSkillMethodologyStore((state) => state.softDeleteSelected);
  const dismissBootstrapWarning = useSkillMethodologyStore((state) => state.dismissBootstrapWarning);
  const confirmations = useAssistantStore((state) => state.confirmations);
  const decideConfirmation = useAssistantStore((state) => state.decideConfirmation);
  const skillPool = useBrainStore((state) => state.skillPool);
  const loadingSkillPool = useBrainStore((state) => state.loadingSkillPool);
  const loadSkillPool = useBrainStore((state) => state.loadSkillPool);

  const [view, setView] = useState<"active" | "store" | "audit">("active");
  const [listCollapsed, setListCollapsed] = useState(false);

  useEffect(() => {
    if (hydrated) return;
    void load();
  }, [hydrated, load]);

  useEffect(() => {
    void loadBootstrapStatus();
  }, [loadBootstrapStatus]);

  useEffect(() => {
    void loadSkillPool();
  }, [loadSkillPool]);

  const skillConfirmation = confirmations.find(
    (confirmation) =>
      confirmation.actionType === "skill.edit_protected" || confirmation.actionType === "skill.soft_delete",
  );
  const affectedNames = useMemo(() => {
    if (skillConfirmation?.affectedSpecialistNames?.length) {
      return skillConfirmation.affectedSpecialistNames;
    }
    return (equipmentAudit?.rows ?? [])
      .filter((row) => row.status === "active")
      .map((row) => row.equipped_entity_name || row.equipped_entity_id);
  }, [equipmentAudit, skillConfirmation]);
  const confirmationTitle =
    skillConfirmation?.actionType === "skill.edit_protected"
      ? "确认编辑受保护方法论"
      : "确认软删除方法论";

  return (
    <section className="methodology-screen" aria-label="方法论">
      <header className="methodology-header">
        <div>
          <h2>方法论</h2>
          <p>沉淀、修订和装备可按需加载的 Skill 方法论</p>
        </div>
        <div className="methodology-header-actions" aria-label="方法论视图" role="group">
          <Button
            aria-pressed={view === "active"}
            kind={view === "active" ? "primary" : "ghost"}
            onClick={() => setView("active")}
          >
            <ListChecks size={14} />
            我的方法论
          </Button>
          <Button
            aria-pressed={view === "store"}
            kind={view === "store" ? "primary" : "ghost"}
            onClick={() => setView("store")}
          >
            <Store size={14} />
            技能商店
          </Button>
          <Button
            aria-pressed={view === "audit"}
            disabled={!selectedDetail}
            kind={view === "audit" ? "primary" : "ghost"}
            onClick={() => setView("audit")}
          >
            <GitBranch size={14} />
            审计
          </Button>
        </div>
      </header>

      {bootstrapWarning ? (
        <div className="methodology-bootstrap-warning" role="status">
          <AlertTriangle size={15} />
          <span>
            内置 seed 加载失败，已启用 fallback。请检查 {bootstrapWarning.seedFilePath || "seed 文件"} 或在本屏编辑修复。
          </span>
          <Button kind="ghost" onClick={dismissBootstrapWarning}>知道了</Button>
        </div>
      ) : null}

      {view === "store" ? (
        <main className="methodology-store-pane me-scroll" aria-label="技能商店">
          <SkillStoreTab />
        </main>
      ) : (
        <div className="methodology-workspace" data-collapsed={listCollapsed}>
          <SkillActiveList
            collapsed={listCollapsed}
            filterKey={filterKey}
            items={items}
            onFilter={setFilterKey}
            onOpen={(skillId) => {
              void selectSkill(skillId);
            }}
            onSort={setSortKey}
            onToggleCollapsed={() => setListCollapsed((v) => !v)}
            selectedSkillId={selectedSkillId}
            sortKey={sortKey}
          />

          <main className="methodology-detail-pane">
            {loading ? <div className="brain-empty">正在加载方法论列表</div> : null}
            {view === "active" ? (
              loadingDetail ? (
                <div className="brain-empty">正在加载方法论详情</div>
              ) : (
                <SkillEditor
                  detail={selectedDetail}
                  draft={editDraft}
                  loadingSkillPool={loadingSkillPool}
                  onDraftField={setDraftField}
                  onSave={() => {
                    void saveDraft();
                  }}
                  onSoftDelete={() => {
                    void softDeleteSelected();
                  }}
                  saving={saving}
                  skillPool={skillPool}
                />
              )
            ) : (
              <SkillAuditView audit={equipmentAudit} history={history} />
            )}
          </main>
        </div>
      )}

      {view !== "store" && items.length === 0 && !loading ? (
        <div className="methodology-empty-state">
          <BookOpenCheck size={18} />
          <span>暂无 active 方法论。让 Assistant 将完成过的流程做成方法论后会出现在这里。</span>
        </div>
      ) : null}
      {skillConfirmation ? (
        <SkillDangerConfirm
          affectedNames={skillConfirmation.actionType === "skill.soft_delete" ? affectedNames : []}
          message={skillConfirmation.sanitizedSummary}
          onCancel={() => {
            void decideConfirmation(skillConfirmation.requestId, "deny");
          }}
          onConfirm={() => {
            void decideConfirmation(skillConfirmation.requestId, "approve");
          }}
          title={confirmationTitle}
        />
      ) : null}
    </section>
  );
}

export default SkillMethodologyScreen;
