import { useEffect, useMemo, useState } from "react";

import type { SettingSectionId } from "../../api/settings";
import { Button } from "../../components/primitives";
import { useSettingsStore } from "../../state/settingsStore";
import SettingControls from "./SettingControls";
import SettingsActions from "./SettingsActions";

const initialSection: SettingSectionId = "ai";

export function SettingsScreen(): JSX.Element {
  const [activeSection, setActiveSection] = useState<SettingSectionId>(initialSection);
  const schema = useSettingsStore((state) => state.schema);
  const values = useSettingsStore((state) => state.draftValues);
  const secrets = useSettingsStore((state) => state.secrets);
  const dirtyKeys = useSettingsStore((state) => state.dirtyKeys);
  const validationErrors = useSettingsStore((state) => state.validationErrors);
  const actionResults = useSettingsStore((state) => state.actionResults);
  const busy = useSettingsStore((state) => state.busy);
  const lastError = useSettingsStore((state) => state.lastError);
  const load = useSettingsStore((state) => state.load);
  const setValue = useSettingsStore((state) => state.setValue);
  const saveValues = useSettingsStore((state) => state.saveValues);
  const writeSecret = useSettingsStore((state) => state.writeSecret);
  const deleteSecret = useSettingsStore((state) => state.deleteSecret);
  const runAction = useSettingsStore((state) => state.runAction);

  useEffect(() => {
    void load();
  }, [load]);

  const sections = Array.isArray(schema) ? schema : [];
  const section = useMemo(
    () => sections.find((item) => item.id === activeSection) ?? sections[0],
    [activeSection, sections],
  );

  return (
    <section className="settings-screen" aria-label="应用设置">
      <div className="settings-sidebar">
        <h2>应用设置</h2>
        <div className="settings-tabs" role="tablist" aria-label="设置分区">
          {sections.map((item) => (
            <Button
              aria-selected={section?.id === item.id}
              key={item.id}
              kind={section?.id === item.id ? "primary" : "secondary"}
              role="tab"
              onClick={() => setActiveSection(item.id)}
            >
              {item.label}
            </Button>
          ))}
        </div>
      </div>
      <div className="settings-detail">
        {section ? (
          <>
            <div className="settings-detail-header">
              <h3>{section.label}</h3>
              {busy ? <span>正在处理</span> : null}
            </div>
            <SettingControls
              items={section.items}
              values={values}
              secrets={secrets}
              dirtyKeys={dirtyKeys}
              validationErrors={validationErrors}
              busy={busy}
              onValue={setValue}
              onSave={() => {
                void saveValues();
              }}
              onWriteSecret={(key, value) => {
                void writeSecret(key, value);
              }}
              onDeleteSecret={(key) => {
                void deleteSecret(key);
              }}
            />
            <SettingsActions
              actions={section.actions}
              results={actionResults}
              busy={busy}
              onRun={(actionName, options) => {
                void runAction(actionName, options);
              }}
            />
          </>
        ) : (
          <div className="settings-empty">正在加载设置</div>
        )}
        {lastError ? <div className="settings-error">{lastError}</div> : null}
      </div>
    </section>
  );
}

export default SettingsScreen;
