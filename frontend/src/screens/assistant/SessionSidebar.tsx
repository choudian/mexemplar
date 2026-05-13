import { Check, Pencil, Plus, Search, Trash2, X } from "lucide-react";
import { useState } from "react";

import type { AssistantSession } from "../../api/assistant";
import { Button, IconButton } from "../../components/primitives";

export function SessionSidebar({
  sessions,
  activeSessionId,
  query,
  loading,
  onQueryChange,
  onNew,
  onSelect,
  onRename,
  onDelete,
}: {
  sessions: AssistantSession[];
  activeSessionId: string | null;
  query: string;
  loading: boolean;
  onQueryChange: (query: string) => void;
  onNew: () => void;
  onSelect: (sessionId: string) => void;
  onRename: (sessionId: string, title: string) => void;
  onDelete: (sessionId: string) => void;
}): JSX.Element {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [titleDraft, setTitleDraft] = useState("");

  return (
    <aside className="assistant-sidebar" aria-label="对话列表">
      <div className="assistant-sidebar-top">
        <Button kind="primary" onClick={onNew}>
          <Plus size={15} />
          <span>新对话</span>
        </Button>
        <label className="assistant-search">
          <Search size={15} />
          <input
            aria-label="搜索对话"
            value={query}
            onChange={(event) => onQueryChange(event.currentTarget.value)}
            placeholder="搜索"
          />
        </label>
      </div>
      <div className="assistant-session-list" data-loading={loading}>
        {sessions.length === 0 ? (
          <div className="assistant-empty">{loading ? "正在加载" : "暂无对话"}</div>
        ) : null}
        {sessions.map((session) => {
          const editing = editingId === session.sessionId;
          return (
            <div
              className="assistant-session-row"
              data-active={session.sessionId === activeSessionId}
              key={session.sessionId}
            >
              {editing ? (
                <form
                  onSubmit={(event) => {
                    event.preventDefault();
                    onRename(session.sessionId, titleDraft);
                    setEditingId(null);
                  }}
                >
                  <input
                    aria-label="会话标题"
                    value={titleDraft}
                    onChange={(event) => setTitleDraft(event.currentTarget.value)}
                  />
                  <IconButton label="保存标题" type="submit">
                    <Check size={14} />
                  </IconButton>
                  <IconButton label="取消重命名" onClick={() => setEditingId(null)}>
                    <X size={14} />
                  </IconButton>
                </form>
              ) : (
                <>
                  <button className="assistant-session-main" type="button" onClick={() => onSelect(session.sessionId)}>
                    <span>{session.title}</span>
                    <small>{session.preview || session.dateLabel}</small>
                  </button>
                  <IconButton
                    label="重命名对话"
                    onClick={() => {
                      setEditingId(session.sessionId);
                      setTitleDraft(session.title);
                    }}
                  >
                    <Pencil size={14} />
                  </IconButton>
                  <IconButton label="删除对话" onClick={() => onDelete(session.sessionId)}>
                    <Trash2 size={14} />
                  </IconButton>
                </>
              )}
            </div>
          );
        })}
      </div>
    </aside>
  );
}

export default SessionSidebar;
