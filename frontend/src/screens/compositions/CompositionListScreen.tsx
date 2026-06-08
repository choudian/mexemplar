import { useEffect, useState } from "react";
import { ArrowRight, ChevronLeft, Edit3, Plus, Play, Shuffle, Workflow } from "lucide-react";

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

function statusToneFor(status: keyof typeof statusLabels) {
  if (status === "needs_review") return "warn";
  if (status === "published") return "ok";
  return "neutral";
}

function modeLabelFor(mode: CompositionSummary["mode"]) {
  return mode === "ordered" ? "顺序型 · 严格管线" : "范围型 · AI 自主调度";
}

function modeIconFor(mode: CompositionSummary["mode"]) {
  return mode === "ordered" ? Workflow : Shuffle;
}

export function CompositionListScreen(): JSX.Element {
  const [view, setView] = useState<"list" | "create">("list");
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
  const canPublish = Boolean(selectedId && draft.applicability.trim() && draft.members.length >= 2);
  const openCreate = () => {
    select(null);
    setView("create");
  };
  const openEditor = (compositionId: string) => {
    select(compositionId);
    setView("create");
  };

  return (
    <section className="compositions-screen" aria-label="工具组合">
      <header className="compositions-page-header">
        <div>
          <h2>工具组合</h2>
          <p>把多个已掌握的工具编排成一个组合，AI 可一次调度协作完成复杂任务</p>
        </div>
        <div className="composition-header-actions">
          {view === "create" ? (
            <Button kind="ghost" onClick={() => setView("list")}>
              <ChevronLeft size={14} />
              返回列表
            </Button>
          ) : null}
          <Button kind="primary" onClick={openCreate}>
            <Plus size={14} />
            新建组合
          </Button>
        </div>
      </header>

      <div className="compositions-workspace">
        {view === "list" ? (
          <CompositionCardGrid
            items={items}
            selectedId={selectedId}
            onCreate={openCreate}
            onEdit={openEditor}
            onTrial={(compositionId) => {
              void startTrial(compositionId);
            }}
          />
        ) : (
          <>
            {items.length === 0 ? (
              <div className="composition-empty-inline">暂无组合</div>
            ) : (
              <CompositionSummaryStrip items={items} selectedId={selectedId} onEdit={openEditor} />
            )}
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
          </>
        )}
      </div>
      <div className="composition-status">
        {selected ? <span>当前：{selected.name}</span> : <span>新建草稿</span>}
        {lastError ? <strong>{lastError}</strong> : null}
      </div>
    </section>
  );
}

function CompositionSummaryStrip({
  items,
  selectedId,
  onEdit,
}: {
  items: CompositionSummary[];
  selectedId: string | null;
  onEdit: (compositionId: string) => void;
}) {
  return (
    <div className="composition-summary-strip" aria-label="已有组合">
      {items.map((item) => {
        const displayStatus = displayStatusFor(item);
        return (
          <button
            className="composition-summary-pill"
            data-active={item.compositionId === selectedId}
            key={item.compositionId}
            onClick={() => onEdit(item.compositionId)}
            type="button"
          >
            <span>{item.name}</span>
            <Badge tone={statusToneFor(displayStatus)}>{statusLabels[displayStatus]}</Badge>
          </button>
        );
      })}
    </div>
  );
}

function CompositionCardGrid({
  items,
  selectedId,
  onCreate,
  onEdit,
  onTrial,
}: {
  items: CompositionSummary[];
  selectedId: string | null;
  onCreate: () => void;
  onEdit: (compositionId: string) => void;
  onTrial: (compositionId: string) => void;
}) {
  return (
    <div className="composition-card-grid">
      {items.length === 0 ? (
        <div className="composition-list-empty">
          <strong>暂无组合</strong>
          <span>从已发布的工具中编排一个新的组合。</span>
        </div>
      ) : null}
      {items.map((item) => (
        <CompositionCard
          item={item}
          key={item.compositionId}
          selected={item.compositionId === selectedId}
          onEdit={() => onEdit(item.compositionId)}
          onTrial={() => onTrial(item.compositionId)}
        />
      ))}
      <button className="composition-new-card" type="button" onClick={onCreate}>
        <span className="composition-new-card-icon">
          <Plus size={18} />
        </span>
        <strong>新建组合</strong>
        <span>从已发布的工具中编排</span>
      </button>
    </div>
  );
}

function CompositionCard({
  item,
  selected,
  onEdit,
  onTrial,
}: {
  item: CompositionSummary;
  selected: boolean;
  onEdit: () => void;
  onTrial: () => void;
}) {
  const displayStatus = displayStatusFor(item);
  const ModeIcon = modeIconFor(item.mode);
  const canTrial = Boolean(item.applicability.trim() && item.members.length > 0);

  return (
    <article className="composition-card" data-active={selected}>
      <div className="composition-card-heading">
        <span className="composition-card-icon">
          <ModeIcon size={18} />
        </span>
        <div>
          <div className="composition-card-title">
            <h3>{item.name}</h3>
            <Badge tone={statusToneFor(displayStatus)}>{statusLabels[displayStatus]}</Badge>
          </div>
          <p>{item.description || "未填写描述"}</p>
        </div>
      </div>

      <div className="composition-card-members">
        <div>
          <span>{modeLabelFor(item.mode)}</span>
          <span>{item.members.length} 个成员</span>
        </div>
        {item.members.length === 0 ? (
          <p className="composition-muted">暂无成员工具</p>
        ) : item.mode === "ordered" ? (
          <div className="composition-member-flow">
            {item.members.map((member, index) => (
              <span className="composition-member-chip" key={member.memberId ?? member.toolId}>
                {member.name ?? member.toolId}
                {index < item.members.length - 1 ? <ArrowRight size={12} /> : null}
              </span>
            ))}
          </div>
        ) : (
          <div className="composition-member-scope">
            {item.members.map((member) => (
              <span className="composition-member-chip" key={member.memberId ?? member.toolId}>
                {member.name ?? member.toolId}
              </span>
            ))}
          </div>
        )}
      </div>

      <div className="composition-card-footer">
        <span>{item.applicability ? "已配置适用场景" : "未配置适用场景"}</span>
        <div>
          <Button kind="ghost" disabled={!canTrial} onClick={onTrial}>
            <Play size={14} />
            试用
          </Button>
          <Button kind="ghost" onClick={onEdit}>
            <Edit3 size={14} />
            编辑
          </Button>
        </div>
      </div>
    </article>
  );
}

export default CompositionListScreen;
