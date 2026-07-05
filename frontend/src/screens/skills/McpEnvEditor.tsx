/**
 * MCP server 环境变量 / 请求头编辑器 — 类型、辅助函数和可复用组件。
 *
 * 从 McpServerDialog 中提取，降低单文件行数。
 */

import { useState, useCallback } from "react";
import { X, Plus, Eye, EyeOff, ChevronDown, ChevronRight } from "lucide-react";

import type { McpServerResponse, McpServerParsedPreview } from "../../api/mcpServers";
import { Button, IconButton, Badge } from "../../components/primitives";

// ── Env row ─────────────────────────────────────────────────────────

export interface EnvRow {
  key: string;
  value: string;
  isSecret: boolean;
  isNew: boolean;
}

export function envRowsFromServer(server: McpServerResponse): EnvRow[] {
  const rows: EnvRow[] = [];
  for (const key of server.envKeys) {
    const presence = server.envPresence[key] ?? "";
    const isSecret = presence === "masked";
    const isMissing = server.envMissingKeys.includes(key);
    rows.push({
      key,
      value: isMissing ? "" : isSecret ? "" : presence,
      isSecret,
      isNew: false,
    });
  }
  return rows;
}

export function envRowsFromPreview(preview: McpServerParsedPreview): EnvRow[] {
  const rows: EnvRow[] = [];
  const env = preview.env ?? {};
  for (const [key, value] of Object.entries(env)) {
    rows.push({
      key,
      value: value ?? "",
      isSecret: preview.detectedSecretKeys.includes(key),
      isNew: true,
    });
  }
  return rows;
}

// ── Header row ─────────────────────────────────────────────────────

export interface HeaderRow {
  key: string;
  value: string;
  isSecret: boolean;
  isNew: boolean;
}

export function headerRowsFromServer(server: McpServerResponse): HeaderRow[] {
  const rows: HeaderRow[] = [];
  for (const key of server.headerKeys) {
    const presence = server.headerPresence[key] ?? "";
    const isSecret = presence === "masked";
    const isMissing = server.headerMissingKeys.includes(key);
    rows.push({
      key,
      value: isMissing ? "" : isSecret ? "" : presence,
      isSecret,
      isNew: false,
    });
  }
  return rows;
}

// ── Preset definitions ──────────────────────────────────────────────

export interface PresetDef {
  slug: string;
  name: string;
  description: string;
  command: string;
  args: string[];
  env: Record<string, string>;
  secretEnvKeys: string[];
}

/**
 * 预置 server 定义（前端镜像后端 mcp_presets.py）。
 *
 * 注意：command 使用后端约定的平台相关值。
 * Windows 下 npx 需要 cmd /c 包装，此处由后端 preset 逻辑处理；
 * 前端仅在"一键启用"快捷路径直接提交时需注意平台差异。
 */
export const PRESET_SERVERS: PresetDef[] = [
  {
    slug: "filesystem",
    name: "文件系统",
    description: "文件系统操作（读取/写入/搜索文件）",
    command: "npx",
    args: ["-y", "@modelcontextprotocol/server-filesystem"],
    env: {},
    secretEnvKeys: [],
  },
  {
    slug: "github",
    name: "GitHub",
    description: "GitHub 操作（PR/Issue/搜索等），需要 API token",
    command: "npx",
    args: ["-y", "@modelcontextprotocol/server-github"],
    env: { GITHUB_PERSONAL_ACCESS_TOKEN: "" },
    secretEnvKeys: ["GITHUB_PERSONAL_ACCESS_TOKEN"],
  },
];

// ── McpEnvFieldset component ────────────────────────────────────────

interface McpEnvFieldsetProps {
  legend: string;
  rows: EnvRow[];
  onRowsChange: (rows: EnvRow[]) => void;
  secretVisible: Record<string, boolean>;
  onToggleSecret: (key: string) => void;
  keyPlaceholder?: string;
  valuePlaceholder?: string;
  collapsible?: boolean;
  collapsedHint?: string;
}

/**
 * 环境变量 / 请求头编辑 fieldset。
 * 通用化设计，env 和 header 共用同一个组件。
 */
export function McpEnvFieldset({
  legend,
  rows,
  onRowsChange,
  secretVisible,
  onToggleSecret,
  keyPlaceholder = "变量名",
  valuePlaceholder = "变量值",
  collapsible = false,
  collapsedHint,
}: McpEnvFieldsetProps): JSX.Element {
  const [expanded, setExpanded] = useState(!collapsible);

  const addRow = useCallback((): void => {
    onRowsChange([...rows, { key: "", value: "", isSecret: false, isNew: true }]);
  }, [rows, onRowsChange]);

  const removeRow = useCallback((index: number): void => {
    onRowsChange(rows.filter((_, i) => i !== index));
  }, [rows, onRowsChange]);

  const updateRow = useCallback(
    (index: number, field: "key" | "value" | "isSecret", val: string | boolean): void => {
      onRowsChange(rows.map((row, i) =>
        i === index ? { ...row, [field]: val } : row,
      ));
    },
    [rows, onRowsChange],
  );

  const renderLegend = (): JSX.Element => {
    if (!collapsible) {
      return <legend className="mcp-form-legend">{legend}</legend>;
    }
    return (
      <legend
        className="mcp-form-legend mcp-collapsible-legend"
        onClick={() => setExpanded((prev) => !prev)}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            setExpanded((prev) => !prev);
          }
        }}
      >
        {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        <span>{legend}</span>
        {!expanded && rows.length > 0 && (
          <Badge tone="neutral">{rows.length}</Badge>
        )}
      </legend>
    );
  };

  return (
    <fieldset className="mcp-form-fieldset">
      {renderLegend()}
      {expanded && (
        <>
          {rows.map((row, index) => {
            const visKey = collapsible ? `header-${row.key}` : row.key;
            const isVisible = secretVisible[visKey] ?? false;
            const isMissing = row.value.trim() === "" && row.key.trim() !== "";
            const varRefMatch = row.value.trim().match(/^\$\{(.+)\}$/);
            return (
              <div key={index}>
                <div className="mcp-env-row">
                  <input
                    type="text"
                    className="mcp-form-input mcp-env-key"
                    value={row.key}
                    onChange={(e) => updateRow(index, "key", e.target.value)}
                    placeholder={keyPlaceholder}
                    disabled={!row.isNew}
                  />
                  {row.isSecret && !isVisible ? (
                    <div className="mcp-secret-field">
                      <input
                        type="password"
                        className="mcp-form-input mcp-env-value"
                        value={row.value}
                        onChange={(e) => updateRow(index, "value", e.target.value)}
                        placeholder={isMissing ? "待填写" : "输入新值替换已保存的密钥"}
                      />
                      <IconButton label="显示" onClick={() => onToggleSecret(visKey)}>
                        <Eye size={14} />
                      </IconButton>
                    </div>
                  ) : (
                    <div className="mcp-secret-field">
                      <input
                        type="text"
                        className="mcp-form-input mcp-env-value"
                        value={row.value}
                        onChange={(e) => updateRow(index, "value", e.target.value)}
                        placeholder={
                          row.isSecret && isMissing
                            ? "待填写"
                            : row.isSecret
                              ? "输入新值替换已保存的密钥"
                              : valuePlaceholder
                        }
                      />
                      {row.isSecret ? (
                        <IconButton label="隐藏" onClick={() => onToggleSecret(visKey)}>
                          <EyeOff size={14} />
                        </IconButton>
                      ) : null}
                    </div>
                  )}
                  <label className="mcp-secret-toggle">
                    <input
                      type="checkbox"
                      checked={row.isSecret}
                      onChange={(e) => updateRow(index, "isSecret", e.target.checked)}
                    />
                    <small>密钥</small>
                  </label>
                  {row.isNew ? (
                    <IconButton label="删除此行" onClick={() => removeRow(index)}>
                      <X size={14} />
                    </IconButton>
                  ) : null}
                </div>
                {varRefMatch ? (
                  <small className="mcp-form-hint mcp-var-hint">
                    将读取系统环境变量 {varRefMatch[1]}；或直接输入实际值
                  </small>
                ) : null}
              </div>
            );
          })}
          <Button kind="ghost" onClick={addRow}>
            <Plus size={14} />
            <span>{collapsible ? "添加请求头" : "添加环境变量"}</span>
          </Button>
          {collapsedHint ? (
            <small className="mcp-form-hint">{collapsedHint}</small>
          ) : null}
        </>
      )}
    </fieldset>
  );
}
