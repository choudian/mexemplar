import { create } from "zustand";

import {
  deleteSettingSecret,
  getSettingsSchema,
  getSettingsValues,
  runSettingAction,
  updateSettingsValues,
  writeSettingSecret,
} from "../api/settings";
import type { SettingDescriptor, SettingSection, SettingValue, SettingsActionResponse } from "../api/settings";
import type { UiEvent } from "../api/client";
import { createDebouncedRefresh, toErrorMessage } from "./helpers";

export type SettingsState = {
  hydrated: boolean;
  schema: SettingSection[];
  values: Record<string, SettingValue>;
  draftValues: Record<string, SettingValue>;
  secrets: Record<string, { present: boolean; masked: string }>;
  status: Record<string, string>;
  dirtyKeys: string[];
  validationErrors: Record<string, string>;
  actionResults: Record<string, SettingsActionResponse>;
  busy: boolean;
  lastError: string | null;
  load: () => Promise<void>;
  setValue: (key: string, value: SettingValue) => void;
  saveValues: () => Promise<void>;
  writeSecret: (secretKey: string, value: string) => Promise<void>;
  deleteSecret: (secretKey: string) => Promise<void>;
  runAction: (actionName: string, options?: { confirmed?: boolean }) => Promise<void>;
  applyEvent: (event: UiEvent) => void;
  markHydrated: () => void;
  setError: (message: string | null) => void;
};

function descriptors(sections: SettingSection[]): SettingDescriptor[] {
  return sections.flatMap((section) => section.items);
}

function validate(descriptor: SettingDescriptor | undefined, value: SettingValue): string | null {
  if (!descriptor) return null;
  if (descriptor.valueKind === "integer" || descriptor.valueKind === "number") {
    const numeric = Number(value);
    if (descriptor.valueKind === "integer" && !Number.isInteger(numeric)) return "必须是整数。";
    if (!Number.isFinite(numeric)) return "必须是数字。";
    const minimum = descriptor.validationRules.min;
    const maximum = descriptor.validationRules.max;
    if (typeof minimum === "number" && numeric < minimum) return `不能小于 ${minimum}。`;
    if (typeof maximum === "number" && numeric > maximum) return `不能大于 ${maximum}。`;
  }
  if (descriptor.valueKind === "enum" && !descriptor.options.includes(String(value))) {
    return "请选择有效选项。";
  }
  if (descriptor.validationRules.required && !String(value ?? "").trim()) {
    return "不能为空。";
  }
  return null;
}

const scheduleRefresh = createDebouncedRefresh();

export const useSettingsStore = create<SettingsState>((set, get) => ({
  hydrated: false,
  schema: [],
  values: {},
  draftValues: {},
  secrets: {},
  status: {},
  dirtyKeys: [],
  validationErrors: {},
  actionResults: {},
  busy: false,
  lastError: null,
  markHydrated: () => set({ hydrated: true }),
  setError: (messageText) => set({ lastError: messageText }),
  load: async () => {
    set({ busy: true, lastError: null });
    try {
      const [schemaResponse, valuesResponse] = await Promise.all([
        getSettingsSchema(),
        getSettingsValues(),
      ]);
      const sections = Array.isArray(schemaResponse.sections) ? schemaResponse.sections : [];
      const values = valuesResponse.values ?? {};
      set({
        hydrated: true,
        schema: sections,
        values,
        draftValues: values,
        secrets: valuesResponse.secrets ?? {},
        status: valuesResponse.status ?? {},
        dirtyKeys: [],
        validationErrors: {},
      });
    } catch (error) {
      set({ lastError: toErrorMessage(error, "无法加载设置。") });
    } finally {
      set({ busy: false });
    }
  },
  setValue: (key, value) => {
    const descriptor = descriptors(get().schema).find((item) => item.key === key);
    const error = validate(descriptor, value);
    const draftValues = { ...get().draftValues, [key]: value };
    const dirtyKeys = Object.keys(draftValues).filter((item) => draftValues[item] !== get().values[item]);
    const validationErrors = { ...get().validationErrors };
    if (error) validationErrors[key] = error;
    else delete validationErrors[key];
    set({ draftValues, dirtyKeys, validationErrors });
  },
  saveValues: async () => {
    const { dirtyKeys, draftValues, validationErrors } = get();
    if (dirtyKeys.length === 0 || Object.keys(validationErrors).length > 0) return;
    set({ busy: true, lastError: null });
    try {
      const payload = Object.fromEntries(dirtyKeys.map((key) => [key, draftValues[key]]));
      const response = await updateSettingsValues(payload);
      set({
        values: response.values,
        draftValues: response.values,
        secrets: response.secrets,
        status: response.status,
        dirtyKeys: [],
        validationErrors: {},
      });
    } catch (error) {
      set({ lastError: toErrorMessage(error, "无法保存设置。") });
    } finally {
      set({ busy: false });
    }
  },
  writeSecret: async (secretKey, value) => {
    if (!value.trim()) {
      set({ validationErrors: { ...get().validationErrors, [secretKey]: "密钥不能为空。" } });
      return;
    }
    set({ busy: true, lastError: null });
    try {
      const response = await writeSettingSecret(secretKey, value);
      // 只更新这个密钥的展示状态。此前会调 load() 全量重载，把用户尚未点
      // "保存全部"的 draftValues 用后端旧值冲掉、dirtyKeys 归零，导致"保存全部"
      // 变灰且已填内容丢失——保存密钥不该动到其他字段的未保存草稿。
      const secrets = { ...get().secrets, [secretKey]: response };
      // 清掉该密钥的校验错误——必须删 key 而不是设成空串：saveValues 用
      // Object.keys(validationErrors).length 判断能否保存，留一个空串 key 会让
      // 计数为 1，"保存全部"永远发不出去（旧代码靠 load() 整表清空掩盖了这点）。
      const validationErrors = { ...get().validationErrors };
      delete validationErrors[secretKey];
      set({ secrets, validationErrors });
    } catch (error) {
      set({ lastError: toErrorMessage(error, "无法保存密钥。") });
    } finally {
      set({ busy: false });
    }
  },
  deleteSecret: async (secretKey) => {
    set({ busy: true, lastError: null });
    try {
      const response = await deleteSettingSecret(secretKey);
      // 同 writeSecret：只更新该密钥状态，不 load() 冲掉其他字段的未保存草稿。
      set({ secrets: { ...get().secrets, [secretKey]: response } });
    } catch (error) {
      set({ lastError: toErrorMessage(error, "无法删除密钥。") });
    } finally {
      set({ busy: false });
    }
  },
  runAction: async (actionName, options = {}) => {
    set({ busy: true, lastError: null });
    try {
      const response = await runSettingAction(actionName, options);
      set({ actionResults: { ...get().actionResults, [actionName]: response } });
    } catch (error) {
      set({ lastError: toErrorMessage(error, "设置动作执行失败。") });
    } finally {
      set({ busy: false });
    }
  },
  applyEvent: (event) => {
    if (event.type === "settings.changed") {
      scheduleRefresh(() => get().load());
    }
  },
}));
