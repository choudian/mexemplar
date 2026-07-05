import { useEffect, useState } from "react";
import {
  CheckCircle2,
  XCircle,
  WifiOff,
  PowerOff,
  Loader2,
  AlertCircle,
  RefreshCw,
  Pencil,
  Trash2,
  Plug,
} from "lucide-react";

import type { McpServerResponse } from "../../api/mcpServers";
import { Badge, Button, IconButton, Toggle } from "../../components/primitives";
import { useMcpStore } from "../../state/mcpStore";

// ── Error translation ───────────────────────────────────────────────

function translateError(
  lastError: string | null,
  suggestion: string | null,
): string | null {
  if (suggestion) return suggestion;
  if (!lastError) return null;

  const lower = lastError.toLowerCase();

  if (
    lower.includes("npx") &&
    (lower.includes("not found") || lower.includes("enoent"))
  ) {
    return "找不到 npx 命令，请确认已安装 Node.js";
  }
  if (
    lower.includes("econnrefused") ||
    lower.includes("timeout") ||
    lower.includes("etimedout")
  ) {
    return "无法连接到服务器，请检查网络或服务器地址";
  }
  if (
    lower.includes("auth") ||
    lower.includes("401") ||
    lower.includes("403") ||
    lower.includes("unauthorized")
  ) {
    return "认证失败，请检查 API Key 或 Token 是否正确";
  }
  if (lower.includes("spawn") || lower.includes("child_process")) {
    return "无法启动服务器进程，请检查命令路径是否正确";
  }
  return "连接失败，请检查配置后重试";
}

// ── Status indicator ────────────────────────────────────────────────

function StatusIndicator({ status }: { status: string | null }): JSX.Element {
  switch (status) {
    case "running":
      return (
        <span className="mcp-status mcp-status-running">
          <CheckCircle2 size={14} />
          运行中
        </span>
      );
    case "failed":
      return (
        <span className="mcp-status mcp-status-failed">
          <XCircle size={14} />
          连接失败
        </span>
      );
    case "disconnected":
      return (
        <span className="mcp-status mcp-status-disconnected">
          <WifiOff size={14} />
          已断开
        </span>
      );
    case "stopped":
      return (
        <span className="mcp-status mcp-status-stopped">
          <PowerOff size={14} />
          已停止
        </span>
      );
    case "starting":
      return (
        <span className="mcp-status mcp-status-starting">
          <Loader2 size={14} className="mcp-spin" />
          启动中
        </span>
      );
    default:
      return (
        <span className="mcp-status mcp-status-unknown">
          <AlertCircle size={14} />
          未知状态
        </span>
      );
  }
}

// ── One-time tooltip ─────────────────────────────────────────────────

const TOOLTIP_TEXT =
  "工具较多，AI 会在需要时搜索发现。如未触发，可在对话中提到 server 名称";

function useOneTimeTooltip(
  serverId: string,
  isPreset: boolean,
): [boolean, () => void] {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (isPreset) return;
    const key = `mcp-tooltip-shown:${serverId}`;
    if (localStorage.getItem(key) === "1") return;
    setVisible(true);
    const timer = setTimeout(() => {
      setVisible(false);
      localStorage.setItem(key, "1");
    }, 5000);
    return () => {
      clearTimeout(timer);
    };
  }, [serverId, isPreset]);

  if (isPreset) return [false, () => {}];
  const key = `mcp-tooltip-shown:${serverId}`;
  const shouldShow = visible && localStorage.getItem(key) !== "1";
  const dismiss = (): void => {
    localStorage.setItem(key, "1");
    setVisible(false);
  };
  return [shouldShow, dismiss];
}

// ── Props ───────────────────────────────────────────────────────────

interface McpServerCardProps {
  server: McpServerResponse;
  onEdit: () => void;
}

// ── Component ───────────────────────────────────────────────────────

export function McpServerCard({
  server,
  onEdit,
}: McpServerCardProps): JSX.Element {
  const enableServer = useMcpStore((s) => s.enableServer);
  const disableServer = useMcpStore((s) => s.disableServer);
  const reconnectServer = useMcpStore((s) => s.reconnectServer);
  const deleteServer = useMcpStore((s) => s.deleteServer);

  const isRunning = server.status === "running";
  const isFailed = server.status === "failed";
  const isDisconnected = server.status === "disconnected";
  const isStarting = server.status === "starting";
  const isPreset = server.presetSlug !== null;
  const showToolCount = isRunning || isFailed;
  const userError = translateError(server.lastError, server.suggestion);
  const hasMissingEnv = server.envMissingKeys.length > 0;
  const isInUse = isRunning && server.toolCount !== null && server.toolCount > 0;

  const [confirmDelete, setConfirmDelete] = useState(false);
  const [showTooltip, dismissTooltip] = useOneTimeTooltip(
    server.serverId,
    isPreset,
  );

  const handleToggle = (): void => {
    if (server.enabled) {
      void disableServer(server.serverId);
    } else {
      void enableServer(server.serverId);
    }
  };

  const handleReconnect = (): void => {
    void reconnectServer(server.serverId);
  };

  const handleDeleteClick = (): void => {
    if (isInUse && !confirmDelete) {
      setConfirmDelete(true);
      return;
    }
    void deleteServer(server.serverId);
  };

  const handleCancelDelete = (): void => {
    setConfirmDelete(false);
  };

  return (
    <article
      className="mcp-server-card"
      data-status={server.status ?? "unknown"}
    >
      <div className="mcp-server-card-top">
        <div className="mcp-server-icon">
          <Plug size={18} />
        </div>
        <div className="mcp-server-info">
          <div className="mcp-server-title-row">
            <h3>{server.name}</h3>
            {isPreset ? (
              <Badge tone="ok">AI 可直接调用</Badge>
            ) : (
              <span className="mcp-badge-wrapper">
                <span className="me-badge mcp-badge-discovery">
                  AI 通过 search 按需发现
                </span>
                {showTooltip ? (
                  <span
                    className="mcp-tooltip"
                    role="tooltip"
                    onClick={dismissTooltip}
                  >
                    {TOOLTIP_TEXT}
                  </span>
                ) : null}
              </span>
            )}
          </div>
          <div className="mcp-server-meta">
            <StatusIndicator status={server.status} />
            {showToolCount && server.toolCount !== null ? (
              <span className="mcp-tool-count me-mono">
                {server.toolCount} 个工具
              </span>
            ) : null}
            {hasMissingEnv ? (
              <span className="mcp-env-warning">有未填写的环境变量</span>
            ) : null}
          </div>
        </div>
      </div>

      {userError ? (
        <div className="mcp-server-error">
          <AlertCircle size={14} />
          <span>{userError}</span>
        </div>
      ) : null}

      {server.circuitBreakerOpen ? (
        <div className="mcp-server-warning">
          多次连接失败，已暂停自动重连。请检查配置后手动重连。
        </div>
      ) : null}

      {confirmDelete ? (
        <div className="mcp-delete-confirm">
          <span>
            删除后 AI 将无法使用此 server 的 {server.toolCount} 个工具
          </span>
          <div className="mcp-delete-confirm-actions">
            <Button kind="danger" onClick={handleDeleteClick}>
              <Trash2 size={14} />
              <span>确认删除</span>
            </Button>
            <Button kind="ghost" onClick={handleCancelDelete}>
              取消
            </Button>
          </div>
        </div>
      ) : (
        <div className="mcp-server-card-footer">
          <div className="mcp-server-actions-left">
            <Toggle
              label={server.enabled ? "禁用" : "启用"}
              pressed={server.enabled}
              onPressedChange={handleToggle}
              disabled={isStarting}
            />
            {(isDisconnected || isFailed) && !isStarting ? (
              <Button kind="secondary" onClick={handleReconnect}>
                <RefreshCw size={14} />
                <span>重连</span>
              </Button>
            ) : null}
          </div>
          <div className="mcp-server-actions-right">
            <IconButton label="编辑" onClick={onEdit}>
              <Pencil size={14} />
            </IconButton>
            <IconButton label="删除" onClick={handleDeleteClick}>
              <Trash2 size={14} />
            </IconButton>
          </div>
        </div>
      )}
    </article>
  );
}

export default McpServerCard;
