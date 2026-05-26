import { ChevronDown, Send } from "lucide-react";
import type { RefObject } from "react";
import { useEffect, useLayoutEffect, useState } from "react";

import { LongPastePreview } from "../../components/LongPastePreview";
import type { ChatAgent, ChatMessage } from "../../state/teachingStore";
import { useLongPasteCollapse } from "../../hooks/useLongPasteCollapse";
import { SafeMarkdown } from "../assistant/SafeMarkdown";

export function UserBubble({ text }: { text: string }): JSX.Element {
  return (
    <div className="teaching-user-msg">
      <div className="teaching-user-bubble">{text}</div>
    </div>
  );
}

export function AgentBubble({
  icon,
  label,
  children,
}: {
  icon: React.ReactNode;
  label: string;
  children: React.ReactNode;
}): JSX.Element {
  return (
    <div className="teaching-ai-msg">
      <div className="teaching-ai-avatar">{icon}</div>
      <div className="teaching-ai-body">
        <div className="teaching-ai-label">{label}</div>
        <div className="teaching-ai-content">{children}</div>
      </div>
    </div>
  );
}

export function ThinkingIndicator({ icon }: { icon: React.ReactNode }): JSX.Element {
  return (
    <div className="teaching-thinking">
      <div className="teaching-ai-avatar">{icon}</div>
      <div className="teaching-thinking-dots">
        <i className="teaching-thinking-dot" />
        <i className="teaching-thinking-dot" />
        <i className="teaching-thinking-dot" />
      </div>
    </div>
  );
}

export function ChatComposer({
  draft,
  setDraft,
  onSend,
  disabled,
  placeholder,
  hint,
}: {
  draft: string;
  setDraft: (v: string) => void;
  onSend: () => void;
  disabled?: boolean;
  placeholder?: string;
  hint?: React.ReactNode;
}): JSX.Element {
  const collapseState = useLongPasteCollapse({
    draft,
    onDraftChange: setDraft,
    resetWhenEmpty: !disabled,
  });

  const handleSend = () => {
    onSend();
  };

  return (
    <div className="teaching-composer" data-disabled={disabled ? "true" : undefined}>
      {collapseState.isQualified ? (
        <LongPastePreview
          draft={draft}
          collapseState={collapseState}
          onDraftChange={setDraft}
          onSend={handleSend}
          sendDisabled={!draft.trim() || disabled}
          editingDisabled={disabled}
        />
      ) : (
        <textarea
          disabled={disabled}
          onChange={(e) => setDraft(e.currentTarget.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              handleSend();
            }
          }}
          onPaste={collapseState.handlePaste}
          placeholder={placeholder ?? "输入消息…"}
          rows={2}
          style={{ resize: "none" }}
          value={draft}
        />
      )}
      {!collapseState.isCollapsed && (
        <div className="teaching-composer-bar">
          <div className="teaching-composer-hint">
            {hint ?? (
              <>
                <kbd className="teaching-kbd">⏎</kbd> 发送 · <kbd className="teaching-kbd">⇧⏎</kbd> 换行
              </>
            )}
          </div>
          <button
            className="teaching-composer-send"
            disabled={!draft.trim() || disabled}
            onClick={handleSend}
            type="button"
          >
            <Send size={15} />
          </button>
        </div>
      )}
    </div>
  );
}

export function useScrollToBottom(ref: RefObject<HTMLElement | null>, deps: readonly unknown[]): void {
  useLayoutEffect(() => {
    const element = ref.current;
    if (!element) return;
    element.scrollTop = element.scrollHeight;
    const frame = window.requestAnimationFrame(() => {
      element.scrollTop = element.scrollHeight;
    });
    return () => window.cancelAnimationFrame(frame);
  }, deps);

  useEffect(() => {
    const element = ref.current;
    const content = element?.firstElementChild;
    if (!element || !content || !("ResizeObserver" in window)) return;
    const observer = new ResizeObserver(() => {
      element.scrollTop = element.scrollHeight;
    });
    observer.observe(content);
    return () => observer.disconnect();
  }, deps);
}

export function CollapsibleChevron({ open }: { open: boolean }): JSX.Element {
  return (
    <ChevronDown
      size={14}
      style={{
        verticalAlign: "middle",
        marginLeft: 4,
        transform: open ? "rotate(180deg)" : "rotate(0)",
        transition: "transform .2s",
      }}
    />
  );
}

function TeachingMarkdown({ content }: { content: string }): JSX.Element {
  return (
    <div className="teaching-markdown">
      <SafeMarkdown content={content} />
    </div>
  );
}

export function AiMessageContent({ headline, detail }: { headline: string; detail?: string }): JSX.Element {
  return (
    <div>
      <TeachingMarkdown content={headline} />
      {detail ? (
        <div className="teaching-ai-detail">
          <TeachingMarkdown content={detail} />
        </div>
      ) : null}
    </div>
  );
}

export function filterAgentMessages(messages: ChatMessage[], agent: ChatAgent): ChatMessage[] {
  return messages.filter((m): m is ChatMessage => m.from === "user" || (m.from === "ai" && m.agent === agent));
}

export function CollapsibleNumberedList({
  title,
  subtitle,
  toggleOpenLabel,
  toggleClosedLabel,
  icon,
  items,
}: {
  title: string;
  subtitle?: React.ReactNode;
  toggleOpenLabel: string;
  toggleClosedLabel: string;
  icon?: React.ReactNode;
  items: { text: string; detail?: string }[];
}): JSX.Element {
  const [open, setOpen] = useState(false);
  return (
    <div className="teaching-collapsible-list">
      <button className="teaching-collapsible-list-header" onClick={() => setOpen((v) => !v)} type="button">
        {icon ? <div className="teaching-collapsible-list-icon">{icon}</div> : null}
        <div style={{ flex: 1, minWidth: 0 }}>
          <h4>{title}</h4>
          {subtitle ? <small>{subtitle}</small> : null}
        </div>
        <span className="teaching-collapsible-list-toggle">
          {open ? toggleOpenLabel : toggleClosedLabel}
          <CollapsibleChevron open={open} />
        </span>
      </button>
      {open && items.length > 0 ? (
        <div className="teaching-collapsible-list-body">
          {items.map((item, i) => (
            <div className="teaching-collapsible-list-item" key={i}>
              <span className="me-mono">{String(i + 1).padStart(2, "0")}</span>
              <div>
                <span>{item.text}</span>
                {item.detail ? <div className="teaching-collapsible-list-item-detail">{item.detail}</div> : null}
              </div>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}
