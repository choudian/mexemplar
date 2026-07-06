import { X } from "lucide-react";

import { Badge, Button } from "../../components/primitives";
import { useSkillStoreStore } from "../../state/skillStoreStore";
import { SafeMarkdown } from "../assistant/SafeMarkdown";

function formatSize(size: number): string {
  if (size < 1024) return `${size} B`;
  return `${(size / 1024).toFixed(1)} KB`;
}

export function SkillStorePreviewDialog(): JSX.Element | null {
  const preview = useSkillStoreStore((s) => s.preview);
  const installing = useSkillStoreStore((s) => s.installing);
  const install = useSkillStoreStore((s) => s.install);
  const closePreview = useSkillStoreStore((s) => s.closePreview);

  if (!preview) return null;

  const audited = preview.sourceType === "skills_sh" && preview.audit.status === "available";

  return (
    <div className="trial-dialog-overlay" onClick={closePreview} role="presentation">
      <div
        aria-label="技能预览"
        className="trial-dialog skill-store-preview"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
      >
        <header className="skill-store-preview-header">
          <div className="skill-store-preview-title">
            <h3>{preview.name}</h3>
            <a href={preview.sourceUrl} rel="noreferrer" target="_blank">
              {preview.sourceRef}
            </a>
          </div>
          <button aria-label="关闭预览" onClick={closePreview} type="button">
            <X size={16} />
          </button>
        </header>

        {audited ? (
          <div className="skill-store-audit" data-tone="ok">
            <Badge tone="ok">已审计</Badge>
            <span>该技能已通过技能市场安全审计。</span>
          </div>
        ) : preview.sourceType === "github" ? (
          <div className="skill-store-audit" data-tone="warn">
            <Badge tone="warn">未经审计</Badge>
            <span>来自 GitHub 直装，未经技能市场安全审计，请自行确认内容可信。</span>
          </div>
        ) : (
          <div className="skill-store-audit" data-tone="neutral">
            <Badge tone="neutral">审计信息不可用</Badge>
            <span>暂时拿不到该技能的审计结果，安装前请自行确认内容。</span>
          </div>
        )}

        <div className="skill-store-preview-body me-scroll">
          <SafeMarkdown content={preview.skillMd} />
        </div>

        <div className="skill-store-preview-files">
          <strong>附带文件（{preview.files.length}）</strong>
          <ul>
            {preview.files.map((file) => (
              <li key={file.path}>
                <code>{file.path}</code>
                <small>{formatSize(file.size)}</small>
              </li>
            ))}
          </ul>
        </div>

        <footer className="skill-store-preview-actions">
          {!preview.installable && preview.reason ? (
            <span className="skill-store-preview-reason">{preview.reason}</span>
          ) : null}
          {preview.installed ? <Badge tone="ok">已安装</Badge> : null}
          <Button kind="ghost" onClick={closePreview}>
            取消
          </Button>
          <Button
            disabled={installing || !preview.installable || preview.installed}
            kind="primary"
            onClick={() => {
              void install();
            }}
          >
            {installing ? "安装中…" : "安装"}
          </Button>
        </footer>
      </div>
    </div>
  );
}

export default SkillStorePreviewDialog;
