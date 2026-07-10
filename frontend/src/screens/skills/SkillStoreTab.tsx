import { Download, Github } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import SearchInput from "../../components/SearchInput";
import { Badge, Button } from "../../components/primitives";
import { useSkillStoreStore } from "../../state/skillStoreStore";
import { SkillStorePreviewDialog } from "./SkillStorePreviewDialog";

export function SkillStoreTab(): JSX.Element {
  const items = useSkillStoreStore((s) => s.items);
  const sourceAvailable = useSkillStoreStore((s) => s.sourceAvailable);
  const sourceMessage = useSkillStoreStore((s) => s.sourceMessage);
  const loading = useSkillStoreStore((s) => s.loading);
  const lastError = useSkillStoreStore((s) => s.lastError);
  const githubSkills = useSkillStoreStore((s) => s.githubSkills);
  const githubMessage = useSkillStoreStore((s) => s.githubMessage);
  const discoveringGithub = useSkillStoreStore((s) => s.discoveringGithub);
  const previewLoading = useSkillStoreStore((s) => s.previewLoading);
  const search = useSkillStoreStore((s) => s.search);
  const loadInstalled = useSkillStoreStore((s) => s.loadInstalled);
  const discoverGithub = useSkillStoreStore((s) => s.discoverGithub);
  const openPreview = useSkillStoreStore((s) => s.openPreview);

  const [queryDraft, setQueryDraft] = useState("");
  const [githubRepo, setGithubRepo] = useState("");
  const debounceRef = useRef<number | null>(null);

  useEffect(() => {
    void search("");
    void loadInstalled();
  }, [search, loadInstalled]);

  const onQueryChange = (value: string) => {
    setQueryDraft(value);
    if (debounceRef.current !== null) {
      window.clearTimeout(debounceRef.current);
    }
    debounceRef.current = window.setTimeout(() => {
      void search(value);
    }, 350);
  };

  return (
    <div className="skill-store-tab">
      <div className="skill-store-toolbar">
        <label className="skills-search">
          <SearchInput
            ariaLabel="搜索技能市场"
            onChange={onQueryChange}
            placeholder="输入关键词搜索技能市场"
            value={queryDraft}
          />
        </label>
      </div>

      {lastError ? <div className="skill-store-error">{lastError}</div> : null}
      {!sourceAvailable ? (
        <div className="skill-store-error">{sourceMessage ?? "技能市场暂时无法访问，请稍后重试。"}</div>
      ) : null}
      {sourceAvailable && sourceMessage ? (
        <div className="skill-store-github-message">{sourceMessage}</div>
      ) : null}
      {loading ? <div className="skills-empty">正在加载技能市场</div> : null}

      <div className="skill-store-list" aria-label="技能市场结果">
        {items.map((item) => (
          <article className="skill-store-card" key={item.sourceRef}>
            <div className="skill-store-card-main">
              <strong>{item.name}</strong>
              <small>{item.source}</small>
            </div>
            <div className="skill-store-card-meta">
              <small>{item.installs.toLocaleString()} 次安装</small>
              {item.installed ? <Badge tone="ok">已安装</Badge> : null}
              <Button
                disabled={previewLoading}
                kind="ghost"
                onClick={() => {
                  void openPreview("skills_sh", item.sourceRef);
                }}
              >
                <Download size={14} />
                <span>查看</span>
              </Button>
            </div>
          </article>
        ))}
        {!loading && sourceAvailable && items.length === 0 ? (
          <div className="skills-empty">{queryDraft.trim() ? "没有匹配的技能" : "输入关键词开始搜索"}</div>
        ) : null}
      </div>

      <div className="skill-store-github">
        <div className="skill-store-github-header">
          <Github size={15} />
          <strong>从 GitHub 安装</strong>
          <small>输入 owner/repo 或仓库链接，直接安装未上架的技能</small>
        </div>
        <div className="skill-store-github-input">
          <input
            aria-label="GitHub 仓库"
            onChange={(event) => setGithubRepo(event.target.value)}
            placeholder="owner/repo"
            value={githubRepo}
          />
          <Button
            disabled={discoveringGithub || !githubRepo.trim()}
            kind="ghost"
            onClick={() => {
              void discoverGithub(githubRepo.trim());
            }}
          >
            {discoveringGithub ? "查找中…" : "查找技能"}
          </Button>
        </div>
        {githubMessage ? <small className="skill-store-github-message">{githubMessage}</small> : null}
        {githubSkills.length > 0 ? (
          <div className="skill-store-list" aria-label="GitHub 发现结果">
            {githubSkills.map((skill) => (
              <article className="skill-store-card" key={skill.sourceRef}>
                <div className="skill-store-card-main">
                  <strong>{skill.name}</strong>
                  <small>{skill.sourceRef}</small>
                </div>
                <div className="skill-store-card-meta">
                  <Badge tone="warn">未经审计</Badge>
                  <Button
                    disabled={previewLoading}
                    kind="ghost"
                    onClick={() => {
                      void openPreview("github", skill.sourceRef);
                    }}
                  >
                    <Download size={14} />
                    <span>查看</span>
                  </Button>
                </div>
              </article>
            ))}
          </div>
        ) : null}
      </div>

      <SkillStorePreviewDialog />
    </div>
  );
}

export default SkillStoreTab;
