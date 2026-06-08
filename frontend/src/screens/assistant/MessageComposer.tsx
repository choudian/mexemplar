import { Clock3, Mic, Paperclip, Pencil, Send, ShieldCheck, Square, X } from "lucide-react";

import { Button, IconButton, Toggle } from "../../components/primitives";
import { LongPastePreview } from "../../components/LongPastePreview";
import { useLongPasteCollapse } from "../../hooks/useLongPasteCollapse";
import type { QueuedMessage } from "../../state/assistantStore";

function MessageComposer({
  draft,
  sending,
  autoApprove,
  isRunning = false,
  stopping = false,
  queued,
  onDraftChange,
  onSend,
  onStop = () => {},
  onQueuedTextChange = () => {},
  onCommitQueued = () => {},
  onEditQueued = () => {},
  onCancelQueued = () => {},
  onToggleAutoApprove,
}: {
  draft: string;
  sending: boolean;
  autoApprove: boolean;
  // 助理真实运行态（progress.status==='running'）：门控输入→排队、发送按钮切为"停止"。
  isRunning?: boolean;
  stopping?: boolean;
  // 当前会话的排队消息（US2）：running 时整框三态（editing/queued）。
  queued?: QueuedMessage | undefined;
  onDraftChange: (draft: string) => void;
  onSend: () => void;
  onStop?: () => void;
  onQueuedTextChange?: (text: string) => void;
  onCommitQueued?: () => void;
  onEditQueued?: () => void;
  onCancelQueued?: () => void;
  onToggleAutoApprove: (enabled: boolean) => void;
}): JSX.Element {
  const collapseState = useLongPasteCollapse({
    draft,
    onDraftChange,
    resetWhenEmpty: !sending,
  });

  const handleSend = () => {
    if (isRunning) return; // 运行中门控：不发出新的唤醒消息（FR-001）
    onSend();
  };

  const queuedText = queued?.text ?? "";
  const isQueuedCommitted = isRunning && queued?.state === "queued";

  // 长文本粘贴预览态：独立卡片（自带展开/收起·清除·发送），不进输入框 shell。
  const isLongPaste = !isRunning && collapseState.isQualified;

  let inputArea: JSX.Element;
  if (isQueuedCommitted) {
    // 排队态：整框展示已排队内容；双击或聚焦后回车进入编辑（键盘可达，不以双击为唯一入口，P2-a11y）
    inputArea = (
      <div
        className="assistant-queued-box"
        role="button"
        tabIndex={0}
        aria-label="已排队的下一条消息，双击或按回车编辑"
        onDoubleClick={onEditQueued}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            onEditQueued();
          }
        }}
      >
        <span className="assistant-queued-hint">已排队 · 双击或回车编辑</span>
        <p className="assistant-queued-text">{queuedText}</p>
      </div>
    );
  } else if (isRunning) {
    // 编辑态：助理在忙时写下一条；回车或失焦提交为排队，编辑态绝不外发（FR-012/FR-015）
    inputArea = (
      <textarea
        aria-label="排队下一条消息"
        placeholder="助理在忙，先写好下一条，回车排队…"
        value={queuedText}
        onChange={(event) => onQueuedTextChange(event.currentTarget.value)}
        onBlur={onCommitQueued}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            onCommitQueued();
          }
        }}
      />
    );
  } else {
    inputArea = (
      <textarea
        aria-label="输入消息"
        placeholder="问点什么，或描述一项任务..."
        value={draft}
        onChange={(event) => onDraftChange(event.currentTarget.value)}
        onPaste={collapseState.handlePaste}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            handleSend();
          }
        }}
      />
    );
  }

  const hasQueuedText = queuedText.trim().length > 0;
  const canCancelQueue = isRunning && (isQueuedCommitted || hasQueuedText);

  // 运行时排队提示条（三态）：排队中 / 编辑中 / 空闲待写；让"先写下一条"行为对用户可见、可解释。
  let ribbon: JSX.Element | null = null;
  if (isQueuedCommitted) {
    ribbon = (
      <div className="assistant-queue-ribbon" data-mode="queued">
        <Clock3 size={13} className="assistant-queue-clock" />
        <span>排队中 · 助理空了自动发出</span>
        <button type="button" className="assistant-queue-edit" onClick={onEditQueued}>
          <Pencil size={11} />
          编辑
        </button>
      </div>
    );
  } else if (isRunning && hasQueuedText) {
    ribbon = (
      <div className="assistant-queue-ribbon" data-mode="editing">
        <Pencil size={13} />
        <span>编辑中 · 回车或点别处即可排队（编辑时不会发出）</span>
      </div>
    );
  } else if (isRunning) {
    ribbon = (
      <div className="assistant-queue-ribbon" data-mode="empty">
        <Clock3 size={13} />
        <span>助理正忙 · 先写下一条，回车即排队，空了自动发</span>
      </div>
    );
  }

  const shellState = isQueuedCommitted ? "queued" : isRunning ? "editing" : undefined;

  return (
    <form
      className="assistant-composer"
      data-running={isRunning ? "true" : undefined}
      onSubmit={(event) => {
        event.preventDefault();
        handleSend();
      }}
    >
      {ribbon}
      {isLongPaste ? (
        <LongPastePreview
          draft={draft}
          collapseState={collapseState}
          onDraftChange={onDraftChange}
          onSend={handleSend}
          sendDisabled={sending || !draft.trim()}
        />
      ) : (
        // 输入框 shell：textarea/排队框在上、工具栏在容器内底部作为独立一行——
        // 一体化外观且工具栏永不压字（与文字是上下兄弟，各占独立区域）。
        <div className="assistant-composer-shell" data-state={shellState}>
          {inputArea}
          <div className="assistant-composer-bar">
            <div className="assistant-composer-tools">
              {canCancelQueue ? (
                <button type="button" className="assistant-queue-cancel" onClick={onCancelQueued}>
                  <X size={13} />
                  <span>取消排队</span>
                </button>
              ) : null}
              <Toggle
                label="全部允许"
                data-guard="auto-approve"
                pressed={autoApprove}
                onPressedChange={onToggleAutoApprove}
              >
                <ShieldCheck size={14} />
                <span>全部允许</span>
              </Toggle>
              <IconButton label="附件暂不可用" disabled>
                <Paperclip size={16} />
              </IconButton>
              <IconButton label="语音输入暂不可用" disabled>
                <Mic size={16} />
              </IconButton>
            </div>
            {isRunning ? (
              <Button kind="secondary" type="button" aria-label="停止" onClick={onStop}>
                <Square size={14} />
                <span>{stopping ? "停止中" : "停止"}</span>
              </Button>
            ) : (
              <Button disabled={sending || !draft.trim()} kind="primary" type="submit">
                <Send size={15} />
                <span>{sending ? "发送中" : "发送"}</span>
              </Button>
            )}
          </div>
        </div>
      )}
    </form>
  );
}

export default MessageComposer;
