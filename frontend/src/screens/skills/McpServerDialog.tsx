import { useState, useCallback } from "react";
import { X, FileJson, Loader2, AlertCircle, RefreshCw } from "lucide-react";

import type {
  McpServerResponse,
  McpServerCreateRequest,
  McpServerUpdateRequest,
  McpServerParsedPreview,
} from "../../api/mcpServers";
import { Button, IconButton, Badge } from "../../components/primitives";
import { useMcpStore } from "../../state/mcpStore";
import {
  type EnvRow,
  type HeaderRow,
  PRESET_SERVERS,
  McpEnvFieldset,
  envRowsFromServer,
  envRowsFromPreview,
  headerRowsFromServer,
} from "./McpEnvEditor";

// ── Props ───────────────────────────────────────────────────────────

interface McpServerDialogProps {
  server: McpServerResponse | null; // null = create mode
  onClose: () => void;
}

// ── Component ───────────────────────────────────────────────────────

export function McpServerDialog({
  server,
  onClose,
}: McpServerDialogProps): JSX.Element {
  const isEdit = server !== null;

  const addServer = useMcpStore((s) => s.addServer);
  const updateServer = useMcpStore((s) => s.updateServer);
  const importJson = useMcpStore((s) => s.importJson);
  const importPreview = useMcpStore((s) => s.importPreview);
  const clearImportPreview = useMcpStore((s) => s.clearImportPreview);
  const testConnection = useMcpStore((s) => s.testConnection);
  const testingServerId = useMcpStore((s) => s.testingServerId);
  const testResult = useMcpStore((s) => s.testResult);
  const clearTestResult = useMcpStore((s) => s.clearTestResult);
  const loading = useMcpStore((s) => s.loading);
  const lastError = useMcpStore((s) => s.lastError);

  // ── Form state ──────────────────────────────────────────────────
  const [name, setName] = useState(server?.name ?? "");
  const [command, setCommand] = useState(server?.command ?? "");
  const [argsText, setArgsText] = useState(
    server?.args ? server.args.join(", ") : "",
  );
  const [envRows, setEnvRows] = useState<EnvRow[]>(
    server ? envRowsFromServer(server) : [],
  );
  const [headerRows, setHeaderRows] = useState<HeaderRow[]>(
    server ? headerRowsFromServer(server) : [],
  );
  const [selectedPreset, setSelectedPreset] = useState<string | null>(null);
  const [jsonText, setJsonText] = useState("");
  const [jsonError, setJsonError] = useState<string | null>(null);
  const [secretVisible, setSecretVisible] = useState<Record<string, boolean>>(
    {},
  );
  const [saving, setSaving] = useState(false);

  // ── Entry mode ──────────────────────────────────────────────────
  type EntryMode = "preset" | "manual" | "json";
  const [entryMode, setEntryMode] = useState<EntryMode>(
    isEdit ? "manual" : "preset",
  );

  // ── Helpers ─────────────────────────────────────────────────────

  const parseArgs = useCallback((): string[] | null => {
    const trimmed = argsText.trim();
    if (!trimmed) return null;
    if (trimmed.startsWith("[")) {
      try {
        const parsed = JSON.parse(trimmed);
        if (Array.isArray(parsed) && parsed.every((v) => typeof v === "string")) {
          return parsed;
        }
      } catch {
        // fall through to comma split
      }
    }
    return trimmed.split(",").map((s) => s.trim()).filter(Boolean);
  }, [argsText]);

  const hasPendingPlaceholders = useCallback((): boolean => {
    return envRows.some(
      (row) => row.value.trim() === "" && row.key.trim() !== "",
    );
  }, [envRows]);

  const toggleSecretVisible = useCallback((key: string): void => {
    setSecretVisible((prev) => ({ ...prev, [key]: !prev[key] }));
  }, []);

  // ── Preset selection ────────────────────────────────────────────

  const handlePresetSelect = useCallback(
    (slug: string): void => {
      const preset = PRESET_SERVERS.find((p) => p.slug === slug);
      if (!preset) return;
      setSelectedPreset(slug);
      setName(preset.name);
      setCommand(preset.command);
      setArgsText(preset.args.join(", "));
      const rows: EnvRow[] = Object.entries(preset.env).map(([key, value]) => ({
        key,
        value: value ?? "",
        isSecret: preset.secretEnvKeys.includes(key),
        isNew: true,
      }));
      setEnvRows(rows);
      setEntryMode("manual");
    },
    [],
  );

  // ── JSON import ─────────────────────────────────────────────────

  const handleJsonParse = useCallback((): void => {
    setJsonError(null);
    if (!jsonText.trim()) {
      setJsonError("请粘贴 JSON 配置");
      return;
    }
    void importJson(jsonText);
  }, [jsonText, importJson]);

  const handleApplyImport = useCallback(
    (preview: McpServerParsedPreview): void => {
      setName(preview.name);
      setCommand(preview.command ?? "");
      setArgsText(preview.args?.join(", ") ?? "");
      setEnvRows(envRowsFromPreview(preview));
      clearImportPreview();
      setEntryMode("manual");
    },
    [clearImportPreview],
  );

  // ── Save ────────────────────────────────────────────────────────

  const handleSave = useCallback((): void => {
    if (!name.trim() || !command.trim()) return;

    const args = parseArgs();
    const env: Record<string, string> = {};
    const secretEnvKeys: string[] = [];
    for (const row of envRows) {
      if (row.key.trim()) {
        env[row.key.trim()] = row.value;
        if (row.isSecret) secretEnvKeys.push(row.key.trim());
      }
    }
    const headers: Record<string, string> = {};
    const secretHeaderKeys: string[] = [];
    for (const row of headerRows) {
      if (row.key.trim()) {
        headers[row.key.trim()] = row.value;
        if (row.isSecret) secretHeaderKeys.push(row.key.trim());
      }
    }

    setSaving(true);

    if (isEdit && server) {
      const input: McpServerUpdateRequest = {
        command: command.trim(),
        args,
        env: Object.keys(env).length > 0 ? env : null,
        secretEnvKeys: secretEnvKeys.length > 0 ? secretEnvKeys : null,
        headers: Object.keys(headers).length > 0 ? headers : null,
        secretHeaderKeys: secretHeaderKeys.length > 0 ? secretHeaderKeys : null,
      };
      void updateServer(server.serverId, input).then(() => {
        setSaving(false);
        if (!useMcpStore.getState().lastError) {
          onClose();
        }
      });
    } else {
      const input: McpServerCreateRequest = {
        name: name.trim(),
        transport: "stdio",
        command: command.trim(),
        args,
        env: Object.keys(env).length > 0 ? env : null,
        secretEnvKeys: secretEnvKeys.length > 0 ? secretEnvKeys : null,
        headers: Object.keys(headers).length > 0 ? headers : null,
        secretHeaderKeys: secretHeaderKeys.length > 0 ? secretHeaderKeys : null,
        presetSlug: selectedPreset,
      };
      void addServer(input).then(() => {
        setSaving(false);
        if (!useMcpStore.getState().lastError) {
          onClose();
        }
      });
    }
  }, [
    name, command, parseArgs, envRows, headerRows,
    isEdit, server, selectedPreset, updateServer, addServer, onClose,
  ]);

  // ── Test connection ─────────────────────────────────────────────

  const handleTestConnection = useCallback((): void => {
    if (!server) return;
    clearTestResult();
    void testConnection(server.serverId);
  }, [server, testConnection, clearTestResult]);

  // ── Render ──────────────────────────────────────────────────────

  const canSave =
    name.trim() !== "" &&
    command.trim() !== "" &&
    !hasPendingPlaceholders() &&
    !saving;

  return (
    <div className="trial-dialog-overlay" onClick={onClose} role="presentation">
      <div
        className="trial-dialog mcp-dialog"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-label={isEdit ? "编辑 MCP 服务器" : "添加 MCP 服务器"}
      >
        <div className="trial-dialog-header">
          <h3>{isEdit ? "编辑 MCP 服务器" : "添加 MCP 服务器"}</h3>
          <IconButton label="关闭" onClick={onClose}>
            <X size={16} />
          </IconButton>
        </div>

        <div className="trial-dialog-body mcp-dialog-body">
          {/* Entry mode tabs (create mode only) */}
          {!isEdit && (
            <div className="mcp-entry-tabs" role="tablist">
              {(
                [
                  ["preset", "预置服务器"],
                  ["manual", "手动填写"],
                  ["json", "粘贴 JSON"],
                ] as const
              ).map(([mode, label]) => (
                <button
                  key={mode}
                  role="tab"
                  type="button"
                  aria-selected={entryMode === mode}
                  className={`mcp-entry-tab ${entryMode === mode ? "mcp-entry-tab-active" : ""}`}
                  onClick={() => setEntryMode(mode)}
                >
                  {label}
                </button>
              ))}
            </div>
          )}

          {/* Preset selection */}
          {entryMode === "preset" && !isEdit && (
            <div className="mcp-preset-list">
              <p className="mcp-preset-hint">
                选择预置服务器快速启用，需要凭证的会在下一步填写
              </p>
              {PRESET_SERVERS.map((preset) => (
                <button
                  key={preset.slug}
                  type="button"
                  className="mcp-preset-card"
                  onClick={() => handlePresetSelect(preset.slug)}
                >
                  <div className="mcp-preset-card-top">
                    <strong>{preset.name}</strong>
                    <Badge tone="ok">AI 可直接调用</Badge>
                  </div>
                  <p>{preset.description}</p>
                  <div className="mcp-preset-card-meta">
                    <span className="me-mono">{preset.command}</span>
                    {preset.secretEnvKeys.length > 0 ? (
                      <span className="mcp-env-warning">需要 API Token</span>
                    ) : (
                      <span className="mcp-env-ok">无需凭证</span>
                    )}
                  </div>
                </button>
              ))}
            </div>
          )}

          {/* JSON import */}
          {entryMode === "json" && !isEdit && (
            <div className="mcp-json-import">
              <p className="mcp-json-hint">
                支持 Claude Desktop/Code 嵌套 mcpServers 格式、裸 stdio server 对象、HTTP server 对象
              </p>
              <textarea
                className="mcp-json-textarea"
                rows={8}
                placeholder='{"mcpServers": {"my-server": {"command": "npx", "args": [...]}}}'
                value={jsonText}
                onChange={(e) => { setJsonText(e.target.value); setJsonError(null); }}
              />
              {jsonError ? (
                <div className="mcp-json-error">
                  <AlertCircle size={14} />
                  <span>{jsonError}</span>
                </div>
              ) : null}
              {importPreview && importPreview.length > 0 ? (
                <div className="mcp-import-preview">
                  <p>检测到 {importPreview.length} 个服务器配置：</p>
                  {importPreview.map((preview, idx) => (
                    <div key={idx} className="mcp-import-preview-item">
                      <div>
                        <strong>{preview.name}</strong>
                        <span className="me-mono">{preview.command ?? preview.url ?? "unknown"}</span>
                      </div>
                      <Button kind="primary" onClick={() => handleApplyImport(preview)}>
                        填入表单
                      </Button>
                    </div>
                  ))}
                </div>
              ) : null}
              <div className="mcp-json-actions">
                <Button kind="primary" onClick={handleJsonParse} disabled={!jsonText.trim() || loading}>
                  {loading ? <Loader2 size={14} className="mcp-spin" /> : <FileJson size={14} />}
                  <span>解析配置</span>
                </Button>
              </div>
            </div>
          )}

          {/* Manual form (also used after preset/json fill) */}
          {(entryMode === "manual" || isEdit) && (
            <div className="mcp-form">
              <label className="mcp-form-field">
                <span className="mcp-form-label">名称</span>
                <input
                  type="text" className="mcp-form-input" value={name}
                  onChange={(e) => setName(e.target.value)} disabled={isEdit}
                  placeholder="例如：GitHub"
                />
                {isEdit ? <small className="mcp-form-hint">服务器名称不可修改</small> : null}
              </label>

              <label className="mcp-form-field">
                <span className="mcp-form-label">命令 <span className="mcp-required">*</span></span>
                <input
                  type="text" className="mcp-form-input" value={command}
                  onChange={(e) => setCommand(e.target.value)} placeholder="例如：npx"
                />
              </label>

              <label className="mcp-form-field">
                <span className="mcp-form-label">参数</span>
                <input
                  type="text" className="mcp-form-input" value={argsText}
                  onChange={(e) => setArgsText(e.target.value)}
                  placeholder="逗号分隔，例如：-y, @modelcontextprotocol/server-filesystem"
                />
                <small className="mcp-form-hint">逗号分隔或 JSON 数组格式</small>
              </label>

              <McpEnvFieldset
                legend="环境变量"
                rows={envRows}
                onRowsChange={setEnvRows}
                secretVisible={secretVisible}
                onToggleSecret={toggleSecretVisible}
              />

              <McpEnvFieldset
                legend="请求头"
                rows={headerRows}
                onRowsChange={setHeaderRows}
                secretVisible={secretVisible}
                onToggleSecret={toggleSecretVisible}
                keyPlaceholder="Header 名"
                valuePlaceholder="Header 值"
                collapsible
                collapsedHint="当前仅支持 stdio 传输，请求头暂不生效；HTTP 传输开放后自动启用"
              />

              {hasPendingPlaceholders() ? (
                <div className="mcp-form-warning">
                  <AlertCircle size={14} />
                  <span>有环境变量尚未填写，保存前请补全</span>
                </div>
              ) : null}

              {lastError ? (
                <div className="mcp-form-error">
                  <AlertCircle size={14} />
                  <span>{lastError}</span>
                </div>
              ) : null}

              {isEdit && server ? (
                <div className="mcp-test-section">
                  <Button
                    kind="secondary" onClick={handleTestConnection}
                    disabled={testingServerId === server.serverId}
                  >
                    {testingServerId === server.serverId ? (
                      <Loader2 size={14} className="mcp-spin" />
                    ) : (
                      <RefreshCw size={14} />
                    )}
                    <span>测试连接</span>
                  </Button>
                  <small className="mcp-form-hint">首次启动可能需 30s+ 下载依赖</small>
                  {testResult ? (
                    <div className={`mcp-test-result ${testResult.success ? "mcp-test-ok" : "mcp-test-fail"}`}>
                      {testResult.success ? (
                        <span>连接成功，发现 {testResult.toolCount} 个工具</span>
                      ) : (
                        <span>{testResult.error ?? "连接测试失败"}</span>
                      )}
                    </div>
                  ) : null}
                </div>
              ) : null}
            </div>
          )}
        </div>

        <div className="mcp-dialog-footer">
          <Button kind="ghost" onClick={onClose}>取消</Button>
          {(entryMode === "manual" || isEdit) && (
            <Button kind="primary" onClick={handleSave} disabled={!canSave}>
              {saving ? <Loader2 size={14} className="mcp-spin" /> : null}
              <span>{isEdit ? "保存修改" : "添加服务器"}</span>
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

export default McpServerDialog;
