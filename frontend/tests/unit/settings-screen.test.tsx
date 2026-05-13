import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { configureDesktopApi } from "../../src/api/client";
import { SettingsScreen } from "../../src/screens/settings/SettingsScreen";
import { useSettingsStore } from "../../src/state/settingsStore";

function jsonResponse(payload: unknown) {
  return {
    ok: true,
    json: async () => payload,
  };
}

const schemaPayload = {
  sections: [
    {
      id: "ai",
      label: "AI",
      items: [
        {
          key: "ai.model",
          label: "主模型",
          section: "ai",
          valueKind: "string",
          description: "",
          options: [],
          validationRules: { required: true },
          status: "available",
        },
        {
          key: "ai.timeout",
          label: "请求超时",
          section: "ai",
          valueKind: "integer",
          description: "",
          options: [],
          validationRules: { min: 1, max: 600 },
          status: "available",
        },
        {
          key: "ai.api_key",
          label: "API Key",
          section: "ai",
          valueKind: "secret",
          description: "",
          options: [],
          validationRules: {},
          status: "available",
        },
      ],
      actions: [
        {
          key: "test_ai_connection",
          label: "测试 AI 连接",
          section: "ai",
          valueKind: "action",
          description: "",
          options: [],
          validationRules: {},
          status: "available",
        },
      ],
    },
    {
      id: "about",
      label: "关于",
      items: [],
      actions: [
        {
          key: "check_updates",
          label: "检查更新",
          section: "about",
          valueKind: "action",
          description: "",
          options: [],
          validationRules: {},
          status: "available",
        },
      ],
    },
  ],
};

describe("SettingsScreen", () => {
  beforeEach(() => {
    configureDesktopApi({ baseUrl: "http://desktop.test", sessionToken: "token" });
    useSettingsStore.setState({
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
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("loads settings, validates values, saves non-secrets, masks secrets, and runs actions", async () => {
    let model = "claude-sonnet-4-20250514";
    let secretPresent = false;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/settings/schema")) return jsonResponse(schemaPayload);
      if (url.endsWith("/api/settings/values") && init?.method === "PATCH") {
        const body = JSON.parse(String(init.body)) as { values: Record<string, string> };
        model = body.values["ai.model"] ?? model;
        return jsonResponse({
          values: { "ai.model": model, "ai.timeout": 120 },
          secrets: { "ai.api_key": { present: secretPresent, masked: secretPresent ? "••••••••" : "" } },
          status: { "ai.api_key": secretPresent ? "available" : "missing_secret" },
        });
      }
      if (url.endsWith("/api/settings/values")) {
        return jsonResponse({
          values: { "ai.model": model, "ai.timeout": 120 },
          secrets: { "ai.api_key": { present: secretPresent, masked: secretPresent ? "••••••••" : "" } },
          status: { "ai.api_key": secretPresent ? "available" : "missing_secret" },
        });
      }
      if (url.endsWith("/api/settings/secrets/ai.api_key") && init?.method === "POST") {
        secretPresent = true;
        return jsonResponse({ secretKey: "ai.api_key", present: true, masked: "••••••••" });
      }
      if (url.endsWith("/api/settings/secrets/ai.api_key") && init?.method === "DELETE") {
        secretPresent = false;
        return jsonResponse({ secretKey: "ai.api_key", present: false, masked: "" });
      }
      if (url.endsWith("/api/settings/actions/check_updates")) {
        return jsonResponse({
          actionName: "check_updates",
          status: "unavailable",
          message: "当前构建未配置更新通道。",
          details: {},
        });
      }
      return jsonResponse({
        actionName: "test_ai_connection",
        status: "completed",
        message: "AI 连接配置可用。",
        details: {},
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<SettingsScreen />);

    await waitFor(() => expect(screen.getByLabelText("主模型")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText("请求超时"), { target: { value: "0" } });
    expect(screen.getByText("不能小于 1。")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("请求超时"), { target: { value: "120" } });
    fireEvent.change(screen.getByLabelText("主模型"), { target: { value: "gpt-5.1" } });
    fireEvent.click(screen.getByRole("button", { name: /保存设置/ }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "http://desktop.test/api/settings/values",
        expect.objectContaining({
          method: "PATCH",
          body: JSON.stringify({ values: { "ai.model": "gpt-5.1" } }),
        }),
      ),
    );

    fireEvent.change(screen.getByLabelText("API Key"), { target: { value: "sk-secret-value" } });
    fireEvent.click(screen.getByRole("button", { name: /保存密钥/ }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "http://desktop.test/api/settings/secrets/ai.api_key",
        expect.objectContaining({ method: "POST" }),
      ),
    );
    expect(document.body.textContent).not.toContain("sk-secret-value");
    expect(await screen.findByText("已保存")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "删除密钥" }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "http://desktop.test/api/settings/secrets/ai.api_key",
        expect.objectContaining({ method: "DELETE" }),
      ),
    );

    const aboutTab = screen.getByRole("tab", { name: "关于" });
    aboutTab.focus();
    fireEvent.keyDown(aboutTab, { key: "Enter" });
    fireEvent.click(aboutTab);
    fireEvent.click(screen.getByRole("button", { name: /执行/ }));
    await waitFor(() => expect(screen.getByText("当前构建未配置更新通道。")).toBeInTheDocument());
  });
});
