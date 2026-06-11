import { requestJson } from "./client";

export type SettingSectionId = "ai" | "web" | "tool_output" | "recording" | "data" | "about";
type SettingValueKind = "string" | "integer" | "number" | "boolean" | "enum" | "path" | "secret" | "action";
type SettingStatus = "available" | "missing_secret" | "invalid" | "unavailable";
export type SettingValue = string | number | boolean | null;

export interface SettingDescriptor {
  key: string;
  label: string;
  section: SettingSectionId;
  valueKind: SettingValueKind;
  description: string;
  options: string[];
  validationRules: Record<string, unknown>;
  status: SettingStatus;
  advanced: boolean;
}

export interface SettingSection {
  id: SettingSectionId;
  label: string;
  items: SettingDescriptor[];
  actions: SettingDescriptor[];
}

export interface SettingsSchemaResponse {
  sections: SettingSection[];
}

export interface SettingsValuesResponse {
  values: Record<string, SettingValue>;
  secrets: Record<string, { secretKey?: string; present: boolean; masked: string }>;
  status: Record<string, SettingStatus>;
}

export interface SettingsActionResponse {
  actionName: string;
  status: "completed" | "failed" | "unavailable";
  message: string;
  details: Record<string, unknown>;
}

export function getSettingsSchema(): Promise<SettingsSchemaResponse> {
  return requestJson<SettingsSchemaResponse>("/api/settings/schema");
}

export function getSettingsValues(): Promise<SettingsValuesResponse> {
  return requestJson<SettingsValuesResponse>("/api/settings/values");
}

export function updateSettingsValues(values: Record<string, SettingValue>): Promise<SettingsValuesResponse> {
  return requestJson<SettingsValuesResponse>("/api/settings/values", {
    method: "PATCH",
    body: JSON.stringify({ values }),
  });
}

export function writeSettingSecret(secretKey: string, value: string): Promise<{ present: boolean; masked: string }> {
  return requestJson<{ present: boolean; masked: string }>(`/api/settings/secrets/${encodeURIComponent(secretKey)}`, {
    method: "POST",
    body: JSON.stringify({ value }),
  });
}

export function deleteSettingSecret(secretKey: string): Promise<{ present: boolean; masked: string }> {
  return requestJson<{ present: boolean; masked: string }>(`/api/settings/secrets/${encodeURIComponent(secretKey)}`, {
    method: "DELETE",
  });
}

export function runSettingAction(
  actionName: string,
  options: { confirmed?: boolean } = {},
): Promise<SettingsActionResponse> {
  return requestJson<SettingsActionResponse>(`/api/settings/actions/${encodeURIComponent(actionName)}`, {
    method: "POST",
    body: options.confirmed ? JSON.stringify({ confirmed: true }) : undefined,
  });
}
