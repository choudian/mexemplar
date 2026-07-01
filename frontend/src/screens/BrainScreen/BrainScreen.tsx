import { RefreshCcw, RotateCcw, Save, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import type { BrainEntryStatus, BrainMemoryEntry, BrainZone } from "../../api/brain";
import type { ImprovementProposalDto } from "../../api/improvementProposal";
import SearchInput from "../../components/SearchInput";
import { Badge, Button, IconButton } from "../../components/primitives";
import { statusToTone } from "../../components/statusTone";
import { useFiltered } from "../../hooks/useFiltered";
import { useBrainStore } from "../../state/brainStore";
import { useSettingsStore } from "../../state/settingsStore";
import EntryEvolution from "./EntryEvolution";

const ZONES = [
  { id: "hot", label: "热区", hint: "近期工作记忆" },
  { id: "persistent", label: "持久区", hint: "稳定身份和偏好" },
  { id: "archive", label: "归档区", hint: "历史事件检索" },
  { id: "subconscious", label: "潜意识区", hint: "风格和价值倾向" },
  { id: "failure", label: "失败区", hint: "避坑经验" },
  { id: "prediction", label: "猜测区", hint: "待校准预测" },
] as const;

const STATUS_OPTIONS = [
  { value: "", label: "全部" },
  { value: "active", label: "活跃" },
  { value: "fading", label: "衰减中" },
  { value: "invalidated", label: "已失效" },
] as const;

function entryCountFor(zone: BrainZone, summaries: ReturnType<typeof useBrainStore.getState>["zones"]): number {
  const summary = summaries.find((item) => item.zone === zone);
  return summary?.entry_count ?? 0;
}

const BRAIN_ENTRY_STATUS_TONES = {
  active: "ok",
  fading: "warn",
  invalidated: "warn",
  "soft-deleted": "danger",
} as const;

export function BrainScreen(): JSX.Element {
  const zones = useBrainStore((state) => state.zones);
  const entries = useBrainStore((state) => state.entries);
  const activeZone = useBrainStore((state) => state.activeZone) ?? "hot";
  const segments = useBrainStore((state) => state.segments);
  const executionReviews = useBrainStore((state) => state.executionReviews);
  const evolutionChain = useBrainStore((state) => state.evolutionChain);
  const loadingZones = useBrainStore((state) => state.loadingZones);
  const loadingEntries = useBrainStore((state) => state.loadingEntries);
  const loadingSegments = useBrainStore((state) => state.loadingSegments);
  const loadingExecutionReviews = useBrainStore((state) => state.loadingExecutionReviews);
  const loadingEvolution = useBrainStore((state) => state.loadingEvolution);
  const loadZones = useBrainStore((state) => state.loadZones);
  const loadEntries = useBrainStore((state) => state.loadEntries);
  const loadSegments = useBrainStore((state) => state.loadSegments);
  const loadExecutionReviews = useBrainStore((state) => state.loadExecutionReviews);
  const deleteEntry = useBrainStore((state) => state.deleteEntry);
  const editEntry = useBrainStore((state) => state.editEntry);
  const retrySegment = useBrainStore((state) => state.retrySegment);
  const loadEvolution = useBrainStore((state) => state.loadEvolution);
  const executionReviewEnabled =
    useSettingsStore((state) => state.values["self_improvement.execution_review.enabled"]) !== false;
  const improvementProposals = useBrainStore((state) => state.improvementProposals);
  const loadingImprovementProposals = useBrainStore((state) => state.loadingImprovementProposals);
  const loadImprovementProposals = useBrainStore((state) => state.loadImprovementProposals);
  const approveImprovementProposal = useBrainStore((state) => state.approveImprovementProposal);
  const rejectImprovementProposal = useBrainStore((state) => state.rejectImprovementProposal);
  const proposalsEnabled =
    useSettingsStore((state) => state.values["self_improvement.proposals.enabled"]) !== false;

  const [activeView, setActiveView] = useState<BrainZone | "execution_review" | "improvement_proposals">("hot");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedReviewId, setSelectedReviewId] = useState<string | null>(null);
  const [selectedProposalId, setSelectedProposalId] = useState<string | null>(null);
  const [proposalSupplement, setProposalSupplement] = useState("");
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<BrainEntryStatus | "">("");
  const [contentDraft, setContentDraft] = useState("");
  const [scopeDraft, setScopeDraft] = useState("");

  useEffect(() => {
    void loadZones();
    void loadSegments();
    void loadEntries("hot");
    if (executionReviewEnabled) {
      void loadExecutionReviews();
    }
    if (proposalsEnabled) {
      void loadImprovementProposals();
    }
  }, [executionReviewEnabled, proposalsEnabled, loadEntries, loadExecutionReviews, loadImprovementProposals, loadSegments, loadZones]);

  useEffect(() => {
    if (!executionReviewEnabled && activeView === "execution_review") {
      setActiveView(activeZone);
    }
    if (!proposalsEnabled && activeView === "improvement_proposals") {
      setActiveView(activeZone);
    }
  }, [activeView, activeZone, executionReviewEnabled, proposalsEnabled]);

  const lastEvolutionIdRef = useRef<string | null>(null);

  useEffect(() => {
    if (selectedId) {
      const stillExists = entries.some((entry) => entry.entry_id === selectedId);
      if (stillExists) return;
    }
    if (!selectedId) {
      const auto = entries[0] ?? null;
      if (!auto) {
        setContentDraft("");
        setScopeDraft("");
        lastEvolutionIdRef.current = null;
        return;
      }
      setSelectedId(auto.entry_id);
      setContentDraft(auto.content);
      setScopeDraft(auto.scope ?? "");
      if (lastEvolutionIdRef.current !== auto.entry_id) {
        lastEvolutionIdRef.current = auto.entry_id;
        void loadEvolution(auto.entry_id);
      }
      return;
    }
    setSelectedId(null);
    setContentDraft("");
    setScopeDraft("");
    lastEvolutionIdRef.current = null;
  }, [entries, loadEvolution, selectedId]);

  const reviewingExecutions = activeView === "execution_review";
  const viewingProposals = activeView === "improvement_proposals";
  const selectedEntry = (reviewingExecutions || viewingProposals) ? null : entries.find((entry) => entry.entry_id === selectedId) ?? null;
  const selectedReview =
    executionReviews.find((review) => review.id === selectedReviewId) ?? executionReviews[0] ?? null;
  const filteredEntries = useFiltered(entries, query, (entry) => [
    entry.content,
    entry.reason,
    entry.scope,
    entry.entry_type,
  ]);

  const chooseZone = (zone: BrainZone) => {
    setActiveView(zone);
    setSelectedId(null);
    setSelectedReviewId(null);
    void loadEntries(zone, { status: status || undefined });
  };

  const chooseExecutionReviews = () => {
    setActiveView("execution_review");
    setSelectedId(null);
    void loadExecutionReviews();
  };

  const chooseStatus = (nextStatus: BrainEntryStatus | "") => {
    setStatus(nextStatus);
    void loadEntries(activeZone, { status: nextStatus || undefined });
  };

  const saveSelected = () => {
    if (!selectedEntry) return;
    void editEntry(selectedEntry.entry_id, contentDraft, scopeDraft || undefined);
  };

  return (
    <section className="brain-screen" aria-label="大脑管理">
      <header className="brain-header">
        <div>
          <h2>大脑管理</h2>
          <p>查看、修正和追溯助理的六个认知分区</p>
        </div>
        <Button kind="secondary" onClick={() => {
          void loadZones();
          if (reviewingExecutions) {
            void loadExecutionReviews();
          } else if (viewingProposals) {
            void loadImprovementProposals();
          } else {
            void loadEntries(activeZone, { status: status || undefined });
          }
          void loadSegments();
        }}>
          <RefreshCcw size={14} />
          刷新
        </Button>
      </header>

      <div className="brain-workspace">
        <aside className="brain-zone-rail" aria-label="大脑分区">
          {ZONES.map((zone) => {
            const active = zone.id === activeView;
            return (
              <button
                aria-pressed={active}
                className="brain-zone-button"
                data-active={active}
                key={zone.id}
                onClick={() => chooseZone(zone.id)}
                type="button"
              >
                <span>
                  <strong>{zone.label}</strong>
                  <small>{zone.hint}</small>
                </span>
                <span className="me-badge">{entryCountFor(zone.id, zones)}</span>
              </button>
            );
          })}
          {executionReviewEnabled ? (
            <button
              aria-pressed={reviewingExecutions}
              className="brain-zone-button"
              data-active={reviewingExecutions}
              onClick={chooseExecutionReviews}
              type="button"
            >
              <span>
                <strong>执行复盘</strong>
                <small>效率和健壮性报告</small>
              </span>
              <span className="me-badge">{executionReviews.length}</span>
            </button>
          ) : null}
          {proposalsEnabled ? (
            <button
              aria-pressed={viewingProposals}
              className="brain-zone-button"
              data-active={viewingProposals}
              onClick={() => setActiveView("improvement_proposals")}
              type="button"
            >
              <span>
                <strong>改进提案</strong>
                <small>可执行的改进项</small>
              </span>
              <span className="me-badge">{improvementProposals.filter((p) => p.status === "pending_review").length || improvementProposals.length}</span>
            </button>
          ) : null}
          {loadingZones ? <div className="brain-empty">正在刷新分区</div> : null}
        </aside>

        <main className="brain-entry-pane">
          {viewingProposals ? (
            <ImprovementProposalList
              loading={loadingImprovementProposals}
              onSelect={(id) => {
                setSelectedProposalId(id);
                // 切换选中提案时清空补料草稿，避免上一条的文本串改到新选中的提案。
                setProposalSupplement("");
              }}
              proposals={improvementProposals}
              selectedId={selectedProposalId}
            />
          ) : reviewingExecutions ? (
            <ExecutionReviewList
              loading={loadingExecutionReviews}
              onSelect={setSelectedReviewId}
              reviews={executionReviews}
              selectedId={selectedReview?.id ?? null}
            />
          ) : (
            <>
              <div className="brain-toolbar">
                <label className="brain-search">
                  <SearchInput
                    ariaLabel="搜索大脑条目"
                    onChange={setQuery}
                    placeholder="搜索内容、理由或范围"
                    value={query}
                  />
                </label>
                <select
                  aria-label="筛选条目状态"
                  onChange={(event) => chooseStatus(event.currentTarget.value as BrainEntryStatus | "")}
                  value={status}
                >
                  {STATUS_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </select>
              </div>

              <div className="brain-entry-list me-scroll" aria-label="分区条目">
                {loadingEntries ? <div className="brain-empty">正在加载条目</div> : null}
                {filteredEntries.map((entry) => (
                  <EntryRow
                    entry={entry}
                    key={entry.entry_id}
                    onDelete={() => {
                      void deleteEntry(entry.entry_id);
                    }}
                    onSelect={() => {
                      setSelectedId(entry.entry_id);
                      setContentDraft(entry.content);
                      setScopeDraft(entry.scope ?? "");
                      lastEvolutionIdRef.current = entry.entry_id;
                      void loadEvolution(entry.entry_id);
                    }}
                    selected={entry.entry_id === selectedId}
                  />
                ))}
                {!loadingEntries && filteredEntries.length === 0 ? <div className="brain-empty">暂无条目</div> : null}
              </div>
            </>
          )}
        </main>

        <aside className="brain-detail-pane me-scroll" aria-label="条目详情">
          {viewingProposals ? (
            <ImprovementProposalDetail
              proposal={improvementProposals.find((p) => p.id === selectedProposalId) ?? null}
              supplement={proposalSupplement}
              onSupplementChange={setProposalSupplement}
              onApprove={(id) => {
                void (async () => {
                  const accepted = await approveImprovementProposal(id, proposalSupplement);
                  if (accepted) {
                    setProposalSupplement("");
                  }
                })();
              }}
              onReject={(id) => {
                void rejectImprovementProposal(id);
              }}
            />
          ) : reviewingExecutions ? (
            <ExecutionReviewDetail review={selectedReview} />
          ) : selectedEntry ? (
            <section className="brain-editor">
              <div className="brain-section-title">
                <span>条目详情</span>
                <Badge tone={statusToTone(selectedEntry.status, BRAIN_ENTRY_STATUS_TONES)}>{selectedEntry.status}</Badge>
              </div>
              <label>
                <span>内容</span>
                <textarea
                  aria-label="编辑条目内容"
                  onChange={(event) => setContentDraft(event.currentTarget.value)}
                  value={contentDraft}
                />
              </label>
              <label>
                <span>适用范围</span>
                <input
                  aria-label="编辑适用范围"
                  onChange={(event) => setScopeDraft(event.currentTarget.value)}
                  value={scopeDraft}
                />
              </label>
              <div className="brain-reason">
                <strong>形成原因</strong>
                <p>{selectedEntry.reason || "无记录"}</p>
              </div>
              {selectedEntry.verification_status ? (
                <div className="brain-reason">
                  <strong>校准状态</strong>
                  <p>{selectedEntry.verification_status} · {selectedEntry.verification_rationale || "无说明"}</p>
                </div>
              ) : null}
              <div className="brain-editor-actions">
                <Button kind="primary" onClick={saveSelected}>
                  <Save size={14} />
                  保存
                </Button>
                <Button kind="danger" onClick={() => {
                  void deleteEntry(selectedEntry.entry_id);
                }}>
                  <Trash2 size={14} />
                  删除
                </Button>
              </div>
            </section>
          ) : (
            <div className="brain-empty">选择一个条目查看详情</div>
          )}
          {reviewingExecutions ? null : (
            <>
              <EntryEvolution chain={evolutionChain} loading={loadingEvolution} />
              <SegmentPanel loading={loadingSegments} segments={segments} onRetry={(segmentId) => {
                void retrySegment(segmentId);
              }} />
            </>
          )}
        </aside>
      </div>
    </section>
  );
}

function severityTone(severity: string): "neutral" | "ok" | "warn" | "danger" {
  if (severity === "high") return "danger";
  if (severity === "med") return "warn";
  if (severity === "low") return "ok";
  return "neutral";
}

function ExecutionReviewList({
  reviews,
  selectedId,
  loading,
  onSelect,
}: {
  reviews: ReturnType<typeof useBrainStore.getState>["executionReviews"];
  selectedId: string | null;
  loading: boolean;
  onSelect: (reviewId: string) => void;
}) {
  return (
    <div className="brain-entry-list me-scroll" aria-label="执行复盘列表">
      {loading ? <div className="brain-empty">正在加载执行复盘</div> : null}
      {reviews.map((review) => {
        const firstFinding = review.findings[0];
        return (
          <article className="brain-entry-row" data-selected={review.id === selectedId} key={review.id}>
            <button onClick={() => onSelect(review.id)} type="button">
              <span className="brain-entry-title">{review.verdict || "未发现明显问题"}</span>
              <span className="brain-entry-meta">
                <Badge tone={review.advisory ? "neutral" : "warn"}>只读建议</Badge>
                {firstFinding ? (
                  <Badge tone={severityTone(firstFinding.severity)}>{firstFinding.severity}</Badge>
                ) : null}
                <small>{review.reviewedAt || review.createdAt}</small>
              </span>
              <small>{firstFinding?.what || "没有可操作发现"}</small>
            </button>
          </article>
        );
      })}
      {!loading && reviews.length === 0 ? <div className="brain-empty">暂无执行复盘</div> : null}
    </div>
  );
}

function ExecutionReviewDetail({
  review,
}: {
  review: ReturnType<typeof useBrainStore.getState>["executionReviews"][number] | null;
}) {
  if (!review) {
    return <div className="brain-empty">选择一条复盘查看详情</div>;
  }
  return (
    <section className="brain-execution-review">
      <div className="brain-section-title">
        <span>执行复盘</span>
        <Badge tone="neutral">只读建议</Badge>
      </div>
      <div className="brain-reason">
        <strong>结论</strong>
        <p>{review.verdict || "未发现明显问题"}</p>
      </div>
      <div className="brain-review-findings">
        {review.findings.map((finding, index) => (
          <article className="brain-review-finding" key={`${review.id}-${index}`}>
            <div className="brain-entry-meta">
              <Badge tone={severityTone(finding.severity)}>{finding.severity}</Badge>
              <small>{finding.type}</small>
            </div>
            <strong>{finding.what}</strong>
            <p>{finding.suggestion}</p>
            {finding.evidence ? <small>{finding.evidence}</small> : null}
          </article>
        ))}
        {review.findings.length === 0 ? <div className="brain-empty">没有可操作发现</div> : null}
      </div>
    </section>
  );
}

const PROPOSAL_STATUS_TONES: Record<string, "ok" | "warn" | "danger" | "neutral"> = {
  pending_review: "warn",
  approved: "ok",
  in_progress: "ok",
  done: "ok",
  failed: "danger",
  rejected: "neutral",
};

const PROPOSAL_STATUS_LABELS: Record<string, string> = {
  pending_review: "待审批",
  approved: "已批准",
  in_progress: "正在实施",
  done: "已完成",
  failed: "失败",
  rejected: "已拒绝",
};

function ImprovementProposalList({
  proposals,
  selectedId,
  loading,
  onSelect,
}: {
  proposals: ImprovementProposalDto[];
  selectedId: string | null;
  loading: boolean;
  onSelect: (proposalId: string) => void;
}) {
  return (
    <div className="brain-entry-list me-scroll" aria-label="改进提案列表">
      {loading ? <div className="brain-empty">正在加载改进提案</div> : null}
      {proposals.map((proposal) => (
        <article className="brain-entry-row" data-selected={proposal.id === selectedId} key={proposal.id}>
          <button onClick={() => onSelect(proposal.id)} type="button">
            <span className="brain-entry-title">{proposal.what || "改进提案"}</span>
            <span className="brain-entry-meta">
              <Badge tone={statusToTone(proposal.status, PROPOSAL_STATUS_TONES)}>
                {PROPOSAL_STATUS_LABELS[proposal.status] ?? proposal.status}
              </Badge>
              {proposal.severity ? <Badge tone={severityTone(proposal.severity)}>{proposal.severity}</Badge> : null}
              {proposal.findingType ? <small>{proposal.findingType}</small> : null}
              <small>{proposal.createdAt}</small>
            </span>
            <small>{proposal.suggestion || proposal.evidence}</small>
          </button>
        </article>
      ))}
      {!loading && proposals.length === 0 ? <div className="brain-empty">暂无改进提案</div> : null}
    </div>
  );
}

function ImprovementProposalDetail({
  proposal,
  supplement,
  onSupplementChange,
  onApprove,
  onReject,
}: {
  proposal: ImprovementProposalDto | null;
  supplement: string;
  onSupplementChange: (value: string) => void;
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
}) {
  if (!proposal) {
    return <div className="brain-empty">选择一条提案查看详情</div>;
  }
  const isPending = proposal.status === "pending_review";
  return (
    <section className="brain-execution-review">
      <div className="brain-section-title">
        <span>改进提案</span>
        <Badge tone={statusToTone(proposal.status, PROPOSAL_STATUS_TONES)}>
          {PROPOSAL_STATUS_LABELS[proposal.status] ?? proposal.status}
        </Badge>
      </div>
      {proposal.severity ? (
        <div className="brain-reason">
          <strong>严重程度</strong>
          <Badge tone={severityTone(proposal.severity)}>{proposal.severity}</Badge>
          {proposal.findingType ? <small>{proposal.findingType}</small> : null}
        </div>
      ) : null}
      <div className="brain-reason">
        <strong>问题描述</strong>
        <p>{proposal.what}</p>
      </div>
      {proposal.evidence ? (
        <div className="brain-reason">
          <strong>证据</strong>
          <p>{proposal.evidence}</p>
        </div>
      ) : null}
      {proposal.suggestion ? (
        <div className="brain-reason">
          <strong>建议</strong>
          <p>{proposal.suggestion}</p>
        </div>
      ) : null}
      {proposal.userSupplement ? (
        <div className="brain-reason">
          <strong>补充说明</strong>
          <p>{proposal.userSupplement}</p>
        </div>
      ) : null}
      {proposal.branchName ? (
        <div className="brain-reason">
          <strong>实施分支</strong>
          <p>{proposal.branchName}</p>
        </div>
      ) : null}
      {proposal.resultSummary ? (
        <div className="brain-reason">
          <strong>实施结果</strong>
          <p>{proposal.resultSummary}</p>
          {proposal.resultTestsPassed != null ? (
            <Badge tone={proposal.resultTestsPassed ? "ok" : "danger"}>
              {proposal.resultTestsPassed ? "测试通过" : "测试失败"}
            </Badge>
          ) : null}
        </div>
      ) : null}
      {proposal.error ? (
        <div className="brain-reason">
          <strong>失败原因</strong>
          <p>{proposal.error}</p>
        </div>
      ) : null}
      {isPending ? (
        <div className="brain-proposal-actions">
          <label>
            <strong>补充说明（可选）</strong>
            <textarea
              aria-label="补充说明"
              onChange={(e) => onSupplementChange(e.target.value)}
              placeholder="给实施补充说明或优先方向"
              rows={3}
              value={supplement}
            />
          </label>
          <div className="brain-action-buttons">
            <Button kind="primary" onClick={() => onApprove(proposal.id)}>批准</Button>
            <Button kind="danger" onClick={() => onReject(proposal.id)}>拒绝</Button>
          </div>
        </div>
      ) : null}
      {proposal.status === "failed" ? (
        <div className="brain-proposal-actions">
          <Button kind="ghost" onClick={() => onReject(proposal.id)}>
            {proposal.worktreeAvailable ? "弃用并清理 worktree" : "弃用"}
          </Button>
        </div>
      ) : null}
    </section>
  );
}

function EntryRow({
  entry,
  selected,
  onSelect,
  onDelete,
}: {
  entry: BrainMemoryEntry;
  selected: boolean;
  onSelect: () => void;
  onDelete: () => void;
}) {
  return (
    <article className="brain-entry-row" data-selected={selected}>
      <button onClick={onSelect} type="button">
        <span className="brain-entry-title">{entry.content}</span>
        <span className="brain-entry-meta">
          <Badge tone={statusToTone(entry.status, BRAIN_ENTRY_STATUS_TONES)}>{entry.status}</Badge>
          {entry.entry_type ? <small>{entry.entry_type}</small> : null}
          {entry.scope ? <small>{entry.scope}</small> : null}
        </span>
        <small>{entry.reason || "无形成原因"}</small>
      </button>
      <IconButton label="删除条目" onClick={onDelete}>
        <Trash2 size={14} />
      </IconButton>
    </article>
  );
}

function SegmentPanel({
  segments,
  loading,
  onRetry,
}: {
  segments: ReturnType<typeof useBrainStore.getState>["segments"];
  loading: boolean;
  onRetry: (segmentId: string) => void;
}) {
  return (
    <section className="brain-segments" aria-label="Segment 列表">
      <div className="brain-section-title">
        <span>Segment</span>
        <small>{segments.length} 条</small>
      </div>
      {loading ? <div className="brain-empty">正在加载 Segment</div> : null}
      {segments.slice(0, 6).map((segment) => (
        <div className="brain-segment-row" key={segment.segment_id}>
          <div>
            <strong>{segment.boundary_reason || "边界"}</strong>
            <small>{segment.status} · retry {segment.retry_count}</small>
          </div>
          {segment.status === "failed" ? (
            <IconButton label="重试 Segment" onClick={() => onRetry(segment.segment_id)}>
              <RotateCcw size={14} />
            </IconButton>
          ) : null}
        </div>
      ))}
      {!loading && segments.length === 0 ? <div className="brain-empty">暂无 Segment</div> : null}
    </section>
  );
}

export default BrainScreen;
