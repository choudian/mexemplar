import { useEffect } from "react";

import type { CompositionSummary } from "../../api/compositions";
import { Badge, Button } from "../../components/primitives";
import { useCompositionsStore } from "../../state/compositionsStore";
import { useSkillsStore } from "../../state/skillsStore";
import CompositionEditor from "./CompositionEditor";

const statusLabels = {
  draft: "草稿",
  published: "已发布",
  offline: "已下线",
  needs_review: "待复核",
} as const;

function displayStatusFor(item: CompositionSummary): keyof typeof statusLabels {
  if (item.displayStatus) return item.displayStatus;
  return item.needsReview ? "needs_review" : item.status;
}

export function CompositionListScreen(): JSX.Element {
  const items = useCompositionsStore((state) => state.items);
  const selectedId = useCompositionsStore((state) => state.selectedId);
  const draft = useCompositionsStore((state) => state.draft);
  const busy = useCompositionsStore((state) => state.busy);
  const lastError = useCompositionsStore((state) => state.lastError);
  const load = useCompositionsStore((state) => state.load);
  const select = useCompositionsStore((state) => state.select);
  const setDraftField = useCompositionsStore((state) => state.setDraftField);
  const setMode = useCompositionsStore((state) => state.setMode);
  const addMember = useCompositionsStore((state) => state.addMember);
  const moveMember = useCompositionsStore((state) => state.moveMember);
  const removeMember = useCompositionsStore((state) => state.removeMember);
  const generateApplicability = useCompositionsStore((state) => state.generateApplicability);
  const recommendOrder = useCompositionsStore((state) => state.recommendOrder);
  const save = useCompositionsStore((state) => state.save);
  const publish = useCompositionsStore((state) => state.publish);
  const startTrial = useCompositionsStore((state) => state.startTrial);
  const publishedSkills = useSkillsStore((state) => state.categories.published);
  const loadSkills = useSkillsStore((state) => state.loadCategory);

  useEffect(() => {
    void load();
    void loadSkills("published");
  }, [load, loadSkills]);

  const selected = items.find((item) => item.compositionId === selectedId);
  const canPublish = Boolean(selectedId && draft.applicability.trim() && draft.members.length > 0);

  return (
    <section className="compositions-screen" aria-label="技能组合">
      <div className="compositions-list">
        <div className="compositions-header">
          <h2>技能组合</h2>
          <Button kind="primary" onClick={() => select(null)}>
            新建
          </Button>
        </div>
        {items.length === 0 ? <div className="composition-muted">暂无组合</div> : null}
        {items.map((item) => {
          const displayStatus = displayStatusFor(item);
          return (
            <button
              className="composition-row"
              data-active={item.compositionId === selectedId}
              key={item.compositionId}
              onClick={() => select(item.compositionId)}
              type="button"
            >
              <span>{item.name}</span>
              <Badge tone={displayStatus === "needs_review" ? "warn" : displayStatus === "published" ? "ok" : "neutral"}>
                {statusLabels[displayStatus]}
              </Badge>
            </button>
          );
        })}
      </div>
      <CompositionEditor
        draft={draft}
        skills={publishedSkills}
        busy={busy}
        canPublish={canPublish}
        onField={setDraftField}
        onMode={setMode}
        onAddMember={addMember}
        onMoveMember={moveMember}
        onRemoveMember={removeMember}
        onGenerateApplicability={() => {
          void generateApplicability();
        }}
        onRecommendOrder={() => {
          void recommendOrder();
        }}
        onSave={() => {
          void save();
        }}
        onPublish={() => {
          void publish();
        }}
        onTrial={() => {
          void startTrial();
        }}
      />
      <div className="composition-status">
        {selected ? <span>当前：{selected.name}</span> : <span>新建草稿</span>}
        {lastError ? <strong>{lastError}</strong> : null}
      </div>
    </section>
  );
}

export default CompositionListScreen;
