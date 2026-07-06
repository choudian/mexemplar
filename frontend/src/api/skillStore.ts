import { requestJson } from "./client";

export interface StoreSkillSummary {
  sourceRef: string;
  name: string;
  source: string;
  installs: number;
  sourceUrl: string;
  installed: boolean;
}

export interface StoreSearchResponse {
  items: StoreSkillSummary[];
  sourceAvailable: boolean;
  message: string | null;
}

export interface DiscoveredGithubSkill {
  sourceRef: string;
  name: string;
  path: string;
}

export interface DiscoverGithubResponse {
  skills: DiscoveredGithubSkill[];
  message: string | null;
}

export interface StoreSkillPreview {
  sourceType: "skills_sh" | "github";
  sourceRef: string;
  name: string;
  sourceUrl: string;
  skillMd: string;
  files: Array<{ path: string; size: number }>;
  audit: { status: string; result?: Record<string, unknown> };
  installable: boolean;
  reason: string | null;
  installed: boolean;
}

export interface InstalledExternalSkill {
  installId: string;
  skillId: string;
  name: string;
  sourceType: string;
  sourceRef: string;
  sourceUrl: string;
  installedAt: string;
}

export async function searchStoreSkills(query: string, limit = 30): Promise<StoreSearchResponse> {
  const params = new URLSearchParams({ q: query, limit: String(limit) });
  return requestJson<StoreSearchResponse>(`/api/skill-store/search?${params}`);
}

export async function discoverGithubSkills(repo: string): Promise<DiscoverGithubResponse> {
  return requestJson<DiscoverGithubResponse>("/api/skill-store/discover-github", {
    method: "POST",
    body: JSON.stringify({ repo }),
  });
}

export async function previewStoreSkill(
  sourceType: "skills_sh" | "github",
  sourceRef: string,
): Promise<StoreSkillPreview> {
  return requestJson<StoreSkillPreview>("/api/skill-store/preview", {
    method: "POST",
    body: JSON.stringify({ sourceType, sourceRef }),
  });
}

export async function installStoreSkill(
  sourceType: "skills_sh" | "github",
  sourceRef: string,
): Promise<{ installId: string; skillId: string }> {
  return requestJson("/api/skill-store/install", {
    method: "POST",
    body: JSON.stringify({ sourceType, sourceRef }),
  });
}

export async function listInstalledExternalSkills(): Promise<{
  items: InstalledExternalSkill[];
}> {
  return requestJson("/api/skill-store/installed");
}

export async function uninstallExternalSkill(installId: string): Promise<{ removed: boolean }> {
  return requestJson(`/api/skill-store/${installId}/uninstall`, { method: "POST" });
}
