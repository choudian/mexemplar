import { PanelLeft, Plus, Search } from "lucide-react";
import { useEffect, useState } from "react";

import { Badge, Button, IconButton } from "../../components/primitives";
import { useAssistantStore } from "../../state/assistantStore";
import { useShellStore } from "../../state/shellStore";
import ConfirmationToast from "./ConfirmationToast";
import ExecutionSummary from "./ExecutionSummary";
import MessageComposer from "./MessageComposer";
import SafeMarkdown from "./SafeMarkdown";
import SessionSidebar from "./SessionSidebar";

export function AssistantScreen(): JSX.Element {
  const sessions = useAssistantStore((state) => state.sessions);
  const activeSessionId = useAssistantStore((state) => state.activeSessionId);
  const messages = useAssistantStore((state) => state.messages);
  const query = useAssistantStore((state) => state.query);
  const draft = useAssistantStore((state) => state.draft);
  const loadingSessions = useAssistantStore((state) => state.loadingSessions);
  const loadingMessages = useAssistantStore((state) => state.loadingMessages);
  const sending = useAssistantStore((state) => state.sending);
  const hasMoreBefore = useAssistantStore((state) => state.hasMoreBefore);
  const progress = useAssistantStore((state) => state.progress);
  const confirmations = useAssistantStore((state) => state.confirmations);
  const lastError = useAssistantStore((state) => state.lastError);
  const publishedSkillCount = useShellStore((state) => state.navigation.publishedSkillCount);
  const setRoute = useShellStore((state) => state.setRoute);
  const loadSessions = useAssistantStore((state) => state.loadSessions);
  const createSession = useAssistantStore((state) => state.createSession);
  const selectSession = useAssistantStore((state) => state.selectSession);
  const loadMoreBefore = useAssistantStore((state) => state.loadMoreBefore);
  const renameSession = useAssistantStore((state) => state.renameSession);
  const deleteSession = useAssistantStore((state) => state.deleteSession);
  const setQuery = useAssistantStore((state) => state.setQuery);
  const setDraft = useAssistantStore((state) => state.setDraft);
  const sendDraft = useAssistantStore((state) => state.sendDraft);
  const decideConfirmation = useAssistantStore((state) => state.decideConfirmation);
  const autoApprove = useAssistantStore((state) => state.autoApprove);
  const setAutoApprove = useAssistantStore((state) => state.setAutoApprove);
  const clearIdleTimer = useAssistantStore((state) => state.clearIdleTimer);
  const [historyOpen, setHistoryOpen] = useState(true);

  useEffect(() => {
    void loadSessions();
  }, [loadSessions, query]);

  useEffect(() => {
    return () => { clearIdleTimer(); };
  }, [clearIdleTimer]);

  const activeSession = sessions.find((session) => session.sessionId === activeSessionId);
  const conversationTitle = activeSession?.title ?? (messages.length > 0 ? "当前对话" : "新对话");

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
          void createSession();
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
              void createSession();
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
            <Badge tone={publishedSkillCount > 0 ? "ok" : "neutral"}>已掌握技能 {publishedSkillCount}</Badge>
            <IconButton label="展开会话搜索" onClick={() => setHistoryOpen(true)}>
              <Search size={16} />
            </IconButton>
          </div>
        </div>
        <div className="assistant-timeline" aria-live="polite">
          {hasMoreBefore ? (
            <div className="assistant-history-more">
              <Button disabled={loadingMessages} kind="secondary" onClick={() => void loadMoreBefore()}>
                加载更早消息
              </Button>
            </div>
          ) : null}
          {loadingMessages ? <div className="assistant-empty">正在加载消息</div> : null}
          {!loadingMessages && messages.length === 0 ? (
            <div className="assistant-welcome">
              <div className="assistant-welcome-mark" aria-hidden="true" />
              <h2>今天想完成什么？</h2>
              <p>直接描述任务即可，也可以让已掌握的技能上场。</p>
              <div className="assistant-suggestion-row">
                <Button kind="secondary" onClick={() => setDraft("总结当前任务的目标、约束和下一步。")}>
                  总结当前任务
                </Button>
                <Button kind="secondary" onClick={() => setRoute("teaching")}>
                  教学新技能
                </Button>
                <Button kind="secondary" onClick={() => setRoute("compositions")}>
                  新建组合
                </Button>
              </div>
            </div>
          ) : null}
          <div className="assistant-thread">
            {messages.map((message) =>
              message.role === "summary" ? (
                <details className="assistant-summary" key={message.sequence}>
                  <summary>之前的对话内容</summary>
                  <div className="assistant-summary-body">
                    <SafeMarkdown content={message.content} />
                  </div>
                </details>
              ) : (
                <article className="assistant-message" data-role={message.role} key={message.sequence}>
                  {message.role === "assistant" ? <div className="assistant-avatar" aria-hidden="true" /> : null}
                  <div className="assistant-message-content">
                    <div className="assistant-message-meta">{message.role === "user" ? "你" : "Assistant"}</div>
                    {message.rendering === "safe_markdown" ? (
                      <SafeMarkdown content={message.content} />
                    ) : (
                      <p>{message.content}</p>
                    )}
                  </div>
                </article>
              ),
            )}
            <ExecutionSummary status={progress.status} headline={progress.headline} />
            {lastError ? <div className="assistant-error">{lastError}</div> : null}
          </div>
        </div>
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
        <MessageComposer
          key={activeSessionId ?? "new"}
          autoApprove={autoApprove}
          draft={draft}
          sending={sending}
          onDraftChange={setDraft}
          onSend={sendDraft}
          onToggleAutoApprove={(newVal) => void setAutoApprove(newVal)}
        />
      </div>
    </section>
  );
}

export default AssistantScreen;
