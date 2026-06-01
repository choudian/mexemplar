import { waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { configureDesktopApi } from "../../src/api/client";
import type { EntityEquipmentResponse, SkillDetail, SkillMethodologySummary } from "../../src/api/skillsMethodology";
import { useSkillMethodologyStore } from "../../src/state/skillMethodologyStore";

function jsonResponse(payload: unknown) {
  return {
    ok: true,
    json: async () => payload,
  };
}

const alpha: SkillMethodologySummary = {
  skill_id: "sk_alpha",
  name: "Alpha Method",
  description: "Alpha flow",
  trigger_conditions: ["用户要求做 alpha"],
  required_tools: ["tool_mail"],
  version: 1,
  chain_root_id: "sk_alpha",
  origin: "assistant_tool_call",
  is_protected: false,
  loaded_count: 2,
  referenced_count: 0,
  equipped_count: 1,
  last_referenced_at: null,
  created_at: "2026-05-20T00:00:00Z",
};

const beta: SkillMethodologySummary = {
  skill_id: "sk_beta",
  name: "Beta Method",
  description: "Beta flow",
  trigger_conditions: ["用户要求做 beta"],
  required_tools: [],
  version: 1,
  chain_root_id: "sk_beta",
  origin: "user_edit",
  is_protected: false,
  loaded_count: 5,
  referenced_count: 3,
  equipped_count: 2,
  last_referenced_at: "2026-05-27T00:00:00Z",
  created_at: "2026-05-21T00:00:00Z",
};

const alphaDetail: SkillDetail = {
  ...alpha,
  body_markdown: "# Alpha\n\nFollow alpha steps.",
  parent_skill_id: null,
  status: "active",
  source_segments: [
    {
      segment_id: "seg_1",
      source_zone: "archive",
      segment_summary: "Alpha source",
      segment_status: "active",
    },
  ],
};

const equipment: EntityEquipmentResponse = {
  entity_type: "specialist",
  entity_id: "spec-1",
  entity_name: "报表专员",
  tool_whitelist: ["tool_mail"],
  active_equipment: [
    {
      skill_id: "sk_alpha",
      chain_root_id: "sk_alpha",
      name: "Alpha Method",
      description: "Alpha flow",
      trigger_conditions: ["用户要求做 alpha"],
      required_tools: ["tool_mail"],
      missing_required_tools: [],
      equipped_order: 0,
      equipped_at: "2026-05-20T00:00:00Z",
    },
  ],
  token_budget_estimate: 123,
  token_budget_thresholds: { warn_threshold: 111, danger_threshold: 222 },
};

function resetStore(): void {
  useSkillMethodologyStore.setState({
    hydrated: false,
    items: [],
    selectedSkillId: null,
    selectedDetail: null,
    history: null,
    equipmentAudit: null,
    equipmentByEntity: {},
    tokenBudgetThresholds: null,
    sortKey: "recently_changed",
    filterKey: "all",
    editDraft: {
      skill_id: null,
      name: "",
      description: "",
      trigger_conditions: [""],
      required_tools: [],
      body_markdown: "",
      change_reason: "",
    },
    unreadBadgeCount: 0,
    loading: false,
    loadingDetail: false,
    saving: false,
    lastError: null,
    bootstrapWarning: null,
  });
}

describe("skillMethodologyStore", () => {
  beforeEach(() => {
    configureDesktopApi({ baseUrl: "http://desktop.test", sessionToken: "token" });
    resetStore();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("loads, selects, edits, soft-deletes, tracks sort/filter, unread badge, and equipment thresholds", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/skills/methodology?sort=recently_changed")) {
        return jsonResponse({ items: [alpha, beta] });
      }
      if (url.endsWith("/api/skills/methodology/sk_alpha") && init?.method === "PUT") {
        const body = JSON.parse(String(init.body));
        return jsonResponse({
          ...alphaDetail,
          name: body.name,
          description: body.description,
          trigger_conditions: body.trigger_conditions,
          required_tools: body.required_tools,
          body_markdown: body.body_markdown,
        });
      }
      if (url.endsWith("/api/skills/methodology/sk_alpha")) {
        return jsonResponse(alphaDetail);
      }
      if (url.endsWith("/api/skills/methodology/sk_alpha/history")) {
        return jsonResponse({ chain_root_id: "sk_alpha", nodes: [{ ...alphaDetail, change_reason: "initial" }] });
      }
      if (url.endsWith("/api/skills/methodology/sk_alpha/audit-equipment")) {
        return jsonResponse({ skill_id: "sk_alpha", rows: [] });
      }
      if (url.endsWith("/api/skills/methodology/sk_alpha/soft-delete")) {
        return jsonResponse({ deleted_skill_id: "sk_alpha", pruned_equipment_count: 1, affected_specialist_ids: ["spec-1"] });
      }
      if (url.endsWith("/api/specialists/spec-1/equipment") && init?.method === "PUT") {
        return jsonResponse({ active_equipment_count: 2, newly_equipped: ["sk_beta"], newly_unequipped: [] });
      }
      if (url.endsWith("/api/specialists/spec-1/equipment")) {
        return jsonResponse(equipment);
      }
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);

    await useSkillMethodologyStore.getState().load();
    expect(useSkillMethodologyStore.getState().items.map((item) => item.skill_id)).toEqual(["sk_alpha", "sk_beta"]);

    useSkillMethodologyStore.getState().setSortKey("loaded_count");
    useSkillMethodologyStore.getState().setFilterKey("never_referenced");
    expect(useSkillMethodologyStore.getState().sortKey).toBe("loaded_count");
    expect(useSkillMethodologyStore.getState().filterKey).toBe("never_referenced");

    await useSkillMethodologyStore.getState().selectSkill("sk_alpha");
    expect(useSkillMethodologyStore.getState().editDraft.name).toBe("Alpha Method");

    useSkillMethodologyStore.getState().setDraftField("name", "Alpha Method Updated");
    useSkillMethodologyStore.getState().setDraftField("trigger_conditions", ["  用户要求做 alpha  ", ""]);
    useSkillMethodologyStore.getState().setDraftField("required_tools", [" tool_mail ", ""]);
    useSkillMethodologyStore.getState().setDraftField("change_reason", "");
    expect(await useSkillMethodologyStore.getState().saveDraft()).toBe(true);

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "http://desktop.test/api/skills/methodology/sk_alpha",
        expect.objectContaining({
          method: "PUT",
          body: JSON.stringify({
            name: "Alpha Method Updated",
            description: "Alpha flow",
            trigger_conditions: ["用户要求做 alpha"],
            required_tools: ["tool_mail"],
            body_markdown: "# Alpha\n\nFollow alpha steps.",
            change_reason: "通过 SkillScreen 编辑",
          }),
        }),
      ),
    );

    await useSkillMethodologyStore.getState().loadEquipment("spec-1");
    expect(useSkillMethodologyStore.getState().tokenBudgetThresholds).toEqual({ warn_threshold: 111, danger_threshold: 222 });

    expect(await useSkillMethodologyStore.getState().saveEquipment("spec-1", ["sk_alpha", "sk_beta"])).toBe(true);
    expect(fetchMock).toHaveBeenCalledWith(
      "http://desktop.test/api/specialists/spec-1/equipment",
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({
          skills: [
            { skill_id: "sk_alpha", equipped_order: 0 },
            { skill_id: "sk_beta", equipped_order: 1 },
          ],
        }),
      }),
    );

    useSkillMethodologyStore.getState().applyEvent({
      eventId: "evt_skill_1",
      sequence: 1,
      sessionId: "ui-1",
      type: "skill.changed",
      scope: { skillId: "sk_alpha" },
      payload: { reason: "user_edit", skillId: "sk_alpha", chainRootId: "sk_alpha" },
      createdAt: new Date().toISOString(),
    });
    expect(useSkillMethodologyStore.getState().unreadBadgeCount).toBe(1);
    const callsBeforeRefresh = fetchMock.mock.calls.length;
    await waitFor(() => expect(fetchMock.mock.calls.length).toBeGreaterThan(callsBeforeRefresh));
    useSkillMethodologyStore.getState().dismissUnread();
    expect(useSkillMethodologyStore.getState().unreadBadgeCount).toBe(0);

    fetchMock.mockClear();
    useSkillMethodologyStore.getState().applyEvent({
      eventId: "evt_equipment_1",
      sequence: 2,
      sessionId: "ui-1",
      type: "skill.equipment.changed",
      scope: { entityId: "spec-1", skillId: "sk_alpha" },
      payload: { changeType: "equipped", entityType: "specialist", entityId: "spec-1", skillId: "sk_alpha" },
      createdAt: new Date().toISOString(),
    });
    await waitFor(() => {
      const paths = fetchMock.mock.calls.map(([input]) => String(input));
      expect(paths.some((path) => path.endsWith("/api/specialists/spec-1/equipment"))).toBe(true);
      expect(paths.some((path) => path.endsWith("/api/skills/methodology?sort=recently_changed"))).toBe(true);
    });

    expect(await useSkillMethodologyStore.getState().softDeleteSelected()).toBe(true);
    expect(fetchMock).toHaveBeenCalledWith(
      "http://desktop.test/api/skills/methodology/sk_alpha/soft-delete",
      expect.objectContaining({ method: "POST" }),
    );
    expect(useSkillMethodologyStore.getState().selectedSkillId).toBeNull();
  });
});
