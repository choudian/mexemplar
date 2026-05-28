import { describe, expect, test } from "vitest";

import { EventWatcher, parseSseEvents } from "../e2e/helpers/event-watcher";

const event = (eventId: string, sequence: number, type: string, payload = {}) => ({
  eventId,
  sequence,
  sessionId: "ui_sess",
  type,
  scope: {},
  payload,
  createdAt: "2026-05-24T00:00:00Z",
});

describe("real Grand Tour event watcher", () => {
  test("deduplicates events and tracks last observable public state", () => {
    const watcher = new EventWatcher();
    const progress = event("evt_1", 1, "assistant.progress", { status: "running" });

    watcher.apply(progress);
    watcher.apply(progress);

    expect(watcher.find((candidate) => candidate.eventId === "evt_1")).toBe(progress);
    expect(watcher.lastObservableState).toEqual({
      type: "assistant.progress",
      status: "running",
      stage: undefined,
      sequence: 1,
    });
  });

  test("blocks incremental events during resync until caller marks resynced", () => {
    const watcher = new EventWatcher();

    watcher.apply(event("evt_resync", 1, "backend.resync_required", { reason: "replay_gap" }));
    watcher.apply(event("evt_ignored", 2, "teaching.stage_changed", { stage: "published" }));
    expect(watcher.find((candidate) => candidate.eventId === "evt_resync")).toMatchObject({
      type: "backend.resync_required",
    });
    expect(watcher.find((candidate) => candidate.eventId === "evt_ignored")).toBeUndefined();

    watcher.markResynced();
    watcher.apply(event("evt_after", 3, "teaching.stage_changed", { stage: "published" }));

    expect(watcher.lastObservableState).toMatchObject({
      type: "teaching.stage_changed",
      stage: "published",
      sequence: 3,
    });
  });

  test("parses server-sent event frames", () => {
    const parsed = parseSseEvents(
      `id: 1\nevent: assistant.progress\ndata: ${JSON.stringify(event("evt_1", 1, "assistant.progress", { status: "running" }))}\n\n`,
    );

    expect(parsed).toHaveLength(1);
    expect(parsed[0].type).toBe("assistant.progress");
  });
});
