import { requestJson } from "./client";
import type { BrainEntryStatus } from "./brain";

export type SkillOrigin =
  | "system_bootstrap"
  | "user_edit"
  | "assistant_tool_call"
  | "specialist_tool_call"
  | "external_import";

export type SkillStatus = "active" | "superseded" | "soft_deleted";
export type { BrainEntryStatus };
export type EquipmentEntityType = "assistant" | "specialist";
export type EquipmentStatus = "active" | "unequipped";
export type UnequippedReason = "user_unequip" | "force_remove_on_soft_delete" | "supersede_transfer";
export type SkillSortKey = "recently_changed" | "loaded_count" | "referenced_count" | "equipped_count";
export type SkillFilterKey = "all" | "never_referenced" | "not_referenced_30d";

export interface SkillMethodologySummary {
  skill_id: string;
  name: string;
  description: string;
  trigger_conditions: string[];
  required_tools: string[];
  version: number;
  chain_root_id: string;
  origin: SkillOrigin;
  is_protected: boolean;
  loaded_count: number;
  referenced_count: number;
  equipped_count: number;
  last_referenced_at: string | null;
  created_at: string | null;
}

export interface SkillSourceSegment {
  segment_id: string;
  source_zone: "archive" | "failure";
  segment_summary: string;
  segment_status: BrainEntryStatus;
}

export interface SkillDetail extends SkillMethodologySummary {
  body_markdown: string;
  parent_skill_id: string | null;
  status: SkillStatus;
  source_segments: SkillSourceSegment[];
}

export interface SkillEditRequest {
  name: string;
  description: string;
  trigger_conditions: string[];
  required_tools: string[];
  body_markdown: string;
  change_reason?: string;
}

export interface SkillVersionNode {
  skill_id: string;
  version: number;
  name: string;
  description: string;
  trigger_conditions: string[];
  required_tools: string[];
  body_markdown: string;
  diff_from_previous: string | null;
  origin: SkillOrigin;
  changed_by: string | null;
  change_reason: string | null;
  created_at: string | null;
}

export interface SkillHistoryResponse {
  chain_root_id: string;
  nodes: SkillVersionNode[];
}

export interface SkillEquipmentItem {
  skill_id: string;
  chain_root_id: string;
  name: string;
  description: string;
  trigger_conditions: string[];
  required_tools: string[];
  missing_required_tools: string[];
  equipped_order: number;
  equipped_at: string | null;
}

export interface SkillEquipmentAuditRow {
  equipped_entity_type: EquipmentEntityType;
  equipped_entity_id: string;
  equipped_entity_name: string;
  status: EquipmentStatus;
  equipped_at: string | null;
  unequipped_at: string | null;
  unequipped_reason: UnequippedReason | null;
}

export interface SkillEquipmentAuditResponse {
  skill_id: string;
  rows: SkillEquipmentAuditRow[];
}

export interface TokenBudgetThresholds {
  warn_threshold: number;
  danger_threshold: number;
}

export interface EntityEquipmentResponse {
  entity_type: EquipmentEntityType;
  entity_id: string;
  entity_name: string;
  tool_whitelist: string[];
  active_equipment: SkillEquipmentItem[];
  token_budget_estimate: number;
  token_budget_thresholds: TokenBudgetThresholds;
}

export interface EquipmentUpdateRequest {
  skills: Array<{ skill_id: string; equipped_order: number }>;
}

export interface EquipmentUpdateResponse {
  active_equipment_count: number;
  newly_equipped: string[];
  newly_unequipped: string[];
  reordered: string[];
}

export interface SkillSoftDeleteResponse {
  deleted_skill_id: string;
  pruned_equipment_count: number;
  affected_specialist_ids: string[];
}

export interface BootstrapStatusResponse {
  bootstrap_active_skill_id: string | null;
  fallback_used: boolean;
  seed_file_path: string;
  last_seed_check_at: string | null;
}

export interface SkillListResponse {
  items: SkillMethodologySummary[];
}

export function listMethodologySkills(options: {
  sort?: SkillSortKey;
  filter?: SkillFilterKey;
} = {}): Promise<SkillListResponse> {
  const params = new URLSearchParams();
  params.set("sort", options.sort ?? "recently_changed");
  if (options.filter && options.filter !== "all") {
    params.set("filter", options.filter);
  }
  return requestJson<SkillListResponse>(`/api/skills/methodology?${params}`);
}

export function getMethodologySkill(skillId: string): Promise<SkillDetail> {
  return requestJson<SkillDetail>(`/api/skills/methodology/${encodeURIComponent(skillId)}`);
}

export function updateMethodologySkill(skillId: string, body: SkillEditRequest): Promise<SkillDetail> {
  return requestJson<SkillDetail>(`/api/skills/methodology/${encodeURIComponent(skillId)}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

export function softDeleteMethodologySkill(skillId: string): Promise<SkillSoftDeleteResponse> {
  return requestJson<SkillSoftDeleteResponse>(`/api/skills/methodology/${encodeURIComponent(skillId)}/soft-delete`, {
    method: "POST",
  });
}

export function getMethodologySkillHistory(skillId: string): Promise<SkillHistoryResponse> {
  return requestJson<SkillHistoryResponse>(`/api/skills/methodology/${encodeURIComponent(skillId)}/history`);
}

export function getMethodologySkillEquipmentAudit(skillId: string): Promise<SkillEquipmentAuditResponse> {
  return requestJson<SkillEquipmentAuditResponse>(
    `/api/skills/methodology/${encodeURIComponent(skillId)}/audit-equipment`,
  );
}

export function getEntityEquipment(entityId: string): Promise<EntityEquipmentResponse> {
  return requestJson<EntityEquipmentResponse>(`/api/specialists/${encodeURIComponent(entityId)}/equipment`);
}

export function updateEntityEquipment(
  entityId: string,
  body: EquipmentUpdateRequest,
): Promise<EquipmentUpdateResponse> {
  return requestJson<EquipmentUpdateResponse>(`/api/specialists/${encodeURIComponent(entityId)}/equipment`, {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

export function getMethodologyBootstrapStatus(): Promise<BootstrapStatusResponse> {
  return requestJson<BootstrapStatusResponse>("/api/skills/methodology/bootstrap-status");
}
