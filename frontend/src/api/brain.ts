import { DesktopApiError, requestJson } from './client';

export type BrainZone = 'hot' | 'persistent' | 'archive' | 'subconscious' | 'failure' | 'prediction';
export type BrainEntryStatus = 'active' | 'fading' | 'invalidated' | 'soft-deleted';
export type BrainSegmentStatus = 'pending' | 'distilling' | 'completed' | 'failed';
export type BrainVerificationStatus = 'hit' | 'partial' | 'miss' | 'expired';

export interface BrainZoneSummary {
  zone: BrainZone;
  label: string;
  entry_count: number;
  fading_count: number;
}

export interface BrainMemoryEntry {
  entry_id: string;
  zone: BrainZone;
  entry_type: string | null;
  content: string;
  status: BrainEntryStatus;
  origin: string;
  reason: string;
  scope: string | null;
  loaded_count: number;
  referenced_count: number;
  superseded_by: string | null;
  verification_checkpoint: string | null;
  verification_status: BrainVerificationStatus | null;
  verification_rationale: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface BrainSegment {
  segment_id: string;
  session_id: string;
  status: BrainSegmentStatus;
  retry_count: number;
  boundary_reason: string | null;
  sealed_at: string | null;
  completed_at: string | null;
  created_at: string | null;
}

export interface BrainSpecialist {
  specialist_id: string;
  name: string;
  description: string;
  role_definition: string;
  tool_whitelist: string[];
  origin: string;
  reason: string;
  current_version: number;
  is_active: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export interface ZoneEntriesResponse {
  items: BrainMemoryEntry[];
  total: number;
  limit: number;
  offset: number;
}

export interface SegmentsResponse {
  items: BrainSegment[];
  total: number;
  limit: number;
  offset: number;
}

export interface SpecialistsResponse {
  items: BrainSpecialist[];
  total: number;
  limit: number;
  offset: number;
}

export interface EvolutionChainResponse {
  chain: BrainMemoryEntry[];
}

export interface SkillPoolItem {
  tool_id: string;
  name: string;
  description: string;
}

export interface SkillPoolResponse {
  skills: SkillPoolItem[];
}

export interface AffectedSpecialist {
  specialist_id: string;
  name: string;
}

export class SkillPoolRemovalConflict extends Error {
  readonly toolId: string;
  readonly affectedSpecialists: AffectedSpecialist[];

  constructor(toolId: string, affectedSpecialists: AffectedSpecialist[]) {
    super("skill_in_use");
    this.name = "SkillPoolRemovalConflict";
    this.toolId = toolId;
    this.affectedSpecialists = affectedSpecialists;
  }
}

export interface SpecialistVersion {
  version_id: string;
  specialist_id: string;
  version: number;
  name: string;
  description: string;
  role_definition: string;
  tool_whitelist: string[];
  changed_by: string;
  change_reason: string | null;
  changed_at: string | null;
}

// ═══════════════════════════════════════════════
// Zone APIs
// ═══════════════════════════════════════════════

export function getBrainZones(): Promise<{ zones: BrainZoneSummary[] }> {
  return requestJson<{ zones: BrainZoneSummary[] }>('/api/brain/zones');
}

export function getZoneEntries(
  zone: BrainZone,
  options: { limit?: number; offset?: number; status?: BrainEntryStatus } = {},
): Promise<ZoneEntriesResponse> {
  const params = new URLSearchParams({
    limit: String(options.limit ?? 50),
    offset: String(options.offset ?? 0),
  });
  if (options.status) {
    params.set('status', options.status);
  }
  return requestJson<ZoneEntriesResponse>(
    `/api/brain/zones/${encodeURIComponent(zone)}/entries?${params}`,
  );
}

export function editBrainEntry(
  entryId: string,
  body: { content: string; scope?: string },
): Promise<BrainMemoryEntry> {
  return requestJson<BrainMemoryEntry>(
    `/api/brain/entries/${encodeURIComponent(entryId)}`,
    { method: 'PUT', body: JSON.stringify(body) },
  );
}

export function deleteBrainEntry(entryId: string): Promise<void> {
  return requestJson<void>(
    `/api/brain/entries/${encodeURIComponent(entryId)}`,
    { method: 'DELETE' },
  );
}

export function getEntryEvolution(entryId: string): Promise<EvolutionChainResponse> {
  return requestJson<EvolutionChainResponse>(
    `/api/brain/entries/${encodeURIComponent(entryId)}/evolution`,
  );
}

// ═══════════════════════════════════════════════
// Segment APIs
// ═══════════════════════════════════════════════

export function getBrainSegments(
  options: { limit?: number; offset?: number; status?: BrainSegmentStatus | 'all' } = {},
): Promise<SegmentsResponse> {
  const params = new URLSearchParams({
    limit: String(options.limit ?? 20),
    offset: String(options.offset ?? 0),
    status: options.status ?? 'all',
  });
  return requestJson<SegmentsResponse>(`/api/brain/segments?${params}`);
}

export function retryBrainSegment(segmentId: string): Promise<{ segment_id: string; status: BrainSegmentStatus }> {
  return requestJson<{ segment_id: string; status: BrainSegmentStatus }>(
    `/api/brain/segments/${encodeURIComponent(segmentId)}/retry`,
    { method: 'POST' },
  );
}

export function isBrainZone(value: unknown): value is BrainZone {
  return (
    value === 'hot' ||
    value === 'persistent' ||
    value === 'archive' ||
    value === 'subconscious' ||
    value === 'failure' ||
    value === 'prediction'
  );
}

// ═══════════════════════════════════════════════
// Specialist APIs
// ═══════════════════════════════════════════════

export function listSpecialists(
  options: { limit?: number; offset?: number; activeOnly?: boolean } = {},
): Promise<SpecialistsResponse> {
  const params = new URLSearchParams({
    limit: String(options.limit ?? 50),
    offset: String(options.offset ?? 0),
    active_only: String(options.activeOnly ?? true),
  });
  return requestJson<SpecialistsResponse>(`/api/brain/specialists?${params}`);
}

export function getSpecialist(specialistId: string): Promise<BrainSpecialist> {
  return requestJson<BrainSpecialist>(
    `/api/brain/specialists/${encodeURIComponent(specialistId)}`,
  );
}

export function createSpecialist(body: {
  name: string;
  description: string;
  role_definition: string;
  tool_whitelist: string[];
}): Promise<BrainSpecialist> {
  return requestJson<BrainSpecialist>('/api/brain/specialists', {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export function updateSpecialist(
  specialistId: string,
  body: {
    name?: string;
    description?: string;
    role_definition?: string;
    tool_whitelist?: string[];
    change_reason?: string;
  },
): Promise<BrainSpecialist> {
  return requestJson<BrainSpecialist>(
    `/api/brain/specialists/${encodeURIComponent(specialistId)}`,
    { method: 'PUT', body: JSON.stringify(body) },
  );
}

export function deleteSpecialist(specialistId: string): Promise<void> {
  return requestJson<void>(
    `/api/brain/specialists/${encodeURIComponent(specialistId)}`,
    { method: 'DELETE' },
  );
}

export function getSpecialistVersions(
  specialistId: string,
  options: { limit?: number; offset?: number } = {},
): Promise<{ items: SpecialistVersion[] }> {
  const params = new URLSearchParams({
    limit: String(options.limit ?? 20),
    offset: String(options.offset ?? 0),
  });
  return requestJson<{ items: SpecialistVersion[] }>(
    `/api/brain/specialists/${encodeURIComponent(specialistId)}/versions?${params}`,
  );
}

// ═══════════════════════════════════════════════
// Skill Pool APIs
// ═══════════════════════════════════════════════

export function getSkillPool(): Promise<SkillPoolResponse> {
  return requestJson<SkillPoolResponse>('/api/brain/skill-pool');
}

export function removeSkillFromPool(
  toolId: string,
  options: { force?: boolean } = {},
): Promise<void> {
  const params = new URLSearchParams({
    force: String(options.force ?? false),
  });
  return requestJson<void>(
    `/api/brain/skill-pool/${encodeURIComponent(toolId)}?${params}`,
    { method: 'DELETE' },
  ).catch((error: unknown) => {
    if (error instanceof DesktopApiError && error.status === 409 && error.code === "skill_in_use") {
      throw new SkillPoolRemovalConflict(
        toolId,
        parseAffectedSpecialists(error.details.affected_specialists),
      );
    }
    throw error;
  });
}

function parseAffectedSpecialists(value: unknown): AffectedSpecialist[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object")
    .map((item) => ({
      specialist_id: typeof item.specialist_id === "string" ? item.specialist_id : "",
      name: typeof item.name === "string" ? item.name : "",
    }))
    .filter((item) => item.specialist_id || item.name);
}
