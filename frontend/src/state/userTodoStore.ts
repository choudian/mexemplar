import { create } from "zustand";

import {
  completeUserTodo,
  createUserTodo,
  deleteUserTodo,
  listUserTodos,
  updateUserTodo,
} from "../api/userTodos";
import type {
  UserTodoFilter,
  UserTodoItem,
  UserTodoPriority,
  UserTodoSort,
  UserTodoStatus,
  UserTodoUpdateInput,
} from "../api/userTodos";
import { toErrorMessage } from "./helpers";

export type UserTodoDraft = {
  title: string;
  description: string;
  priority: UserTodoPriority;
};

export type UserTodoState = {
  hydrated: boolean;
  items: UserTodoItem[];
  total: number;
  statusFilter: UserTodoFilter;
  sort: UserTodoSort;
  query: string;
  draft: UserTodoDraft;
  busy: boolean;
  lastError: string | null;
  load: () => Promise<void>;
  setStatusFilter: (filter: UserTodoFilter) => void;
  setSort: (sort: UserTodoSort) => void;
  setQuery: (query: string) => void;
  setDraft: <K extends keyof UserTodoDraft>(key: K, value: UserTodoDraft[K]) => void;
  resetDraft: () => void;
  create: () => Promise<void>;
  update: (todoId: string, updates: UserTodoUpdateInput) => Promise<void>;
  complete: (todoId: string, done?: boolean) => Promise<void>;
  remove: (todoId: string) => Promise<void>;
  setError: (message: string | null) => void;
};

const emptyDraft: UserTodoDraft = {
  title: "",
  description: "",
  priority: "medium",
};

function replaceItem(items: UserTodoItem[], next: UserTodoItem): UserTodoItem[] {
  return items.map((item) => (item.todoId === next.todoId ? next : item));
}

export const useUserTodoStore = create<UserTodoState>((set, get) => ({
  hydrated: false,
  items: [],
  total: 0,
  statusFilter: "open",
  sort: "created_desc",
  query: "",
  draft: emptyDraft,
  busy: false,
  lastError: null,
  setError: (message) => set({ lastError: message }),
  load: async () => {
    set({ busy: true, lastError: null });
    try {
      const response = await listUserTodos({
        status: get().statusFilter,
        sort: get().sort,
        query: get().query,
        limit: 200,
        offset: 0,
      });
      set({
        hydrated: true,
        items: response.items,
        total: response.total,
      });
    } catch (error) {
      set({ lastError: toErrorMessage(error, "无法加载待办列表。") });
    } finally {
      set({ busy: false });
    }
  },
  setStatusFilter: (statusFilter) => {
    set({ statusFilter });
    void get().load();
  },
  setSort: (sort) => {
    set({ sort });
    void get().load();
  },
  setQuery: (query) => set({ query }),
  setDraft: (key, value) => set({ draft: { ...get().draft, [key]: value } }),
  resetDraft: () => set({ draft: emptyDraft }),
  create: async () => {
    const draft = get().draft;
    if (!draft.title.trim()) {
      set({ lastError: "标题不能为空。" });
      return;
    }
    set({ busy: true, lastError: null });
    try {
      await createUserTodo({
        title: draft.title,
        description: draft.description,
        priority: draft.priority,
      });
      set({ draft: emptyDraft });
      await get().load();
    } catch (error) {
      set({ lastError: toErrorMessage(error, "无法创建待办。") });
    } finally {
      set({ busy: false });
    }
  },
  update: async (todoId, updates) => {
    set({ busy: true, lastError: null });
    try {
      const updated = await updateUserTodo(todoId, updates);
      set({ items: replaceItem(get().items, updated) });
    } catch (error) {
      set({ lastError: toErrorMessage(error, "无法更新待办。") });
    } finally {
      set({ busy: false });
    }
  },
  complete: async (todoId, done = true) => {
    set({ busy: true, lastError: null });
    try {
      const updated = await completeUserTodo(todoId, done);
      if (get().statusFilter === "all") {
        set({ items: replaceItem(get().items, updated) });
      } else {
        await get().load();
      }
    } catch (error) {
      set({ lastError: toErrorMessage(error, "无法更新完成状态。") });
    } finally {
      set({ busy: false });
    }
  },
  remove: async (todoId) => {
    set({ busy: true, lastError: null });
    try {
      await deleteUserTodo(todoId);
      set({
        items: get().items.filter((item) => item.todoId !== todoId),
        total: Math.max(0, get().total - 1),
      });
    } catch (error) {
      set({ lastError: toErrorMessage(error, "无法删除待办。") });
    } finally {
      set({ busy: false });
    }
  },
}));

export type { UserTodoItem, UserTodoPriority, UserTodoStatus };
