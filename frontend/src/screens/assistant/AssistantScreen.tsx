import { useEffect, useState } from "react";

import { Badge, Button } from "../../components/primitives";
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
  const [historyOpen, setHistoryOpen] = useState(true);

  useEffect(() => {
    void loadSessions();
  }, [loadSessions, query]);

  return (
    <section className={`assistant-screen${historyOpen ? "" : " assistant-screen-collapsed"}`} aria-label="AI 助手">
      {historyOpen ? (
        <SessionSidebar
          sessions={sessions}
          activeSessionId={activeSessionId}
          query={query}
          loading={loadingSessions}
          onQueryChange={setQuery}
          onNew={() => {
            void createSession();
          }}
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
      ) : null}
      <div className="assistant-main">
        <div className="assistant-toolbar">
          <Button
            aria-expanded={historyOpen}
            kind="secondary"
            onClick={() => setHistoryOpen((value) => !value)}
          >
            对话列表
          </Button>
          <Badge tone={publishedSkillCount > 0 ? "ok" : "neutral"}>已掌握技能 {publishedSkillCount}</Badge>
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
              <h2>AI 助手</h2>
              <p>从下方输入开始新的对话。</p>
              <div className="assistant-suggestion-row">
                <Button kind="secondary" onClick={() => setDraft("总结当前任务的目标、约束和下一步。")}>
                  总结当前任务
                </Button>
                <Button kind="secondary" onClick={() => setRoute("teaching")}>
                  开始技能教学
                </Button>
                <Button kind="secondary" onClick={() => setRoute("compositions")}>
                  创建技能组合
                </Button>
              </div>
            </div>
          ) : null}
          {messages.map((message) => (
            <article className="assistant-message" data-role={message.role} key={message.sequence}>
              <div className="assistant-message-meta">{message.role === "user" ? "你" : "Assistant"}</div>
              {message.rendering === "safe_markdown" ? (
                <SafeMarkdown content={message.content} />
              ) : (
                <p>{message.content}</p>
              )}
            </article>
          ))}
          <ExecutionSummary status={progress.status} headline={progress.headline} />
          {lastError ? <div className="assistant-error">{lastError}</div> : null}
        </div>
        <div className="assistant-confirmation-stack">
          {confirmations.map((confirmation) => (
            <ConfirmationToast
              confirmation={confirmation}
              key={confirmation.requestId}
              onDecision={(requestId, decision) => {
                void decideConfirmation(requestId, decision);
              }}
            />
          ))}
        </div>
        <MessageComposer draft={draft} sending={sending} onDraftChange={setDraft} onSend={sendDraft} />
      </div>
    </section>
  );
}

export default AssistantScreen;
