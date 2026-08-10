import { PanelLeft, Plus, Search, Sparkles } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Badge, Button, IconButton } from "../../components/primitives";
import type { AssistantMessage } from "../../api/assistant";
import { listUserTasks, type UserTaskItem } from "../../api/userTasks";
import { useAssistantStore } from "../../state/assistantStore";
import type { AssistantTurnActivity, PendingAssistantMessage } from "../../state/assistantStore";
import { emptyTurn, turnIdFromMessage, turnIdFromSequence } from "../../state/assistantStore";
import { useAssistantTaskStore } from "../../state/assistantTaskStore";
import { useShellStore } from "../../state/shellStore";
import ActivityTimeline from "./ActivityTimeline";
import AssistantFailureCard from "./AssistantFailureCard";
import ClarificationCard from "./ClarificationCard";
import ConfirmationToast from "./ConfirmationToast";
import MessageComposer from "./MessageComposer";
import SafeMarkdown from "./SafeMarkdown";
import SessionSidebar from "./SessionSidebar";
import SubagentDetailDrawer from "./SubagentDetailDrawer";
import UserTaskCard from "./UserTaskCard";
import TaskGraphDialog from "./TaskGraphDialog";
import { MeetingChannelDrawer } from "./MeetingChannelDrawer";
import { TaskBoardPanel } from "./TaskBoardPanel";
import { TodoChecklistPanel } from "./TodoChecklistPanel";

type AssistantDisplayMessage = AssistantMessage | PendingAssistantMessage;

type ThreadBlock =
  | { kind: "message"; message: AssistantDisplayMessage }
  | { kind: "transparency"; turnId: string; turn: AssistantTurnActivity; running: boolean };

function messageKey(message: AssistantDisplayMessage): string | number {
  return "optimisticId" in message ? message.optimisticId : message.sequence;
}

function buildThreadBlocks(
  messages: AssistantDisplayMessage[],
  turns: Record<string, AssistantTurnActivity>,
  activeTurnId: string | undefined,
  running: boolean,
): ThreadBlock[] {
  const blocks: ThreadBlock[] = [];
  for (let index = 0; index < messages.length; index += 1) {
    const message = messages[index];
    blocks.push({ kind: "message", message });

    // 过程时间线插在每个回合的用户消息之后、助理回复之前（先过程、后回复，对齐原型）。
    const turnId = turnIdFromMessage(message);
    if (!turnId) continue;
    const turn = turns[turnId] ?? emptyTurn(turnId);
    const isRunning = running && activeTurnId === turnId;
    // 失败回合不展示思考过程——都失败了，中间步骤对用户没有价值，只留恢复入口。
    const failed = message.role === "user" && "sequence" in message && Boolean(message.failure);
    if (
      !failed &&
      (isRunning || turn.steps.length > 0 || turn.subagents.length > 0 || turn.fromSequence !== undefined)
    ) {
      blocks.push({ kind: "transparency", turnId, turn, running: isRunning });
    }
  }
  return blocks;
}

export function AssistantScreen(): JSX.Element {
  const sessions = useAssistantStore((state) => state.sessions);
  const activeSessionId = useAssistantStore((state) => state.activeSessionId);
  const messages = useAssistantStore((state) => state.messages);
  const pendingOptimisticMessages = useAssistantStore((state) => state.pendingOptimisticMessages);
  const query = useAssistantStore((state) => state.query);
  const draft = useAssistantStore((state) => state.draft);
  const loadingSessions = useAssistantStore((state) => state.loadingSessions);
  const loadingMessages = useAssistantStore((state) => state.loadingMessages);
  const sending = useAssistantStore((state) => state.sending);
  const stopping = useAssistantStore((state) => state.stopping);
  const hasMoreBefore = useAssistantStore((state) => state.hasMoreBefore);
  const progress = useAssistantStore((state) => state.progress);
  const confirmations = useAssistantStore((state) => state.confirmations);
  const publishedSkillCount = useShellStore((state) => state.navigation.publishedSkillCount);
  const setRoute = useShellStore((state) => state.setRoute);
  const loadSessions = useAssistantStore((state) => state.loadSessions);
  const startNewConversation = useAssistantStore((state) => state.startNewConversation);
  const selectSession = useAssistantStore((state) => state.selectSession);
  const loadMoreBefore = useAssistantStore((state) => state.loadMoreBefore);
  const renameSession = useAssistantStore((state) => state.renameSession);
  const deleteSession = useAssistantStore((state) => state.deleteSession);
  const setQuery = useAssistantStore((state) => state.setQuery);
  const setDraft = useAssistantStore((state) => state.setDraft);
  const sendDraft = useAssistantStore((state) => state.sendDraft);
  const stopRun = useAssistantStore((state) => state.stopRun);
  const queuedMessageBySession = useAssistantStore((state) => state.queuedMessageBySession);
  const setQueuedText = useAssistantStore((state) => state.setQueuedText);
  const commitQueued = useAssistantStore((state) => state.commitQueued);
  const editQueued = useAssistantStore((state) => state.editQueued);
  const cancelQueued = useAssistantStore((state) => state.cancelQueued);
  const turnActivityBySession = useAssistantStore((state) => state.turnActivityBySession);
  const activeTurnIdBySession = useAssistantStore((state) => state.activeTurnIdBySession);
  const continueSubagent = useAssistantStore((state) => state.continueSubagent);
  const retryFailedMessage = useAssistantStore((state) => state.retryFailedMessage);
  const retryingFailureBySession = useAssistantStore((state) => state.retryingFailureBySession);
  const decideConfirmation = useAssistantStore((state) => state.decideConfirmation);
  const pendingClarificationBySession = useAssistantStore((state) => state.pendingClarificationBySession);
  const clarificationDraftsBySession = useAssistantStore((state) => state.clarificationDraftsBySession);
  const clarificationSubmittingBySession = useAssistantStore(
    (state) => state.clarificationSubmittingBySession,
  );
  const setClarificationDraft = useAssistantStore((state) => state.setClarificationDraft);
  const submitClarification = useAssistantStore((state) => state.submitClarification);
  const cancelClarification = useAssistantStore((state) => state.cancelClarification);
  const autoApprove = useAssistantStore((state) => state.autoApprove);
  const setAutoApprove = useAssistantStore((state) => state.setAutoApprove);
  const clearIdleTimer = useAssistantStore((state) => state.clearIdleTimer);
  const currentTaskGraph = useAssistantTaskStore((state) => state.currentGraph);
  const taskBoardItems = useAssistantTaskStore((state) => state.boardItems);
  const activeMeeting = useAssistantTaskStore((state) => state.activeMeeting);
  const activeMeetingChannelId = useAssistantTaskStore((state) => state.activeMeeting?.channelId ?? null);
  const taskTodosByTaskId = useAssistantTaskStore((state) => state.todosByTaskId);
  const todoLoadingTaskIds = useAssistantTaskStore((state) => state.todoLoadingTaskIds);
  const taskBoardLoading = useAssistantTaskStore((state) => state.boardLoading);
  const taskMeetingLoading = useAssistantTaskStore((state) => state.meetingLoading);
  const taskNeedsResync = useAssistantTaskStore((state) => state.needsResync);
  const loadCurrentTaskGraph = useAssistantTaskStore((state) => state.loadCurrentGraph);
  const loadTaskBoard = useAssistantTaskStore((state) => state.loadBoard);
  const loadMeeting = useAssistantTaskStore((state) => state.loadMeeting);
  const stopTaskGraph = useAssistantTaskStore((state) => state.stopGraph);
  const continueTaskGraph = useAssistantTaskStore((state) => state.continueGraph);
  const decideTaskAdjudication = useAssistantTaskStore((state) => state.decideAdjudication);
  const resetTaskGraph = useAssistantTaskStore((state) => state.reset);
  const executeResync = useAssistantTaskStore((state) => state.executeResync);
  const loadNewTaskTodos = useAssistantTaskStore((state) => state.loadNewTaskTodos);
  const clearSessionTracking = useAssistantTaskStore((state) => state.clearSessionTracking);
  const userTaskVersion = useAssistantTaskStore((state) => state.userTaskVersion);
  const [historyOpen, setHistoryOpen] = useState(true);
  const [openSubagentId, setOpenSubagentId] = useState<string | null>(null);
  const [editingFailureSeq, setEditingFailureSeq] = useState<number | null>(null);
  const [editedContent, setEditedContent] = useState("");
  const [userTasks, setUserTasks] = useState<UserTaskItem[]>([]);
  const [openGraphDialog, setOpenGraphDialog] = useState<{ graphId: string; title: string } | null>(null);

  useEffect(() => {
    if (!activeSessionId) {
      setUserTasks([]);
      return;
    }
    listUserTasks(activeSessionId)
      .then((res) => setUserTasks(res.tasks ?? []))
      .catch(() => setUserTasks([]));
  }, [activeSessionId, messages.length, userTaskVersion]);

  const activeTurns = useMemo(
    () => (activeSessionId ? turnActivityBySession[activeSessionId] ?? {} : {}),
    [activeSessionId, turnActivityBySession],
  );
  const activeTurnId = activeSessionId ? activeTurnIdBySession[activeSessionId] : undefined;
  const activeSubagents = useMemo(
    () => Object.values(activeTurns).flatMap((turn) => turn.subagents),
    [activeTurns],
  );
  const currentTaskIds = useMemo(
    () => currentTaskGraph?.tasks.map((task) => task.taskId) ?? [],
    [currentTaskGraph],
  );
  const currentTaskIdsKey = currentTaskIds.join("|");
  const openSubagent = activeSubagents.find((item) => item.subagentId === openSubagentId);

  useEffect(() => {
    void loadSessions();
  }, [loadSessions, query]);

  useEffect(() => {
    return () => { clearIdleTimer(); };
  }, [clearIdleTimer]);

  useEffect(() => {
    if (!activeSessionId) {
      resetTaskGraph();
      return;
    }
    void loadCurrentTaskGraph(activeSessionId);
    void loadTaskBoard(activeSessionId);
  }, [activeSessionId, loadCurrentTaskGraph, loadTaskBoard, resetTaskGraph]);

  useEffect(() => {
    if (!activeSessionId || !activeMeetingChannelId) {
      return;
    }
    void loadMeeting(activeSessionId, activeMeetingChannelId);
  }, [activeMeetingChannelId, activeSessionId, loadMeeting]);

  // Todo 加载追踪已移入 store（loadNewTaskTodos / loadedTodoTaskIds / loadedTodoGraphKey）。
  // Screen 只在 currentTaskIds 变化时触发 store 的 loadNewTaskTodos。
  useEffect(() => {
    if (!activeSessionId) {
      clearSessionTracking();
      return;
    }
    loadNewTaskTodos(activeSessionId, currentTaskIds, currentTaskIdsKey);
  }, [activeSessionId, currentTaskIds, currentTaskIdsKey, loadNewTaskTodos, clearSessionTracking]);

  // Resync 编排已移入 store（executeResync）。Screen 只在 needsResync 变为 true 时触发。
  useEffect(() => {
    if (!activeSessionId || !taskNeedsResync) {
      return;
    }
    void executeResync(activeSessionId, activeMeetingChannelId, currentTaskIds);
  }, [activeSessionId, activeMeetingChannelId, currentTaskIds, executeResync, taskNeedsResync]);

  // 切换会话时退出失败消息编辑态，避免编辑框残留在别的会话上。
  useEffect(() => {
    setEditingFailureSeq(null);
    setEditedContent("");
  }, [activeSessionId]);

  const activeSession = sessions.find((session) => session.sessionId === activeSessionId);
  const visibleMessages = useMemo<AssistantDisplayMessage[]>(
    () =>
      activeSessionId
        ? [
            ...messages,
            ...pendingOptimisticMessages.filter((message) => message.sessionId === activeSessionId),
          ]
        : messages,
    [activeSessionId, messages, pendingOptimisticMessages],
  );
  const isRunning = progress.status === "running";
  const threadBlocks = useMemo(
    () => buildThreadBlocks(visibleMessages, activeTurns, activeTurnId, isRunning),
    [activeTurnId, activeTurns, isRunning, visibleMessages],
  );
  // 任务图锚点：优先锚到 userMessageSequence 对应的 turn；当该 sequence 为 null，
  // 或其 origin turn 已分页出当前渲染窗口时，回退到最近一个可见 transparency turn，
  // 保证运行中的图（含停止/继续按钮）不会静默消失。复用 turnIdFromSequence 单一来源。
  const graphAnchorTurnId = useMemo(() => {
    if (!currentTaskGraph) return undefined;
    const seq = currentTaskGraph.userMessageSequence;
    if (seq != null) {
      const exact = turnIdFromSequence(seq);
      if (threadBlocks.some((block) => block.kind === "transparency" && block.turnId === exact)) {
        return exact;
      }
    }
    for (let i = threadBlocks.length - 1; i >= 0; i -= 1) {
      const block = threadBlocks[i];
      if (block.kind === "transparency") return block.turnId;
    }
    return undefined;
  }, [currentTaskGraph, threadBlocks]);
  const conversationTitle = activeSession?.title ?? (visibleMessages.length > 0 ? "当前对话" : "新对话");

  const startEditFailure = (sequence: number, content: string) => {
    setEditingFailureSeq(sequence);
    setEditedContent(content);
  };
  const submitEditFailure = (sessionId: string, sequence: number) => {
    const content = editedContent;
    setEditingFailureSeq(null);
    void retryFailedMessage(sessionId, sequence, content);
  };
  const cancelEditFailure = () => {
    setEditingFailureSeq(null);
    setEditedContent("");
  };

  return (
    <section className={`assistant-screen${historyOpen ? "" : " assistant-screen-collapsed"}`} aria-label="AI 助手">
      <h2 className="me-sr-only">AI 助手</h2>
      <SessionSidebar
        activeSessionId={activeSessionId}
        loading={loadingSessions}
        open={historyOpen}
        query={query}
        sessions={sessions}
        onClose={() => setHistoryOpen(false)}
        onNew={() => {
          void startNewConversation();
          setHistoryOpen(false);
        }}
        onQueryChange={setQuery}
        onSelect={(sessionId) => {
          void selectSession(sessionId);
        }}
        onRename={(sessionId, title) => {
          void renameSession(sessionId, title);
        }}
        onDelete={(sessionId) => {
          void deleteSession(sessionId);
        }}
      />
      <div className="assistant-main">
        <div className="assistant-toolbar">
          <IconButton
            label={historyOpen ? "收起会话列表" : "展开会话列表"}
            aria-expanded={historyOpen}
            onClick={() => setHistoryOpen((value) => !value)}
          >
            <PanelLeft size={16} />
          </IconButton>
          <IconButton
            label="新对话"
            onClick={() => {
              void startNewConversation();
              setHistoryOpen(true);
            }}
          >
            <Plus size={16} />
          </IconButton>
          <div className="assistant-toolbar-divider" />
          <div className="assistant-title">
            <strong>{conversationTitle}</strong>
            <small>{activeSession?.dateLabel ?? "开始一个新的对话"}</small>
          </div>
          <div className="assistant-toolbar-actions">
            <Badge tone={publishedSkillCount > 0 ? "ok" : "neutral"}>已掌握工具 {publishedSkillCount}</Badge>
            <IconButton label="展开会话搜索" onClick={() => setHistoryOpen(true)}>
              <Search size={16} />
            </IconButton>
          </div>
        </div>
        {/* 025: TaskGraphPanel 已移除，任务图节点现在嵌入 ActivityTimeline */}
        <TaskBoardPanel
          items={taskBoardItems}
          loading={taskBoardLoading}
        />
        <TodoChecklistPanel
          tasks={currentTaskGraph?.tasks ?? []}
          todosByTaskId={taskTodosByTaskId}
          loadingTaskIds={todoLoadingTaskIds}
        />
        <div className="assistant-timeline" aria-live="polite">
          {hasMoreBefore ? (
            <div className="assistant-history-more">
              <Button disabled={loadingMessages} kind="secondary" onClick={() => void loadMoreBefore()}>
                加载更早消息
              </Button>
            </div>
          ) : null}
          {loadingMessages ? <div className="assistant-empty">正在加载消息</div> : null}
          {!loadingMessages && visibleMessages.length === 0 ? (
            <div className="assistant-welcome">
              <div className="assistant-welcome-mark" aria-hidden="true">
                <Sparkles size={26} strokeWidth={1.9} />
              </div>
              <h2>今天想完成什么？</h2>
              <p>直接描述任务即可，也可以让已掌握的工具上场。</p>
              <div className="assistant-suggestion-row">
                <Button kind="secondary" onClick={() => setDraft("总结当前任务的目标、约束和下一步。")}>
                  总结当前任务
                </Button>
                <Button kind="secondary" onClick={() => setRoute("teaching")}>
                  教学新工具
                </Button>
                <Button kind="secondary" onClick={() => setRoute("compositions")}>
                  新建组合
                </Button>
              </div>
            </div>
          ) : null}
          <div className="assistant-thread">
            {threadBlocks.map((block) => {
              if (block.kind === "transparency") {
                return activeSessionId ? (
                  <ActivityTimeline
                    key={`turn_${activeSessionId}_${block.turnId}`}
                    sessionId={activeSessionId}
                    turnId={block.turnId}
                    liveSteps={block.turn.steps}
                    running={block.running}
                    afterSequence={block.turn.fromSequence}
                    beforeSequence={block.turn.beforeSequence}
                    subagents={block.turn.subagents}
                    onOpenSubagent={(id) => setOpenSubagentId(id)}
                    onContinueSubagent={(id, note) => void continueSubagent(activeSessionId, id, note)}
                    taskGraph={
                      currentTaskGraph && block.turnId === graphAnchorTurnId
                        ? currentTaskGraph
                        : undefined
                    }
                    todosByTaskId={taskTodosByTaskId}
                    onLoadTodos={(taskId: string) => {
                      if (activeSessionId) void useAssistantTaskStore.getState().loadTodos(activeSessionId, taskId);
                    }}
                    onDecide={(adjudicationId, decision, instruction) => {
                      if (activeSessionId) {
                        void decideTaskAdjudication(activeSessionId, adjudicationId, decision, instruction);
                      }
                    }}
                    onStopGraph={(graphId) => {
                      if (activeSessionId) void stopTaskGraph(activeSessionId, graphId, progress.runId);
                    }}
                    onContinueGraph={(graphId) => {
                      if (activeSessionId) void continueTaskGraph(activeSessionId, graphId);
                    }}
                  />
                ) : null;
              }
              const { message } = block;
              const failureSequence = "sequence" in message ? message.sequence : undefined;
              const failure = "sequence" in message ? message.failure : undefined;
              const isEditingFailure =
                failureSequence !== undefined && failure != null && editingFailureSeq === failureSequence;
              return message.role === "summary" ? (
                <details className="assistant-summary" key={messageKey(message)}>
                  <summary>之前的对话内容</summary>
                  <div className="assistant-summary-body">
                    <SafeMarkdown content={message.content} />
                  </div>
                </details>
              ) : (
                <article className="assistant-message" data-role={message.role} key={messageKey(message)}>
                  {message.role === "assistant" ? <div className="assistant-avatar" aria-hidden="true" /> : null}
                  <div className="assistant-message-content">
                    <div className="assistant-message-meta">{message.role === "user" ? "你" : "Assistant"}</div>
                    {message.rendering === "safe_markdown" ? (
                      <SafeMarkdown content={message.content} />
                    ) : isEditingFailure ? (
                      <textarea
                        className="assistant-message-edit-input"
                        aria-label="编辑这条消息"
                        value={editedContent}
                        rows={3}
                        autoFocus
                        onChange={(event) => setEditedContent(event.currentTarget.value)}
                        onKeyDown={(event) => {
                          if (event.key === "Escape") {
                            event.preventDefault();
                            cancelEditFailure();
                          } else if (
                            (event.metaKey || event.ctrlKey)
                            && event.key === "Enter"
                            && activeSessionId
                            && failureSequence !== undefined
                          ) {
                            event.preventDefault();
                            submitEditFailure(activeSessionId, failureSequence);
                          }
                        }}
                      />
                    ) : (
                      <p>{message.content}</p>
                    )}
                    {message.role === "user" && failureSequence !== undefined && failure && activeSessionId ? (
                      <AssistantFailureCard
                        failure={failure}
                        loading={retryingFailureBySession[activeSessionId] === failureSequence}
                        onRetry={() => {
                          void retryFailedMessage(activeSessionId, failureSequence);
                        }}
                        editing={editingFailureSeq === failureSequence}
                        onStartEdit={() => startEditFailure(failureSequence, message.content)}
                        onSubmitEdit={() => submitEditFailure(activeSessionId, failureSequence)}
                        onCancelEdit={cancelEditFailure}
                      />
                    ) : null}
                  </div>
                </article>
              );
            })}
            {progress.status === "cancelled" ? (
              <div className="assistant-stopped-note">
                已停止。被打断的子任务会标为「已暂停」，可以在卡片上点「继续任务」让它接着做。
              </div>
            ) : null}
          </div>
        </div>
        {openSubagent && activeSessionId ? (
          <SubagentDetailDrawer
            sessionId={activeSessionId}
            subagent={openSubagent}
            onClose={() => setOpenSubagentId(null)}
          />
        ) : null}
        {activeMeeting ? (
          <MeetingChannelDrawer
            meeting={activeMeeting}
            loading={taskMeetingLoading}
            onClose={() => useAssistantTaskStore.getState().closeMeeting()}
          />
        ) : null}
        {openGraphDialog && activeSessionId ? (
          <TaskGraphDialog
            sessionId={activeSessionId}
            graphId={openGraphDialog.graphId}
            taskTitle={openGraphDialog.title}
            onClose={() => setOpenGraphDialog(null)}
          />
        ) : null}
        <div className="assistant-confirmation-stack">
          {confirmations.map((confirmation) => (
            <ConfirmationToast
              confirmation={confirmation}
              key={confirmation.requestId}
              onDecision={(requestId, decision) => {
                void decideConfirmation(requestId, decision);
              }}
              onAllowAll={() => void setAutoApprove(true)}
            />
          ))}
        </div>
        {activeSessionId && pendingClarificationBySession[activeSessionId] ? (
          <ClarificationCard
            clarification={pendingClarificationBySession[activeSessionId]}
            drafts={clarificationDraftsBySession[activeSessionId] ?? {}}
            submitting={Boolean(clarificationSubmittingBySession[activeSessionId])}
            onDraftChange={(questionId, draft) =>
              setClarificationDraft(activeSessionId, questionId, draft)
            }
            onSubmit={() => void submitClarification(activeSessionId)}
            onCancel={() => void cancelClarification(activeSessionId)}
          />
        ) : null}
        {activeSessionId && userTasks.length > 0 ? (
          <div className="me-task-list">
            {userTasks.map((task) => (
              <UserTaskCard
                key={task.taskId}
                sessionId={activeSessionId}
                taskId={task.taskId}
                title={task.title}
                status={task.status}
                onOpenFullGraph={(graphId, title) =>
                  setOpenGraphDialog({ graphId, title })
                }
              />
            ))}
          </div>
        ) : null}
        <MessageComposer
          key={activeSessionId ?? "new"}
          autoApprove={autoApprove}
          draft={draft}
          sending={sending}
          isRunning={isRunning}
          stopping={stopping}
          queued={activeSessionId ? queuedMessageBySession[activeSessionId] : undefined}
          onDraftChange={setDraft}
          onSend={sendDraft}
          onStop={() => void stopRun()}
          onQueuedTextChange={setQueuedText}
          onCommitQueued={commitQueued}
          onEditQueued={editQueued}
          onCancelQueued={cancelQueued}
          onToggleAutoApprove={(newVal) => void setAutoApprove(newVal)}
        />
      </div>
    </section>
  );
}

export default AssistantScreen;
