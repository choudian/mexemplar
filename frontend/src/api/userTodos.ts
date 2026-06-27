import { requestJson } from "./client";

export type UserTodoStatus = "pending" | "in_progress" | "done";
export type UserTodoPriority = "low" | "medium" | "high" | "urgent";
export type UserTodoFilter = "all" | "open" | "done";
export type UserTodoSort = "created_desc" | "created_asc" | "priority_desc" | "priority_asc";

export interface UserTodoItem {
  todoId: string;
  title: string;
  description: string;
  status: UserTodoStatus;
  priority: UserTodoPriority;
  sortOrder: number;
  createdAt: string | null;
  updatedAt: string | null;
  completedAt: string | null;
}

export interface UserTodoListResponse {
  items: UserTodoItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface UserTodoCreateInput {
  title: string;
  description?: string;
  priority?: UserTodoPriority;
}

export type UserTodoUpdateInput = Partial<{
  title: string;
  description: string;
  status: UserTodoStatus;
  priority: UserTodoPriority;
}>;

export interface UserTodoListParams {
  status?: UserTodoFilter;
  sort?: UserTodoSort;
  query?: string;
  limit?: number;
  offset?: number;
}

export function listUserTodos(params: UserTodoListParams = {}): Promise<UserTodoListResponse> {
  const query = new URLSearchParams();
  query.set("status", params.status ?? "all");
  query.set("sort", params.sort ?? "created_desc");
  query.set("limit", String(params.limit ?? 100));
  query.set("offset", String(params.offset ?? 0));
  if (params.query?.trim()) {
    query.set("query", params.query.trim());
  }
  return requestJson<UserTodoListResponse>(`/api/user-todos?${query}`);
}

export function createUserTodo(input: UserTodoCreateInput): Promise<UserTodoItem> {
  return requestJson<UserTodoItem>("/api/user-todos", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function updateUserTodo(todoId: string, input: UserTodoUpdateInput): Promise<UserTodoItem> {
  return requestJson<UserTodoItem>(`/api/user-todos/${encodeURIComponent(todoId)}`, {
    method: "PUT",
    body: JSON.stringify(input),
  });
}

export function completeUserTodo(todoId: string, done = true): Promise<UserTodoItem> {
  return requestJson<UserTodoItem>(`/api/user-todos/${encodeURIComponent(todoId)}/complete`, {
    method: "POST",
    body: JSON.stringify({ done }),
  });
}

export async function deleteUserTodo(todoId: string): Promise<void> {
  await requestJson<void>(`/api/user-todos/${encodeURIComponent(todoId)}`, {
    method: "DELETE",
  });
}
