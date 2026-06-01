import { cleanup, render, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, test, vi } from "vitest";

import { configureDesktopApi } from "../../src/api/client";
import { SkillMethodologyScreen } from "../../src/screens/SkillMethodologyScreen/SkillMethodologyScreen";
import { useBrainStore } from "../../src/state/brainStore";
import { useSkillMethodologyStore } from "../../src/state/skillMethodologyStore";

describe("SkillMethodologyScreen", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    useSkillMethodologyStore.setState({ hydrated: false, items: [], bootstrapWarning: null });
    useBrainStore.setState({ skillPool: [], loadingSkillPool: false });
  });

  test("does not reload the full list when an already hydrated screen remounts", async () => {
    configureDesktopApi({ baseUrl: "http://desktop.test", sessionToken: "token" });
    useSkillMethodologyStore.setState({ hydrated: true, items: [], bootstrapWarning: null });
    const fetchMock = vi.fn(async (input: unknown) => ({
      ok: true,
      json: async () => {
        if (String(input).includes("bootstrap-status")) {
          return {
            bootstrap_active_skill_id: "bootstrap.how_to_create_skill_methodology",
            fallback_used: false,
            seed_file_path: "seed.md",
            last_seed_check_at: "2026-05-31T00:00:00Z",
          };
        }
        return { skills: [] };
      },
    }));
    vi.stubGlobal("fetch", fetchMock);

    // 每次 mount 触发 loadBootstrapStatus + loadSkillPool 共 2 次 fetch
    const first = render(<SkillMethodologyScreen />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    first.unmount();
    render(<SkillMethodologyScreen />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(4));

    const urls = (fetchMock.mock.calls as unknown as Array<[string, ...unknown[]]>).map(([input]) => String(input));
    // 方法论列表接口（hydrated=true 时不应调用）
    expect(urls.every((url) => !url.match(/\/api\/skills\/methodology\?/))).toBe(true);
    // 每次 mount 应调用 bootstrap-status 和 skill-pool
    expect(urls.filter((url) => url.includes("bootstrap-status"))).toHaveLength(2);
    expect(urls.filter((url) => url.includes("skill-pool"))).toHaveLength(2);
  });
});
