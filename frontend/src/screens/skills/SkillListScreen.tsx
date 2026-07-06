import { useEffect, useState } from "react";
import { Plus } from "lucide-react";

import { SKILL_CATEGORIES } from "../../api/skills";
import type { SkillCategory } from "../../api/skills";
import SearchInput from "../../components/SearchInput";
import { Button } from "../../components/primitives";
import { useFiltered } from "../../hooks/useFiltered";
import { useSkillsStore } from "../../state/skillsStore";
import { useShellStore } from "../../state/shellStore";
import SkillCards from "./SkillCards";
import { SkillTrialDialog } from "./SkillTrialDialog";
import { McpServerTab } from "./McpServerTab";
import { SkillStoreTab } from "./SkillStoreTab";

const CATEGORY_LABELS: Record<SkillCategory, string> = {
  pending: "待考核",
  published: "已掌握",
  failed: "失败记录",
};

type SkillTab = SkillCategory | "mcp" | "store";
const SKILL_TABS: SkillTab[] = [...SKILL_CATEGORIES, "mcp" as const, "store" as const];
const TAB_LABELS: Record<SkillTab, string> = {
  ...CATEGORY_LABELS,
  mcp: "MCP 工具",
  store: "技能商店",
};

export function SkillListScreen(): JSX.Element {
  const activeCategory = useSkillsStore((state) => state.activeCategory);
  const data = useSkillsStore((state) => state.categories);
  const counts = useSkillsStore((state) => state.counts);
  const query = useSkillsStore((state) => state.query);
  const busy = useSkillsStore((state) => state.busy);
  const setCategory = useSkillsStore((state) => state.setCategory);
  const setQuery = useSkillsStore((state) => state.setQuery);
  const loadAllCategories = useSkillsStore((state) => state.loadAllCategories);
  const openTrial = useSkillsStore((state) => state.openTrial);
  const deleteSkill = useSkillsStore((state) => state.deleteSkill);
  const retryFailure = useSkillsStore((state) => state.retryFailure);
  const dismissFailure = useSkillsStore((state) => state.dismissFailure);
  const setRoute = useShellStore((state) => state.setRoute);

  const hydrated = useSkillsStore((state) => state.hydrated);
  const [activeTab, setActiveTab] = useState<SkillTab>(activeCategory);

  useEffect(() => {
    if (hydrated) return;
    void loadAllCategories();
  }, [hydrated, loadAllCategories]);

  // 同步 tab 切换到 skillsStore（仅教学工具分类 tab）
  useEffect(() => {
    if (activeTab !== "mcp" && activeTab !== "store") {
      setCategory(activeTab);
    }
  }, [activeTab, setCategory]);

  const filteredSkills = useFiltered(data[activeCategory], query, (skill) => [
    skill.name,
    skill.description,
    skill.errorSummary,
    skill.source,
  ]);

  return (
    <section className="skills-screen" aria-label="工具列表">
      <div className="skills-header">
        <div>
          <h2>工具列表</h2>
          <p>管理所有学习到的工具</p>
        </div>
        <div className="skills-header-actions">
          <label className="skills-search">
            <SearchInput
              ariaLabel="搜索工具"
              onChange={setQuery}
              placeholder="搜索工具"
              value={query}
            />
          </label>
          <Button kind="primary" onClick={() => setRoute("teaching")}>
            <Plus size={15} />
            <span>教学新工具</span>
          </Button>
        </div>
      </div>
      <div className="skills-tabs" role="tablist" aria-label="工具分类">
        {SKILL_TABS.map((id) => {
          const active = activeTab === id;
          return (
            <button
              aria-selected={active}
              className="skills-tab"
              data-active={active}
              key={id}
              onClick={() => setActiveTab(id)}
              role="tab"
              type="button"
            >
              <span>{TAB_LABELS[id]}</span>
              {id !== "mcp" && id !== "store" && <small className="me-mono">{counts[id]}</small>}
            </button>
          );
        })}
      </div>
      {activeTab === "mcp" ? (
        <McpServerTab />
      ) : activeTab === "store" ? (
        <SkillStoreTab />
      ) : (
        <>
          {busy ? <div className="skills-empty">正在加载</div> : null}
          <SkillCards
            category={activeCategory}
            skills={filteredSkills}
            onTrial={(toolId) => {
              openTrial(toolId);
            }}
            onDelete={(toolId) => {
              void deleteSkill(toolId);
            }}
            onRetry={(workflowId) => {
              void retryFailure(workflowId);
            }}
            onDismiss={(workflowId) => {
              void dismissFailure(workflowId);
            }}
          />
        </>
      )}
      <SkillTrialDialog />
    </section>
  );
}

export default SkillListScreen;
