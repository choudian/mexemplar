const ISO_DATETIME_WITHOUT_TIMEZONE =
  /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?$/;

/**
 * 后端持久化时间统一为 UTC，但部分历史 DTO 是不带 offset 的 ISO 字符串。
 * 浏览器会把这种字符串误当本地时间；在 API 展示边界补成 UTC，同时保留显式 offset。
 */
export function parseApiDateTime(value: string | null | undefined): Date | null {
  if (!value) return null;
  const normalized = ISO_DATETIME_WITHOUT_TIMEZONE.test(value) ? `${value}Z` : value;
  const date = new Date(normalized);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatDate(value: string | null): string {
  const date = parseApiDateTime(value);
  if (!date) return "未知时间";
  return date.toLocaleDateString();
}

export function formatDateTime(value: string | null): string {
  const date = parseApiDateTime(value);
  if (!date) return "未知时间";
  return date.toLocaleString();
}

export function formatMonthDayTime(value: string | null): string {
  const date = parseApiDateTime(value);
  if (!date) return "";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}
