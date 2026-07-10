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
          advanced: false,
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
          advanced: false,
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
          advanced: false,
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
          advanced: false,
        },
      ],
    },
    {
      id: "tool_output",
      label: "工具输出",
      items: [
        {
          key: "agent_tools.output.semantic_summary.enabled",
          label: "语义摘要",
          section: "tool_output",
          valueKind: "boolean",
          description: "",
          options: [],
          validationRules: {},
          status: "available",
          advanced: false,
        },
        {
          key: "agent_tools.output.semantic_summary.model",
          label: "摘要模型",
          section: "tool_output",
          valueKind: "string",
          description: "",
          options: [],
          validationRules: {},
          status: "available",
          advanced: false,
        },
        {
          key: "agent_tools.output.semantic_summary.api_key",
          label: "摘要 API Key",
          section: "tool_output",
          valueKind: "secret",
          description: "",
          options: [],
          validationRules: {},
          status: "available",
          advanced: false,
        },
        {
          key: "agent_tools.output.semantic_summary.trigger_chars",
          label: "触发字符数",
          section: "tool_output",
          valueKind: "integer",
          description: "",
          options: [],
          validationRules: { min: 1000, max: 1000000 },
          status: "available",
          advanced: true,
        },
      ],
      actions: [
        {
          key: "test_tool_output_summary_connection",
          label: "测试摘要模型连接",
          section: "tool_output",
          valueKind: "action",
          description: "",
          options: [],
          validationRules: {},
          status: "available",
          advanced: false,
        },
      ],
    },
    {
      id: "web",
      label: "Web",
      items: [
        {
          key: "web.search_backend",
          label: "搜索后端",
          section: "web",
          valueKind: "enum",
          description: "",
          options: ["auto", "brave-free", "ddg-html", "ddgs"],
          validationRules: {},
          status: "available",
          advanced: false,
        },
        {
          key: "web.brave_api_key",
          label: "Brave Search API Key",
          section: "web",
          valueKind: "secret",
          description: "",
          options: [],
          validationRules: {},
          status: "available",
          advanced: false,
        },
      ],
      actions: [],
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
          advanced: false,
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
    let searchBackend = "auto";
    let secretPresent = false;
    let braveSecretPresent = false;
    let summaryModel = "";
    let summarySecretPresent = false;
    const settingsPayload = () => ({
      values: {
        "ai.model": model,
        "ai.timeout": 120,
        "web.search_backend": searchBackend,
        "agent_tools.output.semantic_summary.enabled": true,
        "agent_tools.output.semantic_summary.model": summaryModel,
        "agent_tools.output.semantic_summary.trigger_chars": 20000,
      },
      secrets: {
        "ai.api_key": { present: secretPresent, masked: secretPresent ? "••••••••" : "" },
        "web.brave_api_key": {
          present: braveSecretPresent,
          masked: braveSecretPresent ? "••••••••" : "",
        },
        "agent_tools.output.semantic_summary.api_key": {
          present: summarySecretPresent,
          masked: summarySecretPresent ? "••••••••" : "",
        },
      },
      status: {
        "ai.api_key": secretPresent ? "available" : "missing_secret",
        "web.brave_api_key": braveSecretPresent ? "available" : "missing_secret",
        "agent_tools.output.semantic_summary.api_key": summarySecretPresent
          ? "available"
          : "missing_secret",
      },
    });
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/settings/schema")) return jsonResponse(schemaPayload);
      if (url.endsWith("/api/settings/values") && init?.method === "PATCH") {
        const body = JSON.parse(String(init.body)) as { values: Record<string, string> };
        model = body.values["ai.model"] ?? model;
        searchBackend = body.values["web.search_backend"] ?? searchBackend;
        summaryModel = body.values["agent_tools.output.semantic_summary.model"] ?? summaryModel;
        return jsonResponse(settingsPayload());
      }
      if (url.endsWith("/api/settings/values")) {
        return jsonResponse(settingsPayload());
      }
      if (url.endsWith("/api/settings/secrets/ai.api_key") && init?.method === "POST") {
        secretPresent = true;
        return jsonResponse({ secretKey: "ai.api_key", present: true, masked: "••••••••" });
      }
      if (url.endsWith("/api/settings/secrets/ai.api_key") && init?.method === "DELETE") {
        secretPresent = false;
        return jsonResponse({ secretKey: "ai.api_key", present: false, masked: "" });
      }
      if (url.endsWith("/api/settings/secrets/web.brave_api_key") && init?.method === "POST") {
        braveSecretPresent = true;
        return jsonResponse({ secretKey: "web.brave_api_key", present: true, masked: "••••••••" });
      }
      if (url.endsWith("/api/settings/secrets/web.brave_api_key") && init?.method === "DELETE") {
        braveSecretPresent = false;
        return jsonResponse({ secretKey: "web.brave_api_key", present: false, masked: "" });
      }
      if (url.endsWith("/api/settings/secrets/agent_tools.output.semantic_summary.api_key") && init?.method === "POST") {
        summarySecretPresent = true;
        return jsonResponse({
          secretKey: "agent_tools.output.semantic_summary.api_key",
          present: true,
          masked: "••••••••",
        });
      }
      if (url.endsWith("/api/settings/secrets/agent_tools.output.semantic_summary.api_key") && init?.method === "DELETE") {
        summarySecretPresent = false;
        return jsonResponse({
          secretKey: "agent_tools.output.semantic_summary.api_key",
          present: false,
          masked: "",
        });
      }
      if (url.endsWith("/api/settings/actions/test_tool_output_summary_connection")) {
        if (!summarySecretPresent) {
          return jsonResponse({
            actionName: "test_tool_output_summary_connection",
            status: "failed",
            message: "缺少摘要 API Key。",
            details: { provider: "openai", model: "summary-model", code: "missing_secret" },
          });
        }
        return jsonResponse({
          actionName: "test_tool_output_summary_connection",
          status: "completed",
          message: "摘要模型连接成功。",
          details: { provider: "openai", model: "summary-model" },
        });
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
    fireEvent.click(screen.getByRole("button", { name: "保存 API Key" }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "http://desktop.test/api/settings/secrets/ai.api_key",
        expect.objectContaining({ method: "POST" }),
      ),
    );
    expect(document.body.textContent).not.toContain("sk-secret-value");
    expect(await screen.findByText("已保存")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "删除 API Key" }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "http://desktop.test/api/settings/secrets/ai.api_key",
        expect.objectContaining({ method: "DELETE" }),
      ),
    );

    fireEvent.click(screen.getByRole("tab", { name: "Web" }));
    fireEvent.change(screen.getByLabelText("搜索后端"), { target: { value: "brave-free" } });
    fireEvent.click(screen.getByRole("button", { name: /保存设置/ }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "http://desktop.test/api/settings/values",
        expect.objectContaining({
          method: "PATCH",
          body: JSON.stringify({ values: { "web.search_backend": "brave-free" } }),
        }),
      ),
    );

    fireEvent.change(screen.getByLabelText("Brave Search API Key"), { target: { value: "brave-secret-value" } });
    fireEvent.click(screen.getByRole("button", { name: "保存 Brave Search API Key" }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "http://desktop.test/api/settings/secrets/web.brave_api_key",
        expect.objectContaining({ method: "POST" }),
      ),
    );
    expect(document.body.textContent).not.toContain("brave-secret-value");

    fireEvent.click(screen.getByRole("button", { name: "删除 Brave Search API Key" }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "http://desktop.test/api/settings/secrets/web.brave_api_key",
        expect.objectContaining({ method: "DELETE" }),
      ),
    );

    fireEvent.click(screen.getByRole("tab", { name: "工具输出" }));
    expect(screen.getByLabelText("触发字符数")).not.toBeVisible();
    fireEvent.click(screen.getByText("高级参数"));
    expect(screen.getByLabelText("触发字符数")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("摘要模型"), { target: { value: "summary-model" } });
    fireEvent.click(screen.getByRole("button", { name: /保存设置/ }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "http://desktop.test/api/settings/values",
        expect.objectContaining({
          method: "PATCH",
          body: JSON.stringify({
            values: { "agent_tools.output.semantic_summary.model": "summary-model" },
          }),
        }),
      ),
    );
    fireEvent.change(screen.getByLabelText("摘要 API Key"), { target: { value: "sk-summary" } });
    fireEvent.click(screen.getByRole("button", { name: "保存 摘要 API Key" }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "http://desktop.test/api/settings/secrets/agent_tools.output.semantic_summary.api_key",
        expect.objectContaining({ method: "POST" }),
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: /执行/ }));
    await waitFor(() => expect(screen.getByText("摘要模型连接成功。")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "删除 摘要 API Key" }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "http://desktop.test/api/settings/secrets/agent_tools.output.semantic_summary.api_key",
        expect.objectContaining({ method: "DELETE" }),
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: /执行/ }));
    await waitFor(() => expect(screen.getByText("缺少摘要 API Key。")).toBeInTheDocument());

    const aboutTab = screen.getByRole("tab", { name: "关于" });
    aboutTab.focus();
    fireEvent.keyDown(aboutTab, { key: "Enter" });
    fireEvent.click(aboutTab);
    fireEvent.click(screen.getByRole("button", { name: /执行/ }));
    await waitFor(() => expect(screen.getByText("当前构建未配置更新通道。")).toBeInTheDocument());
  });
});
