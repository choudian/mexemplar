import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { useSettingsStore } from "../../src/state/settingsStore";

// Saving a secret used to call load(), which reset draftValues to the backend's
// values and cleared dirtyKeys. Anyone who filled provider/model/base_url and
// then clicked "保存密钥" first lost those edits and found "保存全部" greyed out.
vi.mock("../../src/api/settings", () => ({
  writeSettingSecret: vi.fn(async () => ({ present: true, masked: "sk_***" })),
  deleteSettingSecret: vi.fn(async () => ({ present: false, masked: "" })),
  getSettingsSchema: vi.fn(),
  getSettingsValues: vi.fn(),
  updateSettingsValues: vi.fn(),
  runSettingAction: vi.fn(),
}));

function seedUnsavedEdits() {
  useSettingsStore.setState({
    values: { "ai.base_url": "https://api.anthropic.com" },
    draftValues: { "ai.base_url": "https://open.bigmodel.cn/api/coding/paas/v4" },
    dirtyKeys: ["ai.base_url"],
    secrets: {},
    validationErrors: {},
    busy: false,
  });
}

describe("saving a secret leaves other unsaved edits intact", () => {
  beforeEach(() => {
    seedUnsavedEdits();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  test("writeSecret keeps the pending base_url draft and its dirty flag", async () => {
    await useSettingsStore.getState().writeSecret("ai.api_key", "my-real-key");

    const state = useSettingsStore.getState();
    expect(state.draftValues["ai.base_url"]).toBe(
      "https://open.bigmodel.cn/api/coding/paas/v4",
    );
    expect(state.dirtyKeys).toContain("ai.base_url");
    // The secret itself did update.
    expect(state.secrets["ai.api_key"]).toEqual({ present: true, masked: "sk_***" });
  });

  test("deleteSecret also leaves pending drafts intact", async () => {
    await useSettingsStore.getState().deleteSecret("ai.api_key");

    const state = useSettingsStore.getState();
    expect(state.dirtyKeys).toContain("ai.base_url");
    expect(state.secrets["ai.api_key"]).toEqual({ present: false, masked: "" });
  });

  test("an empty secret is rejected without touching drafts", async () => {
    await useSettingsStore.getState().writeSecret("ai.api_key", "   ");

    const state = useSettingsStore.getState();
    expect(state.dirtyKeys).toContain("ai.base_url");
    expect(state.validationErrors["ai.api_key"]).toBe("密钥不能为空。");
  });

  test("saving a secret leaves no blank error key that would block 保存全部", async () => {
    // saveValues bails when Object.keys(validationErrors).length > 0. A blank
    // "" error left under the secret key counts as 1, so "保存全部" could never
    // fire after saving a key — exactly the reported bug.
    await useSettingsStore.getState().writeSecret("ai.api_key", "my-real-key");

    const errors = useSettingsStore.getState().validationErrors;
    expect(Object.keys(errors)).not.toContain("ai.api_key");
    expect(Object.keys(errors).length).toBe(0);
  });
});
