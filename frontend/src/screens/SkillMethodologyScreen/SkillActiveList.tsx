import { PanelLeftClose, PanelLeftOpen, SlidersHorizontal } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import type { SkillFilterKey, SkillSortKey, SkillMethodologySummary } from "../../api/skillsMethodology";
import SearchInput from "../../components/SearchInput";
import { IconButton } from "../../components/primitives";
import SkillCard from "../../components/SkillCard";
import { parseApiDateTime } from "../../utils/dates";

const SORT_LABELS: Record<SkillSortKey, string> = {
  recently_changed: "最近变更",
  loaded_count: "加载次数",
  referenced_count: "引用次数",
  equipped_count: "装备者",
};

const FILTER_LABELS: Record<SkillFilterKey, string> = {
  all: "全部",
  never_referenced: "从未引用",
  not_referenced_30d: "30 天未引用",
};

function timestamp(value: string | null): number {
  return parseApiDateTime(value)?.getTime() ?? 0;
}

function isNotReferenced30d(skill: SkillMethodologySummary): boolean {
  if (!skill.last_referenced_at) return true;
  return Date.now() - timestamp(skill.last_referenced_at) > 30 * 24 * 60 * 60 * 1000;
}

function sortValue(skill: SkillMethodologySummary, sortKey: SkillSortKey): number {
  if (sortKey === "recently_changed") return timestamp(skill.created_at);
  if (sortKey === "loaded_count") return skill.loaded_count;
  if (sortKey === "referenced_count") return skill.referenced_count;
  return skill.equipped_count;
}

function SortFilterChip({
  sortKey,
  filterKey,
  onSort,
  onFilter,
}: {
  sortKey: SkillSortKey;
  filterKey: SkillFilterKey;
  onSort: (key: SkillSortKey) => void;
  onFilter: (key: SkillFilterKey) => void;
}): JSX.Element {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const hasFilter = filterKey !== "all";
  const hasNonDefaultSort = sortKey !== "recently_changed";
  const isActive = hasFilter || hasNonDefaultSort;

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const chipLabel = filterKey === "all"
    ? SORT_LABELS[sortKey]
    : `${SORT_LABELS[sortKey]} · ${FILTER_LABELS[filterKey]}`;

  return (
    <div className="methodology-sort-filter" ref={ref}>
      <button
        aria-expanded={open}
        className="methodology-sort-filter-chip"
        data-active={isActive}
        onClick={() => setOpen((v) => !v)}
        type="button"
      >
        <SlidersHorizontal size={12} />
        <span>{chipLabel}</span>
        {isActive ? <i className="methodology-filter-dot" /> : null}
      </button>

      {open ? (
        <div className="methodology-sort-filter-popover" role="dialog" aria-label="排序与筛选">
          <div className="methodology-popover-section">
            <span className="methodology-popover-label">排序</span>
            {(Object.keys(SORT_LABELS) as SkillSortKey[]).map((key) => (
              <button
                data-active={sortKey === key}
                key={key}
                onClick={() => onSort(key)}
                type="button"
              >
                {SORT_LABELS[key]}
              </button>
            ))}
          </div>
          <div className="methodology-popover-divider" />
          <div className="methodology-popover-section">
            <span className="methodology-popover-label">筛选</span>
            {(Object.keys(FILTER_LABELS) as SkillFilterKey[]).map((key) => (
              <button
                data-active={filterKey === key}
                key={key}
                onClick={() => onFilter(key)}
                type="button"
              >
                {FILTER_LABELS[key]}
              </button>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}

export function SkillActiveList({
  items,
  selectedSkillId,
  sortKey,
  filterKey,
  collapsed,
  onSort,
  onFilter,
  onOpen,
  onToggleCollapsed,
}: {
  items: SkillMethodologySummary[];
  selectedSkillId: string | null;
  sortKey: SkillSortKey;
  filterKey: SkillFilterKey;
  collapsed: boolean;
  onSort: (sortKey: SkillSortKey) => void;
  onFilter: (filterKey: SkillFilterKey) => void;
  onOpen: (skillId: string) => void;
  onToggleCollapsed: () => void;
}): JSX.Element {
  const [query, setQuery] = useState("");
  const visibleItems = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return items
      .filter((skill) => {
        if (filterKey === "never_referenced" && skill.referenced_count !== 0) return false;
        if (filterKey === "not_referenced_30d" && !isNotReferenced30d(skill)) return false;
        if (!needle) return true;
        return [skill.name, skill.description, skill.skill_id, ...skill.trigger_conditions]
          .some((value) => value.toLowerCase().includes(needle));
      })
      .sort((a, b) => sortValue(b, sortKey) - sortValue(a, sortKey));
  }, [filterKey, items, query, sortKey]);

  if (collapsed) {
    return (
      <section className="methodology-list-pane" aria-label="方法论列表" data-collapsed="true">
        <IconButton label="展开列表" onClick={onToggleCollapsed}>
          <PanelLeftOpen size={15} />
        </IconButton>
      </section>
    );
  }

  return (
    <section className="methodology-list-pane" aria-label="方法论列表">
      <div className="methodology-list-header">
        <span className="methodology-list-title">方法论列表</span>
        <IconButton label="折叠列表" onClick={onToggleCollapsed}>
          <PanelLeftClose size={15} />
        </IconButton>
      </div>
      <label className="methodology-search">
        <SearchInput
          ariaLabel="搜索方法论"
          onChange={setQuery}
          placeholder="搜索方法论"
          value={query}
        />
      </label>
      <SortFilterChip
        filterKey={filterKey}
        onFilter={onFilter}
        onSort={onSort}
        sortKey={sortKey}
      />
      <div className="methodology-card-grid me-scroll">
        {visibleItems.map((skill) => (
          <SkillCard
            key={skill.skill_id}
            onOpen={() => onOpen(skill.skill_id)}
            selected={selectedSkillId === skill.skill_id}
            skill={skill}
          />
        ))}
        {visibleItems.length === 0 ? <div className="brain-empty">暂无匹配方法论</div> : null}
      </div>
    </section>
  );
}

export default SkillActiveList;
