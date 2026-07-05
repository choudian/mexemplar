import { useState, useEffect } from "react";
import { Plus, Plug } from "lucide-react";

import { useMcpStore } from "../../state/mcpStore";
import { Button, Badge } from "../../components/primitives";
import { McpServerCard } from "./McpServerCard";
import { McpServerDialog } from "./McpServerDialog";
import type { McpServerResponse } from "../../api/mcpServers";

// ── Preset quick-enable cards (empty state) ─────────────────────────

interface PresetQuickCard {
  slug: string;
  name: string;
  description: string;
  needsCredential: boolean;
}

const PRESET_QUICK_CARDS: PresetQuickCard[] = [
  {
    slug: "filesystem",
    name: "文件系统",
    description: "文件系统操作（读取/写入/搜索文件）",
    needsCredential: false,
  },
  {
    slug: "github",
    name: "GitHub",
    description: "GitHub 操作（PR/Issue/搜索等），需要 API token",
    needsCredential: true,
  },
];

// ── Component ───────────────────────────────────────────────────────

export function McpServerTab(): JSX.Element {
  const servers = useMcpStore((s) => s.servers);
  const hydrated = useMcpStore((s) => s.hydrated);
  const loading = useMcpStore((s) => s.loading);
  const lastError = useMcpStore((s) => s.lastError);
  const load = useMcpStore((s) => s.load);
  const addServer = useMcpStore((s) => s.addServer);
  const enableServer = useMcpStore((s) => s.enableServer);
  const clearImportPreview = useMcpStore((s) => s.clearImportPreview);
  const clearTestResult = useMcpStore((s) => s.clearTestResult);
  const setError = useMcpStore((s) => s.setError);

  const [dialogOpen, setDialogOpen] = useState(false);
  const [editingServer, setEditingServer] =
    useState<McpServerResponse | null>(null);

  useEffect(() => {
    if (!hydrated) void load();
  }, [hydrated, load]);

  // Clean up store state when dialog closes
  const handleCloseDialog = (): void => {
    setDialogOpen(false);
    setEditingServer(null);
    clearImportPreview();
    clearTestResult();
    setError(null);
  };

  const handleOpenCreate = (): void => {
    setEditingServer(null);
    setDialogOpen(true);
  };

  const handleOpenEdit = (server: McpServerResponse): void => {
    setEditingServer(server);
    setDialogOpen(true);
  };

  // Quick-enable a preset server (one-click for no-credential presets)
  // 优先使用后端 seed 创建的预设记录（已含平台正确的 command），
  // 回退到 addServer（但此时 command 可能不含 Windows cmd /c 包装）。
  const handleQuickEnable = (preset: PresetQuickCard): void => {
    if (preset.needsCredential) {
      // Open dialog pre-filled with preset
      setEditingServer(null);
      setDialogOpen(true);
      return;
    }
    // 查找后端 seed 的预设 server（presetSlug 匹配且 disabled）
    const existing = servers.find(
      (s) => s.presetSlug === preset.slug && !s.enabled,
    );
    if (existing) {
      void enableServer(existing.serverId);
    } else {
      // 兜底：手动 add（注意 command 可能需要平台适配）
      void addServer({
        name: preset.name,
        transport: "stdio",
        command: "npx",
        args: ["-y", `@modelcontextprotocol/server-${preset.slug}`],
        presetSlug: preset.slug,
      });
    }
  };

  // ── Empty state ─────────────────────────────────────────────────

  if (servers.length === 0 && !loading) {
    return (
      <section className="mcp-server-tab" aria-label="MCP 工具">
        <div className="mcp-empty">
          <div className="mcp-empty-header">
            <Plug size={32} />
            <h3>添加 MCP 服务器</h3>
          </div>
          <p>
            添加 MCP server 后，AI 助手可以自动使用这些工具完成任务
          </p>

          <div className="mcp-preset-quick-grid">
            {PRESET_QUICK_CARDS.map((preset) => (
              <button
                key={preset.slug}
                type="button"
                className="mcp-preset-quick-card"
                onClick={() => handleQuickEnable(preset)}
              >
                <div className="mcp-preset-quick-top">
                  <strong>{preset.name}</strong>
                  <Badge tone="ok">AI 可直接调用</Badge>
                </div>
                <p>{preset.description}</p>
                <div className="mcp-preset-quick-footer">
                  {preset.needsCredential ? (
                    <span className="mcp-env-warning">需要配置 Token</span>
                  ) : (
                    <span className="mcp-env-ok">一键启用</span>
                  )}
                </div>
              </button>
            ))}
          </div>

          <div className="mcp-empty-actions">
            <Button kind="primary" onClick={handleOpenCreate}>
              <Plus size={15} />
              <span>添加 MCP 服务器</span>
            </Button>
          </div>
        </div>

        {dialogOpen && (
          <McpServerDialog
            server={editingServer}
            onClose={handleCloseDialog}
          />
        )}
      </section>
    );
  }

  // ── Server list ─────────────────────────────────────────────────

  return (
    <section className="mcp-server-tab" aria-label="MCP 工具">
      {lastError ? (
        <div className="mcp-tab-error">{lastError}</div>
      ) : null}

      {loading && !hydrated ? (
        <div className="mcp-loading">正在加载</div>
      ) : (
        <>
          <div className="mcp-server-grid me-scroll">
            {servers.map((server) => (
              <McpServerCard
                key={server.serverId}
                server={server}
                onEdit={() => handleOpenEdit(server)}
              />
            ))}
          </div>

          <div className="mcp-add-button">
            <Button kind="secondary" onClick={handleOpenCreate}>
              <Plus size={15} />
              <span>添加 MCP 服务器</span>
            </Button>
          </div>
        </>
      )}

      {dialogOpen && (
        <McpServerDialog
          server={editingServer}
          onClose={handleCloseDialog}
        />
      )}
    </section>
  );
}

export default McpServerTab;
