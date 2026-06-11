import { KeyRound, Save, Trash2 } from "lucide-react";
import { useState } from "react";

import type { SettingDescriptor, SettingValue } from "../../api/settings";
import { Badge, Button, IconButton } from "../../components/primitives";

function SettingControls({
  items,
  values,
  secrets,
  dirtyKeys,
  validationErrors,
  busy,
  onValue,
  onSave,
  onWriteSecret,
  onDeleteSecret,
}: {
  items: SettingDescriptor[];
  values: Record<string, SettingValue>;
  secrets: Record<string, { present: boolean; masked: string }>;
  dirtyKeys: string[];
  validationErrors: Record<string, string>;
  busy: boolean;
  onValue: (key: string, value: SettingValue) => void;
  onSave: () => void;
  onWriteSecret: (key: string, value: string) => void;
  onDeleteSecret: (key: string) => void;
}): JSX.Element {
  const [secretDrafts, setSecretDrafts] = useState<Record<string, string>>({});
  const hasErrors = Object.values(validationErrors).some(Boolean);
  const regularItems = items.filter((item) => !item.advanced);
  const advancedItems = items.filter((item) => item.advanced);

  const renderItem = (item: SettingDescriptor): JSX.Element => {
    const error = validationErrors[item.key];
    const unavailable = item.status === "unavailable";
    if (item.valueKind === "secret") {
      const secret = secrets[item.key] ?? { present: false, masked: "" };
      const draft = secretDrafts[item.key] ?? "";
      return (
        <div className="settings-control-row" key={item.key}>
          <label>
            <span>{item.label}</span>
            <input
              aria-label={item.label}
              disabled={busy || unavailable}
              type="password"
              value={draft}
              placeholder={secret.present ? secret.masked : "未设置"}
              onChange={(event) =>
                setSecretDrafts((currentDrafts) => ({ ...currentDrafts, [item.key]: event.currentTarget.value }))
              }
            />
          </label>
          <div className="settings-control-meta">
            <Badge tone={secret.present ? "ok" : "warn"}>{secret.present ? "已保存" : "未设置"}</Badge>
            <Button
              disabled={busy || unavailable || !draft.trim()}
              kind="secondary"
              onClick={() => {
                onWriteSecret(item.key, draft);
                setSecretDrafts((currentDrafts) => ({ ...currentDrafts, [item.key]: "" }));
              }}
            >
              <KeyRound size={14} />
              <span>保存密钥</span>
            </Button>
            <IconButton label="删除密钥" disabled={busy || unavailable || !secret.present} onClick={() => onDeleteSecret(item.key)}>
              <Trash2 size={14} />
            </IconButton>
          </div>
          {item.description ? <small className="settings-hint">{item.description}</small> : null}
          {error ? <small className="settings-error">{error}</small> : null}
        </div>
      );
    }

    return (
      <div className="settings-control-row" key={item.key}>
            <label>
              <span>{item.label}</span>
              {item.valueKind === "boolean" ? (
                <input
                  aria-label={item.label}
                  checked={Boolean(values[item.key])}
                  disabled={busy || unavailable}
                  type="checkbox"
                  onChange={(event) => onValue(item.key, event.currentTarget.checked)}
                />
              ) : null}
              {item.valueKind === "enum" ? (
                <select
                  aria-label={item.label}
                  disabled={busy || unavailable}
                  value={String(values[item.key] ?? "")}
                  onChange={(event) => onValue(item.key, event.currentTarget.value)}
                >
                  {item.options.map((option) => (
                    <option key={option} value={option}>
                      {option}
                    </option>
                  ))}
                </select>
              ) : null}
              {item.valueKind === "integer" ? (
                <input
                  aria-label={item.label}
                  disabled={busy || unavailable}
                  type="number"
                  value={Number(values[item.key] ?? 0)}
                  onChange={(event) => onValue(item.key, Number(event.currentTarget.value))}
                />
              ) : null}
              {item.valueKind === "number" ? (
                <input
                  aria-label={item.label}
                  disabled={busy || unavailable}
                  step="0.1"
                  type="number"
                  value={Number(values[item.key] ?? 0)}
                  onChange={(event) => onValue(item.key, Number(event.currentTarget.value))}
                />
              ) : null}
              {item.valueKind === "string" || item.valueKind === "path" ? (
                <input
                  aria-label={item.label}
                  disabled={busy || unavailable}
                  value={String(values[item.key] ?? "")}
                  onChange={(event) => onValue(item.key, event.currentTarget.value)}
                />
              ) : null}
            </label>
            {unavailable ? (
              <div className="settings-control-meta">
                <Badge tone="warn">暂不可改</Badge>
                <small className="settings-hint">{item.description || "当前版本暂不可修改。"}</small>
              </div>
            ) : null}
            {!unavailable && item.description ? <small className="settings-hint">{item.description}</small> : null}
            {error ? <small className="settings-error">{error}</small> : null}
      </div>
    );
  };

  return (
    <section className="settings-controls" aria-label="设置项">
      {regularItems.map(renderItem)}
      {advancedItems.length > 0 ? (
        <details className="settings-advanced">
          <summary>高级参数</summary>
          <div className="settings-advanced-grid">{advancedItems.map(renderItem)}</div>
        </details>
      ) : null}
      <div className="settings-savebar">
        <span>{dirtyKeys.length > 0 ? `${dirtyKeys.length} 项待保存` : "无未保存更改"}</span>
        <Button disabled={busy || dirtyKeys.length === 0 || hasErrors} onClick={onSave}>
          <Save size={14} />
          <span>保存设置</span>
        </Button>
      </div>
    </section>
  );
}

export default SettingControls;
