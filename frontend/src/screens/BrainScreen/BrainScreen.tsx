import {
  FileSearch,
  FileText,
  ListTree,
  MessageSquare,
  RefreshCcw,
  RotateCcw,
  ScrollText,
  Save,
  Trash2,
  Wrench,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { sendAssistantMessage } from "../../api/assistant";
import type { BrainEntryStatus, BrainMemoryEntry, BrainZone } from "../../api/brain";
import {
  fetchProposalSource,
  type ImprovementProposalDto,
  type ProposalSourceAnchor,
  type ProposalSourcePackage,
  type ProposalSourceTimelineItem,
  type ProposalSourceView,
} from "../../api/improvementProposal";
import SearchInput from "../../components/SearchInput";
import { Badge, Button, IconButton } from "../../components/primitives";
import { statusToTone } from "../../components/statusTone";
import { useFiltered } from "../../hooks/useFiltered";
import { useAssistantStore } from "../../state/assistantStore";
import { useBrainStore } from "../../state/brainStore";
import { useSettingsStore } from "../../state/settingsStore";
import { useShellStore } from "../../state/shellStore";
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

const PROPOSAL_AUTO_INVESTIGATION_PROMPT =
  "请先调查这条改进提案为什么会生成。请调用 inspect_proposal_source 读取 overview、prompt 和 timeline；必要时再读取 messages 或相关 tool_output。请重点回答：来源证据是否真的支持这条 finding、可能有哪些误判或证据缺口、复盘提示词应该如何收紧。不要批准、拒绝或实施这条提案。";

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
  const proposalSources = useBrainStore((state) => state.proposalSources);
  const loadingProposalSourceId = useBrainStore((state) => state.loadingProposalSourceId);
  const proposalSourceError = useBrainStore((state) => state.proposalSourceError);
  const loadProposalSource = useBrainStore((state) => state.loadProposalSource);
  const approveImprovementProposal = useBrainStore((state) => state.approveImprovementProposal);
  const rejectImprovementProposal = useBrainStore((state) => state.rejectImprovementProposal);
  const openProposalDiscussion = useBrainStore((state) => state.openProposalDiscussion);
  const openingDiscussionProposalId = useBrainStore((state) => state.openingDiscussionProposalId);
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
  const selectedProposal = improvementProposals.find((p) => p.id === selectedProposalId) ?? null;
  const selectedProposalSource = selectedProposalId ? proposalSources[selectedProposalId] ?? null : null;
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

  useEffect(() => {
    if (!viewingProposals || !selectedProposalId) return;
    void loadProposalSource(selectedProposalId);
  }, [loadProposalSource, selectedProposalId, viewingProposals]);

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
              proposal={selectedProposal}
              source={selectedProposalSource}
              sourceError={proposalSourceError}
              sourceLoading={loadingProposalSourceId === selectedProposalId}
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
              onDiscuss={(id) => {
                void (async () => {
                  const discussion = await openProposalDiscussion(id);
                  if (discussion) {
                    await useAssistantStore.getState().selectSession(discussion.sessionId);
                    useShellStore.getState().setRoute("assistant");
                    if (discussion.created) {
                      void sendAssistantMessage(
                        discussion.sessionId,
                        PROPOSAL_AUTO_INVESTIGATION_PROMPT,
                      ).catch(() => {
                        useAssistantStore
                          .getState()
                          .setError("讨论已打开，但自动调查请求发送失败。可以在会话里手动要求助理分析来源。");
                      });
                    }
                  }
                })();
              }}
              discussPending={openingDiscussionProposalId !== null}
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
  source,
  sourceLoading,
  sourceError,
  supplement,
  onSupplementChange,
  onApprove,
  onReject,
  onDiscuss,
  discussPending,
}: {
  proposal: ImprovementProposalDto | null;
  source: ProposalSourcePackage | null;
  sourceLoading: boolean;
  sourceError: string | null;
  supplement: string;
  onSupplementChange: (value: string) => void;
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
  onDiscuss: (id: string) => void;
  discussPending: boolean;
}) {
  if (!proposal) {
    return <div className="brain-empty">选择一条提案查看详情</div>;
  }
  const isPending = proposal.status === "pending_review";
  const hasOutcome = Boolean(proposal.branchName || proposal.resultSummary || proposal.error);
  const discussionButton = (
    <button
      className="brain-proposal-discuss-button"
      disabled={discussPending}
      onClick={() => onDiscuss(proposal.id)}
      type="button"
    >
      <MessageSquare size={15} />
      <span>{proposal.discussionSessionId ? "继续讨论" : "讨论"}</span>
    </button>
  );
  return (
    <section aria-label="改进提案详情" className="brain-execution-review brain-proposal-detail">
      <div className="brain-proposal-heading">
        <div className="brain-section-title">
          <span>改进提案</span>
          <Badge tone={statusToTone(proposal.status, PROPOSAL_STATUS_TONES)}>
            {PROPOSAL_STATUS_LABELS[proposal.status] ?? proposal.status}
          </Badge>
        </div>
      </div>
      {proposal.severity || proposal.findingType ? (
        <div className="brain-proposal-meta">
          {proposal.severity ? (
            <Badge tone={severityTone(proposal.severity)}>{proposal.severity}</Badge>
          ) : null}
          {proposal.findingType ? <small>{proposal.findingType}</small> : null}
        </div>
      ) : null}
      <div className="brain-proposal-chain">
        <div className="brain-proposal-node" data-kind="what">
          <span className="brain-proposal-node-label">问题</span>
          <p>{proposal.what}</p>
        </div>
        {proposal.evidence ? (
          <div className="brain-proposal-node" data-kind="evidence">
            <span className="brain-proposal-node-label">证据</span>
            <p>{proposal.evidence}</p>
          </div>
        ) : null}
        {proposal.suggestion ? (
          <div className="brain-proposal-node" data-kind="suggestion">
            <span className="brain-proposal-node-label">建议</span>
            <p>{proposal.suggestion}</p>
          </div>
        ) : null}
      </div>
      {proposal.userSupplement ? (
        <div className="brain-proposal-supplement">
          <strong>你的补充</strong>
          <p>{proposal.userSupplement}</p>
        </div>
      ) : null}
      <ProposalSourcePanel error={sourceError} loading={sourceLoading} source={source} />
      {!isPending ? <div className="brain-proposal-followup">{discussionButton}</div> : null}
      {hasOutcome ? (
        <div className="brain-proposal-outcome">
          <span className="brain-proposal-outcome-title">实施情况</span>
          {proposal.branchName ? (
            <code className="brain-proposal-branch" title="实施分支">
              {proposal.branchName}
            </code>
          ) : null}
          {proposal.resultSummary ? (
            <div
              className="brain-proposal-result"
              data-outcome={
                proposal.resultTestsPassed == null
                  ? "neutral"
                  : proposal.resultTestsPassed
                    ? "passed"
                    : "failed"
              }
            >
              <p>{proposal.resultSummary}</p>
              {proposal.resultTestsPassed != null ? (
                <Badge tone={proposal.resultTestsPassed ? "ok" : "danger"}>
                  {proposal.resultTestsPassed ? "测试通过" : "测试失败"}
                </Badge>
              ) : null}
            </div>
          ) : null}
          {proposal.error ? (
            <div className="brain-proposal-result" data-outcome="failed">
              <span className="brain-proposal-node-label">失败原因</span>
              <p>{proposal.error}</p>
            </div>
          ) : null}
        </div>
      ) : null}
      {isPending ? (
        <div className="brain-proposal-decision">
          <label className="brain-proposal-supplement-field">
            <span>
              <strong>补充说明</strong>
              <small>可选，写给实施任务</small>
            </span>
            <textarea
              aria-label="补充说明"
              onChange={(e) => onSupplementChange(e.target.value)}
              placeholder="给实施补充说明或优先方向"
              rows={4}
              value={supplement}
            />
          </label>
          <div className="brain-action-buttons">
            {discussionButton}
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

function anchorLabel(anchor: ProposalSourceAnchor): string {
  if (typeof anchor.sequence === "number") return `消息 #${anchor.sequence}`;
  if (typeof anchor.findingIndex === "number") return `Finding #${anchor.findingIndex + 1}`;
  if (typeof anchor.stepIndex === "number") return `步骤 #${anchor.stepIndex + 1}`;
  if (anchor.toolName) return anchor.toolName;
  if (anchor.sourceReviewId) return anchor.sourceReviewId;
  return "来源锚点";
}

const SOURCE_VIEW_OPTIONS: Array<{ view: ProposalSourceView; label: string }> = [
  { view: "overview", label: "概览" },
  { view: "messages", label: "原文" },
  { view: "prompt", label: "Prompt" },
  { view: "timeline", label: "工具线" },
  { view: "tool_output", label: "大输出" },
];

function sourceRoleLabel(role?: string | null): string {
  if (role === "user") return "用户";
  if (role === "assistant") return "助理";
  if (role === "tool") return "工具";
  return role || "消息";
}

function formatBytes(value?: number | null): string {
  if (!value || value <= 0) return "0 B";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}

function localErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof Error && error.message) return error.message;
  return fallback;
}

function mergeSourcePackage(
  previous: ProposalSourcePackage | undefined,
  next: ProposalSourcePackage,
  append: boolean,
): ProposalSourcePackage {
  if (!append || !previous || previous.view !== next.view) return next;
  if (next.view === "messages") {
    return {
      ...next,
      items: [...(previous.items ?? []), ...(next.items ?? [])],
    };
  }
  if (next.view === "tool_output") {
    return {
      ...next,
      content: `${previous.content ?? ""}${next.content ?? ""}`,
    };
  }
  return next;
}

function ProposalSourcePanel({
  source,
  loading,
  error,
}: {
  source: ProposalSourcePackage | null;
  loading: boolean;
  error: string | null;
}): JSX.Element {
  const [activeView, setActiveView] = useState<ProposalSourceView>("overview");
  const [viewPackages, setViewPackages] = useState<Partial<Record<ProposalSourceView, ProposalSourcePackage>>>({});
  const [loadingView, setLoadingView] = useState<ProposalSourceView | null>(null);
  const [viewError, setViewError] = useState<string | null>(null);
  const [activeReferenceId, setActiveReferenceId] = useState<string | null>(null);

  useEffect(() => {
    setActiveView("overview");
    setViewPackages(source ? { overview: source } : {});
    setViewError(null);
    setActiveReferenceId(null);
  }, [source?.proposalId]);

  useEffect(() => {
    if (!source) return;
    setViewPackages((previous) => ({ ...previous, overview: source }));
  }, [source]);

  const loadView = async (
    view: ProposalSourceView,
    options: {
      cursor?: string | null;
      append?: boolean;
      referenceId?: string | null;
      offset?: number | null;
    } = {},
  ) => {
    if (!source?.proposalId) return;
    if (view === "tool_output" && !options.referenceId && !activeReferenceId) {
      setViewError("先在工具时间线里选择一条大输出。");
      return;
    }
    setLoadingView(view);
    setViewError(null);
    try {
      const next = await fetchProposalSource(source.proposalId, {
        view,
        cursor: options.cursor,
        limit: view === "messages" ? 20 : 20,
        referenceId: options.referenceId ?? activeReferenceId,
        offset: options.offset,
        maxBytes: 32000,
      });
      setViewPackages((previous) => ({
        ...previous,
        [view]: mergeSourcePackage(previous[view], next, Boolean(options.append)),
      }));
    } catch (loadError) {
      setViewError(localErrorMessage(loadError, "来源视图暂时不可用。"));
    } finally {
      setLoadingView(null);
    }
  };

  const chooseView = (view: ProposalSourceView) => {
    setActiveView(view);
    if (view === "overview") return;
    if (view === "tool_output" && !activeReferenceId && !viewPackages.tool_output) {
      setViewError("先在工具时间线里选择一条大输出。");
      return;
    }
    if (!viewPackages[view]) {
      void loadView(view);
    }
  };

  const openToolOutput = (referenceId: string) => {
    setActiveReferenceId(referenceId);
    setActiveView("tool_output");
    void loadView("tool_output", { referenceId });
  };

  const evidence = source?.evidence ?? [];
  const activePackage = activeView === "overview" ? source : viewPackages[activeView] ?? null;
  const messages = activePackage?.items ?? [];
  const timeline = activePackage?.timeline ?? [];
  const prompt = activePackage?.prompt ?? null;
  const outputReference = activePackage?.reference ?? null;
  const outputError = activePackage?.error?.message;
  return (
    <section className="brain-proposal-source" aria-label="来源证据">
      <div className="brain-section-title">
        <span>
          <FileSearch size={14} />
          来源证据
        </span>
        {source?.source?.available === false ? <Badge tone="warn">来源缺失</Badge> : null}
      </div>
      {loading ? <div className="brain-empty">正在读取来源证据</div> : null}
      {!loading && error ? <div className="brain-error">{error}</div> : null}
      {!loading && !error && source ? (
        <>
          <div className="brain-proposal-source-meta">
            <span>复盘 {source.source.sourceReviewId ?? "未知"}</span>
            {source.source.turnSessionId ? <span>会话 {source.source.turnSessionId}</span> : null}
            {source.source.reviewedAt ? <span>{source.source.reviewedAt}</span> : null}
          </div>
          {source.scopeNote ? <p className="brain-proposal-source-note">{source.scopeNote}</p> : null}
          <div className="brain-proposal-source-tabs" role="tablist" aria-label="来源证据视图">
            {SOURCE_VIEW_OPTIONS.map((option) => {
              const disabled = option.view === "tool_output" && !activeReferenceId && !viewPackages.tool_output;
              return (
                <button
                  aria-selected={activeView === option.view}
                  disabled={disabled}
                  key={option.view}
                  onClick={() => chooseView(option.view)}
                  role="tab"
                  type="button"
                >
                  {option.view === "overview" ? <FileSearch size={13} /> : null}
                  {option.view === "messages" ? <ScrollText size={13} /> : null}
                  {option.view === "prompt" ? <FileText size={13} /> : null}
                  {option.view === "timeline" ? <ListTree size={13} /> : null}
                  {option.view === "tool_output" ? <Wrench size={13} /> : null}
                  <span>{option.label}</span>
                </button>
              );
            })}
          </div>

          {loadingView ? <div className="brain-empty">正在读取{SOURCE_VIEW_OPTIONS.find((item) => item.view === loadingView)?.label}</div> : null}
          {viewError ? <div className="brain-error">{viewError}</div> : null}

          {activeView === "overview" ? (
            <>
              <div className="brain-proposal-source-list">
                {evidence.map((item) => (
                  <article className="brain-proposal-source-item" key={item.id}>
                    <div>
                      <span className="brain-proposal-node-label">{item.label}</span>
                      <small>{anchorLabel(item.anchor)}</small>
                    </div>
                    <p>{item.excerpt}{item.truncated ? "\n...[已截断]" : ""}</p>
                    <small>{item.reason}</small>
                  </article>
                ))}
              </div>
              {evidence.length === 0 ? <div className="brain-empty">暂无可展示的来源片段</div> : null}
            </>
          ) : null}

          {activeView === "messages" ? (
            <div className="brain-proposal-source-list">
              {messages.map((item) => (
                <article className="brain-proposal-source-item" key={item.messageId}>
                  <div>
                    <span className="brain-proposal-node-label">{sourceRoleLabel(item.role)}</span>
                    <small>{anchorLabel(item.anchor)}</small>
                  </div>
                  <p>{item.excerpt}{item.truncated ? "\n...[已截断]" : ""}</p>
                  {item.toolName ? <small>{item.toolName}</small> : null}
                </article>
              ))}
              {messages.length === 0 && !loadingView ? <div className="brain-empty">暂无原始消息片段</div> : null}
              {activePackage?.page?.hasMore ? (
                <Button
                  kind="ghost"
                  onClick={() => {
                    void loadView("messages", {
                      cursor: activePackage.page?.nextCursor,
                      append: true,
                    });
                  }}
                >
                  加载更多
                </Button>
              ) : null}
            </div>
          ) : null}

          {activeView === "prompt" ? (
            <div className="brain-proposal-source-code">
              {activePackage?.scopeNote ? <p className="brain-proposal-source-note">{activePackage.scopeNote}</p> : null}
              <div>
                <span className="brain-proposal-node-label">复盘系统提示词</span>
                <pre>{prompt?.system || "暂无"}</pre>
              </div>
              <div>
                <span className="brain-proposal-node-label">Skeleton 输入</span>
                <pre>{prompt?.userPayload || "{}"}</pre>
              </div>
              {prompt?.tools?.length ? (
                <div className="brain-proposal-source-tools">
                  {prompt.tools.map((tool) => (
                    <span key={tool.name}>{tool.name}</span>
                  ))}
                </div>
              ) : null}
            </div>
          ) : null}

          {activeView === "timeline" ? (
            <div className="brain-proposal-source-list">
              {timeline.map((item: ProposalSourceTimelineItem) => (
                <article className="brain-proposal-source-item" key={item.id}>
                  <div>
                    <span className="brain-proposal-node-label">{item.label}</span>
                    <small>{item.sequence != null ? `消息 #${item.sequence}` : item.toolName}</small>
                  </div>
                  {item.argsPreview ? <pre className="brain-proposal-source-inline-code">{item.argsPreview}</pre> : null}
                  {item.excerpt ? <p>{item.excerpt}{item.truncated ? "\n...[已截断]" : ""}</p> : null}
                  <div className="brain-proposal-source-item-footer">
                    {item.resultSize != null ? <small>{formatBytes(item.resultSize)}</small> : null}
                    {item.outputRef ? (
                      <button onClick={() => openToolOutput(item.outputRef as string)} type="button">
                        查看大输出
                      </button>
                    ) : null}
                  </div>
                </article>
              ))}
              {timeline.length === 0 && !loadingView ? <div className="brain-empty">暂无工具时间线</div> : null}
            </div>
          ) : null}

          {activeView === "tool_output" ? (
            <div className="brain-proposal-source-code">
              {outputReference ? (
                <div className="brain-proposal-source-meta">
                  <span>{outputReference.toolName ?? "工具输出"}</span>
                  <span>{formatBytes(outputReference.sizeBytes)}</span>
                  {outputReference.contentType ? <span>{outputReference.contentType}</span> : null}
                </div>
              ) : null}
              {outputError ? <div className="brain-error">{outputError}</div> : null}
              <pre>{activePackage?.content || "暂无可展示内容"}</pre>
              {activePackage?.page?.hasMore ? (
                <Button
                  kind="ghost"
                  onClick={() => {
                    void loadView("tool_output", {
                      referenceId: activeReferenceId,
                      offset: activePackage.page?.nextOffset,
                      append: true,
                    });
                  }}
                >
                  继续读取
                </Button>
              ) : null}
            </div>
          ) : null}
        </>
      ) : null}
      {!loading && !error && !source ? <div className="brain-empty">选择提案后会读取来源证据</div> : null}
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
