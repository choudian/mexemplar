import { Brain, CircleDot } from "lucide-react";
import { useMemo, useRef, useState } from "react";

import { useTeachingStore } from "../../state/teachingStore";
import { AgentBubble, ChatComposer, CollapsibleNumberedList, AiMessageContent, ThinkingIndicator, useScrollToBottom, UserBubble, filterAgentMessages } from "./shared";

// ── Main component ────────────────────────────────────────────────────────

function IntentStage(): JSX.Element {
  const messages = useTeachingStore((s) => s.messages);
  const progressLog = useTeachingStore((s) => s.progressLog);
  const busy = useTeachingStore((s) => s.busy);
  const stage = useTeachingStore((s) => s.stage);
  const replyIntent = useTeachingStore((s) => s.replyIntent);

  const [draft, setDraft] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  const pmMessages = useMemo(() => filterAgentMessages(messages, "pm"), [messages]);

  useScrollToBottom(scrollRef, [pmMessages.length, busy]);

  const disabled = busy || stage !== "intent_confirmation";

  return (
    <div className="teaching-chat-stage">
      <div className="teaching-chat-scroll me-scroll" ref={scrollRef}>
        <div className="teaching-chat-thread">
          {progressLog.length > 0 ? (
            <CollapsibleNumberedList
              title="刚才的录制"
              subtitle={<><span className="me-mono">{progressLog.length}</span> 步事件线索</>}
              toggleOpenLabel="收起"
              toggleClosedLabel="查看录制"
              icon={<CircleDot size={14} />}
              items={progressLog.map((text) => ({ text }))}
            />
          ) : null}

          {pmMessages.length === 0 && !busy ? (
            <AgentBubble icon={<Brain size={16} />} label="需求分析师">
              <div>我正在分析刚才的录制数据，请稍等…</div>
            </AgentBubble>
          ) : null}

          {pmMessages.map((m, i) => {
            if (m.from === "user") return <UserBubble key={`u-${i}`} text={m.text} />;
            return (
              <AgentBubble key={`a-${i}`} icon={<Brain size={16} />} label="需求分析师">
                <div>
                  <AiMessageContent headline={m.headline} detail={m.detail} />
                  {m.error ? (
                    <div style={{ marginTop: 4, color: "var(--danger)", fontSize: 12.5 }}>分析遇到问题，请调整描述后重试。</div>
                  ) : null}
                </div>
              </AgentBubble>
            );
          })}

          {busy ? <ThinkingIndicator icon={<Brain size={16} />} /> : null}
        </div>
      </div>

      <div className="teaching-composer-wrap">
        <ChatComposer
          draft={draft}
          disabled={disabled}
          onSend={() => {
            if (draft.trim()) {
              const submittedDraft = draft;
              void replyIntent(submittedDraft).then((accepted) => {
                if (accepted) {
                  setDraft((current) => current === submittedDraft ? "" : current);
                }
              });
            }
          }}
          setDraft={setDraft}
          placeholder="回复需求分析师…"
        />
      </div>
    </div>
  );
}

export default IntentStage;
