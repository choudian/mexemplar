import { useEffect } from "react";
import { Plus, Search } from "lucide-react";

import type { SkillCategory } from "../../api/skills";
import { Button } from "../../components/primitives";
import { useSkillsStore } from "../../state/skillsStore";
import { useShellStore } from "../../state/shellStore";
import SkillCards from "./SkillCards";

const categories: { id: SkillCategory; label: string }[] = [
  { id: "pending", label: "待考核" },
  { id: "published", label: "已掌握" },
  { id: "failed", label: "失败记录" },
];

export function SkillListScreen(): JSX.Element {
  const activeCategory = useSkillsStore((state) => state.activeCategory);
  const data = useSkillsStore((state) => state.categories);
  const query = useSkillsStore((state) => state.query);
  const busy = useSkillsStore((state) => state.busy);
  const lastError = useSkillsStore((state) => state.lastError);
  const setCategory = useSkillsStore((state) => state.setCategory);
  const setQuery = useSkillsStore((state) => state.setQuery);
  const loadCategory = useSkillsStore((state) => state.loadCategory);
  const runTrial = useSkillsStore((state) => state.runTrial);
  const deleteSkill = useSkillsStore((state) => state.deleteSkill);
  const retryFailure = useSkillsStore((state) => state.retryFailure);
  const dismissFailure = useSkillsStore((state) => state.dismissFailure);
  const setRoute = useShellStore((state) => state.setRoute);

  useEffect(() => {
    void loadCategory(activeCategory);
  }, [activeCategory, loadCategory]);

  const filteredSkills = data[activeCategory].filter((skill) => {
    const needle = query.trim().toLowerCase();
    if (!needle) return true;
    return [skill.name, skill.description, skill.errorSummary, skill.source]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(needle));
  });

  return (
    <section className="skills-screen" aria-label="技能列表">
      <div className="skills-header">
        <div>
          <h2>技能列表</h2>
          <p>管理所有学习到的技能</p>
        </div>
        <div className="skills-header-actions">
          <label className="skills-search">
            <Search size={14} />
            <input
              aria-label="搜索技能"
              placeholder="搜索技能"
              value={query}
              onChange={(event) => setQuery(event.currentTarget.value)}
            />
          </label>
          <Button kind="primary" onClick={() => setRoute("teaching")}>
            <Plus size={15} />
            <span>教学新技能</span>
          </Button>
        </div>
      </div>
      <div className="skills-tabs" role="tablist" aria-label="技能分类">
        {categories.map((category) => {
          const active = activeCategory === category.id;
          return (
            <button
              aria-selected={active}
              className="skills-tab"
              data-active={active}
              key={category.id}
              onClick={() => setCategory(category.id)}
              role="tab"
              type="button"
            >
              <span>{category.label}</span>
              <small className="me-mono">{data[category.id].length}</small>
            </button>
          );
        })}
      </div>
      {busy ? <div className="skills-empty">正在加载</div> : null}
      <SkillCards
        category={activeCategory}
        skills={filteredSkills}
        onTrial={(toolId) => {
          void runTrial(toolId);
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
      {lastError ? <div className="skills-error">{lastError}</div> : null}
    </section>
  );
}

export default SkillListScreen;
