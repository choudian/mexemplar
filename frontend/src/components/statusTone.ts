export type BadgeTone = "neutral" | "ok" | "warn" | "danger";

export function statusToTone<TStatus extends string>(
  status: TStatus | null | undefined,
  tones: Partial<Record<TStatus, BadgeTone>>,
  fallback: BadgeTone = "neutral",
): BadgeTone {
  return status ? tones[status] ?? fallback : fallback;
}
