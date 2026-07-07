import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { configureDesktopApi } from "../../src/api/client";
import { SkillStoreTab } from "../../src/screens/skills/SkillStoreTab";
import { useSkillStoreStore } from "../../src/state/skillStoreStore";

function jsonResponse(payload: unknown): Response {
  return { ok: true, json: async () => payload } as Response;
}

async function settle(): Promise<void> {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
}

const summary = {
  sourceRef: "acme/frontend-design",
  name: "frontend-design",
  source: "acme",
  installs: 1200,
  sourceUrl: "https://skills.sh/acme/frontend-design",
  installed: false,
};

const preview = {
  sourceType: "skills_sh",
  sourceRef: "acme/frontend-design",
  name: "frontend-design",
  sourceUrl: "https://skills.sh/acme/frontend-design",
  skillMd: "# Frontend Design\n\nDo good design.",
  files: [{ path: "SKILL.md", size: 420 }],
  audit: { status: "available", result: { verdict: "clean" } },
  installable: true,
  reason: null,
  installed: false,
};

function resetStore(): void {
  useSkillStoreStore.setState({
    items: [],
    sourceAvailable: true,
    sourceMessage: null,
    query: "",
    loading: false,
    installed: [],
    githubSkills: [],
    githubMessage: null,
    discoveringGithub: false,
    preview: null,
    previewLoading: false,
    installing: false,
    lastError: null,
  });
}

describe("skill store tab", () => {
  beforeEach(() => {
    configureDesktopApi({ baseUrl: "http://desktop.test", sessionToken: "token" });
    resetStore();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  test("renders curated results and opens preview with audit info", async () => {
    let installCalls = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/api/skill-store/search")) {
        return jsonResponse({
          items: [{ ...summary, installed: installCalls > 0 }],
          sourceAvailable: true,
          message: null,
        });
      }
      if (url.includes("/api/skill-store/installed")) {
        return jsonResponse({ items: [] });
      }
      if (url.includes("/api/skill-store/preview")) {
        expect(init?.method).toBe("POST");
        return jsonResponse(preview);
      }
      if (url.includes("/api/skill-store/install")) {
        installCalls += 1;
        return jsonResponse({ installId: "esi_1", skillId: "sk_1" });
      }
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<SkillStoreTab />);
    await settle();

    await waitFor(() => expect(screen.getByText("frontend-design")).toBeInTheDocument());
    expect(screen.getByText("1,200 次安装")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /查看/ }));
    await waitFor(() => expect(screen.getByRole("dialog", { name: "技能预览" })).toBeInTheDocument());

    const dialog = within(screen.getByRole("dialog", { name: "技能预览" }));
    expect(dialog.getByText("已审计")).toBeInTheDocument();
    expect(dialog.getByText("Do good design.")).toBeInTheDocument();
    expect(dialog.getByText("SKILL.md")).toBeInTheDocument();

    fireEvent.click(dialog.getByRole("button", { name: "安装" }));
    await waitFor(() => expect(installCalls).toBe(1));
    // 安装成功后弹层关闭，列表刷新为已安装
    await waitFor(() =>
      expect(screen.queryByRole("dialog", { name: "技能预览" })).not.toBeInTheDocument(),
    );
    await waitFor(() => expect(screen.getByText("已安装")).toBeInTheDocument());
  });

  test("github flow shows unaudited warning in preview", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/skill-store/search")) {
        return jsonResponse({ items: [], sourceAvailable: true, message: null });
      }
      if (url.includes("/api/skill-store/installed")) {
        return jsonResponse({ items: [] });
      }
      if (url.includes("/api/skill-store/discover-github")) {
        return jsonResponse({
          skills: [{ sourceRef: "o/r", name: "r", path: "SKILL.md" }],
          message: null,
        });
      }
      if (url.includes("/api/skill-store/preview")) {
        return jsonResponse({
          ...preview,
          sourceType: "github",
          sourceRef: "o/r",
          audit: { status: "unaudited" },
        });
      }
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<SkillStoreTab />);
    await settle();

    fireEvent.change(screen.getByLabelText("GitHub 仓库"), { target: { value: "o/r" } });
    fireEvent.click(screen.getByRole("button", { name: "查找技能" }));

    const githubList = await screen.findByLabelText("GitHub 发现结果");
    fireEvent.click(within(githubList).getByRole("button", { name: /查看/ }));

    await waitFor(() => expect(screen.getByRole("dialog", { name: "技能预览" })).toBeInTheDocument());
    const dialog = within(screen.getByRole("dialog", { name: "技能预览" }));
    expect(dialog.getByText(/未经技能市场安全审计/)).toBeInTheDocument();
  });

  test("degrades gracefully when marketplace is unavailable", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/skill-store/search")) {
        return jsonResponse({
          items: [],
          sourceAvailable: false,
          message: "技能市场暂时无法访问，请稍后重试。",
        });
      }
      if (url.includes("/api/skill-store/installed")) {
        return jsonResponse({ items: [] });
      }
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<SkillStoreTab />);
    await settle();

    await waitFor(() =>
      expect(screen.getByText("技能市场暂时无法访问，请稍后重试。")).toBeInTheDocument(),
    );
  });

  test("methodology screen exposes store view", async () => {
    const { SkillMethodologyScreen } = await import(
      "../../src/screens/SkillMethodologyScreen/SkillMethodologyScreen"
    );
    const { useBrainStore } = await import("../../src/state/brainStore");
    const { useSkillMethodologyStore } = await import("../../src/state/skillMethodologyStore");
    useBrainStore.setState({ skillPool: [], loadingSkillPool: false });
    useSkillMethodologyStore.setState({ hydrated: true, items: [], bootstrapWarning: null });

    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/skill-store/search")) {
        return jsonResponse({ items: [], sourceAvailable: true, message: null });
      }
      if (url.includes("/api/skill-store/installed")) {
        return jsonResponse({ items: [] });
      }
      if (url.includes("/api/skills/methodology/bootstrap-status")) {
        return jsonResponse({
          bootstrap_active_skill_id: "bootstrap.how_to_create_skill_methodology",
          fallback_used: false,
          seed_file_path: "seed.md",
          last_seed_check_at: "2026-05-31T00:00:00Z",
        });
      }
      if (url.includes("/api/brain/skill-pool")) {
        return jsonResponse({ skills: [] });
      }
      return jsonResponse({ skills: [] });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<SkillMethodologyScreen />);
    await settle();

    fireEvent.click(screen.getByRole("button", { name: "技能商店" }));
    await waitFor(() =>
      expect(screen.getByLabelText("搜索技能市场")).toBeInTheDocument(),
    );
  });

  test("skill list screen no longer exposes store tab", async () => {
    const { SkillListScreen } = await import("../../src/screens/skills/SkillListScreen");
    const { useSkillsStore } = await import("../../src/state/skillsStore");
    useSkillsStore.setState({ hydrated: true });

    render(<SkillListScreen />);

    expect(screen.queryByRole("tab", { name: "技能商店" })).not.toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "MCP 工具" })).toBeInTheDocument();
  });
});
