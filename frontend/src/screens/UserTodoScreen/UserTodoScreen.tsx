import { FormEvent, useEffect, useState } from "react";
import {
  CheckCircle2,
  ChevronDown,
  Circle,
  CircleDot,
  ListTodo,
  Pencil,
  Plus,
  RefreshCcw,
  Save,
  Search,
  Trash2,
  X,
} from "lucide-react";

import { Button, IconButton, Badge } from "../../components/primitives";
import { listUserTodos } from "../../api/userTodos";
import { useUserTodoStore } from "../../state/userTodoStore";
import type { UserTodoItem, UserTodoPriority, UserTodoStatus } from "../../state/userTodoStore";

type EditDraft = {
  title: string;
  description: string;
  status: UserTodoStatus;
  priority: UserTodoPriority;
};

type FilterId = "open" | "all" | "done";

const FILTERS = [
  { id: "open", label: "未完成" },
  { id: "all", label: "全部" },
  { id: "done", label: "已完成" },
] as const;

const PRIORITY_LABELS: Record<UserTodoPriority, string> = {
  urgent: "紧急",
  high: "高",
  medium: "中",
  low: "低",
};

const STATUS_LABELS: Record<UserTodoStatus, string> = {
  pending: "待办",
  in_progress: "进行中",
  done: "已完成",
};

function toEditDraft(todo: UserTodoItem): EditDraft {
  return {
    title: todo.title,
    description: todo.description,
    status: todo.status,
    priority: todo.priority,
  };
}

function formatDate(value: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function priorityTone(priority: UserTodoPriority): "neutral" | "ok" | "warn" | "danger" {
  if (priority === "urgent") return "danger";
  if (priority === "high") return "warn";
  return "neutral";
}

/** 进度环：这个界面的签名元素——一眼看见"今天推进了多少"。 */
function ProgressRing({ pct }: { pct: number }): JSX.Element {
  const radius = 26;
  const circumference = 2 * Math.PI * radius;
  const clamped = Math.min(1, Math.max(0, pct));
  const offset = circumference * (1 - clamped);
  return (
    <svg
      className="user-todo-ring"
      width="60"
      height="60"
      viewBox="0 0 60 60"
      aria-hidden="true"
      focusable="false"
    >
      <circle
        className="user-todo-ring-track"
        cx="30"
        cy="30"
        r={radius}
        fill="none"
        strokeWidth="5"
      />
      <circle
        className="user-todo-ring-fill"
        cx="30"
        cy="30"
        r={radius}
        fill="none"
        strokeWidth="5"
        strokeLinecap="round"
        strokeDasharray={circumference}
        strokeDashoffset={offset}
        transform="rotate(-90 30 30)"
      />
      <text x="30" y="34" textAnchor="middle" className="user-todo-ring-label">
        {Math.round(clamped * 100)}%
      </text>
    </svg>
  );
}

export function UserTodoScreen(): JSX.Element {
  const hydrated = useUserTodoStore((state) => state.hydrated);
  const items = useUserTodoStore((state) => state.items);
  const busy = useUserTodoStore((state) => state.busy);
  const lastError = useUserTodoStore((state) => state.lastError);
  const statusFilter = useUserTodoStore((state) => state.statusFilter);
  const sort = useUserTodoStore((state) => state.sort);
  const query = useUserTodoStore((state) => state.query);
  const draft = useUserTodoStore((state) => state.draft);
  const load = useUserTodoStore((state) => state.load);
  const setStatusFilter = useUserTodoStore((state) => state.setStatusFilter);
  const setSort = useUserTodoStore((state) => state.setSort);
  const setQuery = useUserTodoStore((state) => state.setQuery);
  const setDraft = useUserTodoStore((state) => state.setDraft);
  const createTodo = useUserTodoStore((state) => state.create);
  const updateTodo = useUserTodoStore((state) => state.update);
  const completeTodo = useUserTodoStore((state) => state.complete);
  const removeTodo = useUserTodoStore((state) => state.remove);

  const [editingId, setEditingId] = useState<string | null>(null);
  const [editDraft, setEditDraft] = useState<EditDraft | null>(null);
  const [descOpen, setDescOpen] = useState(false);
  const [progress, setProgress] = useState({ total: 0, done: 0 });

  useEffect(() => {
    void load();
  }, [load]);

  // 进度环口径是「全部待办」的完成度，独立于当前筛选视图拉一次轻量计数。
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const [all, done] = await Promise.all([
          listUserTodos({ status: "all", limit: 1, offset: 0 }),
          listUserTodos({ status: "done", limit: 1, offset: 0 }),
        ]);
        if (!cancelled) setProgress({ total: all.total, done: done.total });
      } catch {
        // 进度环不是关键路径，拉取失败时静默保留上次数值。
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [items, hydrated]);

  const remaining = Math.max(0, progress.total - progress.done);
  const pct = progress.total > 0 ? progress.done / progress.total : 0;
  const filterCount = (id: FilterId): number =>
    id === "open" ? remaining : id === "done" ? progress.done : progress.total;

  const activeItems = items.filter((item) => item.status !== "done");
  const doneItems = items.filter((item) => item.status === "done");
  const showDivider = activeItems.length > 0 && doneItems.length > 0;

  const startEditing = (todo: UserTodoItem) => {
    setEditingId(todo.todoId);
    setEditDraft(toEditDraft(todo));
  };

  const submitCreate = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void createTodo();
  };

  const submitSearch = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void load();
  };

  const saveEdit = () => {
    if (!editingId || !editDraft) return;
    void updateTodo(editingId, editDraft).then(() => {
      setEditingId(null);
      setEditDraft(null);
    });
  };

  const heroSubtitle = (() => {
    if (!hydrated) return "正在读取你的清单…";
    if (progress.total === 0) return "把要做的事记下来，逐件推进";
    if (remaining === 0) return "全部完成，今天辛苦了";
    return `还有 ${remaining} 件未完成`;
  })();

  const renderRow = (todo: UserTodoItem) => {
    const isEditing = editingId === todo.todoId && editDraft;
    return (
      <li
        className="user-todo-row"
        data-status={todo.status}
        data-priority={todo.priority}
        key={todo.todoId}
      >
        {isEditing ? (
          <div className="user-todo-edit">
            <input
              aria-label="编辑标题"
              className="user-todo-edit-title"
              maxLength={200}
              onChange={(event) =>
                setEditDraft({ ...editDraft, title: event.target.value })
              }
              value={editDraft.title}
            />
            <textarea
              aria-label="编辑描述"
              className="user-todo-edit-desc"
              maxLength={2000}
              onChange={(event) =>
                setEditDraft({ ...editDraft, description: event.target.value })
              }
              rows={2}
              value={editDraft.description}
            />
            <select
              aria-label="编辑状态"
              className="user-todo-edit-status"
              onChange={(event) =>
                setEditDraft({
                  ...editDraft,
                  status: event.target.value as UserTodoStatus,
                })
              }
              value={editDraft.status}
            >
              {(["pending", "in_progress", "done"] as const).map((status) => (
                <option key={status} value={status}>
                  {STATUS_LABELS[status]}
                </option>
              ))}
            </select>
            <select
              aria-label="编辑优先级"
              className="user-todo-edit-priority"
              onChange={(event) =>
                setEditDraft({
                  ...editDraft,
                  priority: event.target.value as UserTodoPriority,
                })
              }
              value={editDraft.priority}
            >
              {(["urgent", "high", "medium", "low"] as const).map((priority) => (
                <option key={priority} value={priority}>
                  {PRIORITY_LABELS[priority]}
                </option>
              ))}
            </select>
            <div className="user-todo-edit-actions">
              <IconButton label="保存待办" onClick={saveEdit} disabled={busy}>
                <Save size={15} />
              </IconButton>
              <IconButton
                label="取消编辑"
                onClick={() => {
                  setEditingId(null);
                  setEditDraft(null);
                }}
              >
                <X size={15} />
              </IconButton>
            </div>
          </div>
        ) : (
          <>
            <button
              aria-label={todo.status === "done" ? "撤销完成" : "标记完成"}
              className="user-todo-check"
              onClick={() => void completeTodo(todo.todoId, todo.status !== "done")}
              disabled={busy}
              type="button"
            >
              {todo.status === "done" ? (
                <CheckCircle2 size={20} />
              ) : todo.status === "in_progress" ? (
                <CircleDot size={20} />
              ) : (
                <Circle size={20} />
              )}
            </button>
            <div className="user-todo-main">
              <div className="user-todo-titleline">
                <strong>{todo.title}</strong>
                <Badge tone={priorityTone(todo.priority)}>
                  {PRIORITY_LABELS[todo.priority]}
                </Badge>
              </div>
              {todo.description ? <p>{todo.description}</p> : null}
              <div className="user-todo-meta">
                <span>创建 {formatDate(todo.createdAt)}</span>
                {todo.completedAt ? (
                  <span>完成 {formatDate(todo.completedAt)}</span>
                ) : null}
              </div>
            </div>
            <div className="user-todo-row-actions">
              <IconButton label="编辑待办" onClick={() => startEditing(todo)}>
                <Pencil size={15} />
              </IconButton>
              <IconButton
                label="删除待办"
                onClick={() => {
                  if (window.confirm("删除这个待办？")) {
                    void removeTodo(todo.todoId);
                  }
                }}
              >
                <Trash2 size={15} />
              </IconButton>
            </div>
          </>
        )}
      </li>
    );
  };

  return (
    <section className="user-todo-screen" aria-label="待办列表">
      <header className="user-todo-hero">
        <div className="user-todo-hero-text">
          <h2>待办</h2>
          <p>{heroSubtitle}</p>
        </div>
        <div className="user-todo-hero-right">
          <IconButton label="刷新列表" onClick={() => void load()} disabled={busy}>
            <RefreshCcw size={16} />
          </IconButton>
          <div className="user-todo-progress" aria-label={`完成 ${progress.done} 件，共 ${progress.total} 件`}>
            <ProgressRing pct={pct} />
            <div className="user-todo-progress-text">
              <strong>
                {progress.done} / {progress.total}
              </strong>
              <span>已完成</span>
            </div>
          </div>
        </div>
      </header>

      <form className="user-todo-create" onSubmit={submitCreate}>
        <Plus className="user-todo-create-icon" size={18} aria-hidden="true" />
        <input
          aria-label="待办标题"
          maxLength={200}
          onChange={(event) => setDraft("title", event.target.value)}
          placeholder="添加一件要做的事…"
          value={draft.title}
        />
        <select
          aria-label="待办优先级"
          onChange={(event) => setDraft("priority", event.target.value as UserTodoPriority)}
          value={draft.priority}
        >
          {(["urgent", "high", "medium", "low"] as const).map((priority) => (
            <option key={priority} value={priority}>
              {PRIORITY_LABELS[priority]}
            </option>
          ))}
        </select>
        <Button kind="primary" type="submit" disabled={busy || !draft.title.trim()}>
          <Plus size={15} />
          <span>新增</span>
        </Button>
        <button
          aria-expanded={descOpen}
          aria-label="展开待办描述"
          className="user-todo-desc-toggle"
          onClick={() => setDescOpen((open) => !open)}
          type="button"
        >
          <ChevronDown size={14} />
          <span>描述</span>
        </button>
        {descOpen ? (
          <textarea
            aria-label="待办描述"
            className="user-todo-desc-input"
            maxLength={2000}
            onChange={(event) => setDraft("description", event.target.value)}
            placeholder="补充说明（可选）"
            rows={2}
            value={draft.description}
          />
        ) : null}
      </form>

      <div className="user-todo-toolbar">
        <div className="user-todo-filter" role="tablist" aria-label="待办筛选">
          {FILTERS.map((filter) => {
            const count = filterCount(filter.id);
            return (
              <button
                aria-selected={statusFilter === filter.id}
                className="user-todo-filter-button"
                data-active={statusFilter === filter.id}
                key={filter.id}
                onClick={() => setStatusFilter(filter.id)}
                role="tab"
                type="button"
              >
                <span>{filter.label}</span>
                {count > 0 ? (
                  <em aria-hidden="true" className="user-todo-filter-count">
                    {count}
                  </em>
                ) : null}
              </button>
            );
          })}
        </div>
        <form className="user-todo-search" onSubmit={submitSearch}>
          <Search size={15} aria-hidden="true" />
          <input
            aria-label="搜索待办"
            onChange={(event) => setQuery(event.target.value)}
            placeholder="搜索"
            value={query}
          />
        </form>
        <select
          aria-label="待办排序"
          onChange={(event) => setSort(event.target.value as typeof sort)}
          value={sort}
        >
          <option value="created_desc">最新创建</option>
          <option value="created_asc">最早创建</option>
          <option value="priority_desc">优先级高到低</option>
          <option value="priority_asc">优先级低到高</option>
        </select>
      </div>

      {lastError ? <div className="user-todo-error" role="alert">{lastError}</div> : null}

      {busy && items.length === 0 ? (
        <div className="user-todo-status">正在加载…</div>
      ) : null}

      {!busy && hydrated && items.length === 0 ? (
        <div className="user-todo-empty">
          <ListTodo size={40} aria-hidden="true" />
          <p>还没有待办</p>
          <span>在上面添加第一件要做的事吧</span>
        </div>
      ) : null}

      {items.length > 0 ? (
        <ul className="user-todo-list">
          {activeItems.map(renderRow)}
          {showDivider ? (
            <li className="user-todo-divider" aria-hidden="true" key="divider" />
          ) : null}
          {doneItems.map(renderRow)}
        </ul>
      ) : null}
    </section>
  );
}

export default UserTodoScreen;
