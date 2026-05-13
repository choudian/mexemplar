import { Mic, Paperclip, Send } from "lucide-react";

import { Button, IconButton } from "../../components/primitives";

export function MessageComposer({
  draft,
  sending,
  onDraftChange,
  onSend,
}: {
  draft: string;
  sending: boolean;
  onDraftChange: (draft: string) => void;
  onSend: () => void;
}): JSX.Element {
  return (
    <form
      className="assistant-composer"
      onSubmit={(event) => {
        event.preventDefault();
        onSend();
      }}
    >
      <textarea
        aria-label="输入消息"
        placeholder="输入消息"
        value={draft}
        onChange={(event) => onDraftChange(event.currentTarget.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            onSend();
          }
        }}
      />
      <div className="assistant-composer-bar">
        <div>
          <IconButton label="附件暂不可用" disabled>
            <Paperclip size={16} />
          </IconButton>
          <IconButton label="语音输入暂不可用" disabled>
            <Mic size={16} />
          </IconButton>
        </div>
        <Button disabled={sending || !draft.trim()} kind="primary" type="submit">
          <Send size={15} />
          <span>{sending ? "发送中" : "发送"}</span>
        </Button>
      </div>
    </form>
  );
}

export default MessageComposer;
