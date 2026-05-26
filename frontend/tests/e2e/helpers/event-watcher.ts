export interface PublicUiEvent {
  eventId: string;
  sequence: number;
  sessionId: string;
  type: string;
  scope: Record<string, string>;
  payload: Record<string, unknown>;
  createdAt: string;
}

export interface LastObservableState {
  type: string;
  status?: string;
  stage?: string;
  sequence: number;
}

export class EventWatcher {
  private readonly seen = new Set<string>();
  private readonly events: PublicUiEvent[] = [];
  private lastState: LastObservableState | null = null;
  private blockedForResync = false;

  apply(event: PublicUiEvent): void {
    if (this.seen.has(event.eventId)) return;
    this.seen.add(event.eventId);
    if (event.type === "backend.resync_required") {
      this.blockedForResync = true;
      this.lastState = { type: event.type, sequence: event.sequence };
      return;
    }
    if (this.blockedForResync) return;
    this.events.push(event);
    this.lastState = {
      type: event.type,
      status: typeof event.payload.status === "string" ? event.payload.status : undefined,
      stage: typeof event.payload.stage === "string" ? event.payload.stage : undefined,
      sequence: event.sequence,
    };
  }

  markResynced(): void {
    this.blockedForResync = false;
  }

  get lastObservableState(): LastObservableState | null {
    return this.lastState;
  }

  find(predicate: (event: PublicUiEvent) => boolean): PublicUiEvent | undefined {
    return this.events.find(predicate);
  }
}

export function parseSseEvents(chunk: string): PublicUiEvent[] {
  return chunk
    .split(/\n\n+/)
    .map((frame) => frame.trim())
    .filter(Boolean)
    .map((frame) => {
      const dataLine = frame.split(/\n/).find((line) => line.startsWith("data:"));
      if (!dataLine) return null;
      return JSON.parse(dataLine.slice("data:".length).trim()) as PublicUiEvent;
    })
    .filter((event): event is PublicUiEvent => event !== null);
}

export async function streamPublicUiEvents(
  baseUrl: string,
  token: string,
  watcher: EventWatcher,
  signal: AbortSignal,
): Promise<void> {
  const response = await fetch(`${baseUrl}/api/events`, {
    headers: { "X-Mexemplar-Session": token },
    signal,
  });
  if (!response.ok || !response.body) {
    throw new Error("public_event_stream_unavailable");
  }
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let pending = "";
  while (!signal.aborted) {
    const { done, value } = await reader.read();
    if (done) return;
    pending += value;
    const frames = pending.split("\n\n");
    pending = frames.pop() ?? "";
    for (const frame of frames) {
      for (const event of parseSseEvents(`${frame}\n\n`)) watcher.apply(event);
    }
  }
}

export async function waitForPublicEvent(
  watcher: EventWatcher,
  predicate: (event: PublicUiEvent) => boolean,
  timeoutMs = 30_000,
): Promise<PublicUiEvent> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const event = watcher.find(predicate);
    if (event) return event;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error("public_event_timeout");
}
