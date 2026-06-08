import { RefreshCcw, RotateCcw, Save, Search, Trash2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import type { BrainEntryStatus, BrainMemoryEntry, BrainZone } from "../../api/brain";
import { Badge, Button, IconButton } from "../../components/primitives";
import { useBrainStore } from "../../state/brainStore";
import EntryEvolution from "./EntryEvolution";

const ZONES = [
  { id: "hot", label: "热区", hint: "近期工作记忆" },
  { id: "persistent", label: "持久区", hint: "稳定身份和偏好" },
  { id: "archive", label: "归档区", hint: "历史事件检索" },
  { id: "subconscious", label: "潜意识区", hint: "风格和价值倾向" },
  { id: "failure", label: "失败区", hint: "避坑经验" },
  { id: "prediction", label: "猜测区", hint: "待校准预测" },
] as const;

const STATUS_OPTIONS = [
  { value: "", label: "全部" },
  { value: "active", label: "活跃" },
  { value: "fading", label: "衰减中" },
  { value: "invalidated", label: "已失效" },
] as const;

function entryCountFor(zone: BrainZone, summaries: ReturnType<typeof useBrainStore.getState>["zones"]): number {
  const summary = summaries.find((item) => item.zone === zone);
  return summary?.entry_count ?? 0;
}

function statusTone(status: BrainEntryStatus) {
  if (status === "active") return "ok";
  if (status === "fading" || status === "invalidated") return "warn";
  if (status === "soft-deleted") return "danger";
  return "neutral";
}

export function BrainScreen(): JSX.Element {
  const zones = useBrainStore((state) => state.zones);
  const entries = useBrainStore((state) => state.entries);
  const activeZone = useBrainStore((state) => state.activeZone) ?? "hot";
  const segments = useBrainStore((state) => state.segments);
  const evolutionChain = useBrainStore((state) => state.evolutionChain);
  const loadingZones = useBrainStore((state) => state.loadingZones);
  const loadingEntries = useBrainStore((state) => state.loadingEntries);
  const loadingSegments = useBrainStore((state) => state.loadingSegments);
  const loadingEvolution = useBrainStore((state) => state.loadingEvolution);
  const loadZones = useBrainStore((state) => state.loadZones);
  const loadEntries = useBrainStore((state) => state.loadEntries);
  const loadSegments = useBrainStore((state) => state.loadSegments);
  const deleteEntry = useBrainStore((state) => state.deleteEntry);
  const editEntry = useBrainStore((state) => state.editEntry);
  const retrySegment = useBrainStore((state) => state.retrySegment);
  const loadEvolution = useBrainStore((state) => state.loadEvolution);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<BrainEntryStatus | "">("");
  const [contentDraft, setContentDraft] = useState("");
  const [scopeDraft, setScopeDraft] = useState("");

  useEffect(() => {
    void loadZones();
    void loadSegments();
    void loadEntries("hot");
  }, [loadEntries, loadSegments, loadZones]);

  const lastEvolutionIdRef = useRef<string | null>(null);

  useEffect(() => {
    if (selectedId) {
      const stillExists = entries.some((entry) => entry.entry_id === selectedId);
      if (stillExists) return;
    }
    if (!selectedId) {
      const auto = entries[0] ?? null;
      if (!auto) {
        setContentDraft("");
        setScopeDraft("");
        lastEvolutionIdRef.current = null;
        return;
      }
      setSelectedId(auto.entry_id);
      setContentDraft(auto.content);
      setScopeDraft(auto.scope ?? "");
      if (lastEvolutionIdRef.current !== auto.entry_id) {
        lastEvolutionIdRef.current = auto.entry_id;
        void loadEvolution(auto.entry_id);
      }
      return;
    }
    setSelectedId(null);
    setContentDraft("");
    setScopeDraft("");
    lastEvolutionIdRef.current = null;
  }, [entries, loadEvolution, selectedId]);

  const selectedEntry = entries.find((entry) => entry.entry_id === selectedId) ?? null;
  const filteredEntries = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return entries;
    return entries.filter((entry) =>
      [entry.content, entry.reason, entry.scope ?? "", entry.entry_type ?? ""]
        .some((value) => value.toLowerCase().includes(needle)),
    );
  }, [entries, query]);

  const chooseZone = (zone: BrainZone) => {
    setSelectedId(null);
    void loadEntries(zone, { status: status || undefined });
  };

  const chooseStatus = (nextStatus: BrainEntryStatus | "") => {
    setStatus(nextStatus);
    void loadEntries(activeZone, { status: nextStatus || undefined });
  };

  const saveSelected = () => {
    if (!selectedEntry) return;
    void editEntry(selectedEntry.entry_id, contentDraft, scopeDraft || undefined);
  };

  return (
    <section className="brain-screen" aria-label="大脑管理">
      <header className="brain-header">
        <div>
          <h2>大脑管理</h2>
          <p>查看、修正和追溯助理的六个认知分区</p>
        </div>
        <Button kind="secondary" onClick={() => {
          void loadZones();
          void loadEntries(activeZone, { status: status || undefined });
          void loadSegments();
        }}>
          <RefreshCcw size={14} />
          刷新
        </Button>
      </header>

      <div className="brain-workspace">
        <aside className="brain-zone-rail" aria-label="大脑分区">
          {ZONES.map((zone) => {
            const active = zone.id === activeZone;
            return (
              <button
                aria-pressed={active}
                className="brain-zone-button"
                data-active={active}
                key={zone.id}
                onClick={() => chooseZone(zone.id)}
                type="button"
              >
                <span>
                  <strong>{zone.label}</strong>
                  <small>{zone.hint}</small>
                </span>
                <span className="me-badge">{entryCountFor(zone.id, zones)}</span>
              </button>
            );
          })}
          {loadingZones ? <div className="brain-empty">正在刷新分区</div> : null}
        </aside>

        <main className="brain-entry-pane">
          <div className="brain-toolbar">
            <label className="brain-search">
              <Search size={14} />
              <input
                aria-label="搜索大脑条目"
                onChange={(event) => setQuery(event.currentTarget.value)}
                placeholder="搜索内容、理由或范围"
                value={query}
              />
            </label>
            <select
              aria-label="筛选条目状态"
              onChange={(event) => chooseStatus(event.currentTarget.value as BrainEntryStatus | "")}
              value={status}
            >
              {STATUS_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </select>
          </div>

          <div className="brain-entry-list me-scroll" aria-label="分区条目">
            {loadingEntries ? <div className="brain-empty">正在加载条目</div> : null}
            {filteredEntries.map((entry) => (
              <EntryRow
                entry={entry}
                key={entry.entry_id}
                onDelete={() => {
                  void deleteEntry(entry.entry_id);
                }}
                onSelect={() => {
                  setSelectedId(entry.entry_id);
                  setContentDraft(entry.content);
                  setScopeDraft(entry.scope ?? "");
                  lastEvolutionIdRef.current = entry.entry_id;
                  void loadEvolution(entry.entry_id);
                }}
                selected={entry.entry_id === selectedId}
              />
            ))}
            {!loadingEntries && filteredEntries.length === 0 ? <div className="brain-empty">暂无条目</div> : null}
          </div>
        </main>

        <aside className="brain-detail-pane me-scroll" aria-label="条目详情">
          {selectedEntry ? (
            <section className="brain-editor">
              <div className="brain-section-title">
                <span>条目详情</span>
                <Badge tone={statusTone(selectedEntry.status)}>{selectedEntry.status}</Badge>
              </div>
              <label>
                <span>内容</span>
                <textarea
                  aria-label="编辑条目内容"
                  onChange={(event) => setContentDraft(event.currentTarget.value)}
                  value={contentDraft}
                />
              </label>
              <label>
                <span>适用范围</span>
                <input
                  aria-label="编辑适用范围"
                  onChange={(event) => setScopeDraft(event.currentTarget.value)}
                  value={scopeDraft}
                />
              </label>
              <div className="brain-reason">
                <strong>形成原因</strong>
                <p>{selectedEntry.reason || "无记录"}</p>
              </div>
              {selectedEntry.verification_status ? (
                <div className="brain-reason">
                  <strong>校准状态</strong>
                  <p>{selectedEntry.verification_status} · {selectedEntry.verification_rationale || "无说明"}</p>
                </div>
              ) : null}
              <div className="brain-editor-actions">
                <Button kind="primary" onClick={saveSelected}>
                  <Save size={14} />
                  保存
                </Button>
                <Button kind="danger" onClick={() => {
                  void deleteEntry(selectedEntry.entry_id);
                }}>
                  <Trash2 size={14} />
                  删除
                </Button>
              </div>
            </section>
          ) : (
            <div className="brain-empty">选择一个条目查看详情</div>
          )}
          <EntryEvolution chain={evolutionChain} loading={loadingEvolution} />
          <SegmentPanel loading={loadingSegments} segments={segments} onRetry={(segmentId) => {
            void retrySegment(segmentId);
          }} />
        </aside>
      </div>
    </section>
  );
}

function EntryRow({
  entry,
  selected,
  onSelect,
  onDelete,
}: {
  entry: BrainMemoryEntry;
  selected: boolean;
  onSelect: () => void;
  onDelete: () => void;
}) {
  return (
    <article className="brain-entry-row" data-selected={selected}>
      <button onClick={onSelect} type="button">
        <span className="brain-entry-title">{entry.content}</span>
        <span className="brain-entry-meta">
          <Badge tone={statusTone(entry.status)}>{entry.status}</Badge>
          {entry.entry_type ? <small>{entry.entry_type}</small> : null}
          {entry.scope ? <small>{entry.scope}</small> : null}
        </span>
        <small>{entry.reason || "无形成原因"}</small>
      </button>
      <IconButton label="删除条目" onClick={onDelete}>
        <Trash2 size={14} />
      </IconButton>
    </article>
  );
}

function SegmentPanel({
  segments,
  loading,
  onRetry,
}: {
  segments: ReturnType<typeof useBrainStore.getState>["segments"];
  loading: boolean;
  onRetry: (segmentId: string) => void;
}) {
  return (
    <section className="brain-segments" aria-label="Segment 列表">
      <div className="brain-section-title">
        <span>Segment</span>
        <small>{segments.length} 条</small>
      </div>
      {loading ? <div className="brain-empty">正在加载 Segment</div> : null}
      {segments.slice(0, 6).map((segment) => (
        <div className="brain-segment-row" key={segment.segment_id}>
          <div>
            <strong>{segment.boundary_reason || "边界"}</strong>
            <small>{segment.status} · retry {segment.retry_count}</small>
          </div>
          {segment.status === "failed" ? (
            <IconButton label="重试 Segment" onClick={() => onRetry(segment.segment_id)}>
              <RotateCcw size={14} />
            </IconButton>
          ) : null}
        </div>
      ))}
      {!loading && segments.length === 0 ? <div className="brain-empty">暂无 Segment</div> : null}
    </section>
  );
}

export default BrainScreen;
