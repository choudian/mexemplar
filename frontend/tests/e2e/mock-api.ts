import type { Page, Route } from "@playwright/test";

type BackendStatus = "starting" | "ready" | "degraded" | "failed" | "shutting_down";

interface MockOptions {
  backendStatus?: BackendStatus;
  backendMessage?: string;
}

interface MockRequestRecord {
  method: string;
  path: string;
  body?: unknown;
}

export interface MockApiHarness {
  requests: MockRequestRecord[];
}

const jsonHeaders = { "Content-Type": "application/json" };

function json(route: Route, payload: unknown, status = 200) {
  return route.fulfill({ status, headers: jsonHeaders, body: JSON.stringify(payload) });
}

function bootstrap(status: BackendStatus, message: string) {
  return {
    connection: {
      status,
      message,
      checks: [{ name: "sidecar", status: status === "failed" ? "failed" : "ok", message }],
      serverTime: new Date().toISOString(),
    },
    user: { displayName: "E2E User", statusLabel: "Fixture backend" },
    navigation: { pendingSkillCount: 1, publishedSkillCount: 1, failureCount: 1, compositionCount: 0 },
    settingsSummary: { theme: "light", dark: false, density: "comfy" },
    brain: { segmentIdleThresholdSeconds: 300 },
  };
}

export async function installMockApi(page: Page, options: MockOptions = {}): Promise<MockApiHarness> {
  const requests: MockRequestRecord[] = [];
  let assistantMessagePosted = false;
  let secretPresent = false;
  let settingsModel = "claude-sonnet-4-20250514";
  let compositionCounter = 0;
  let debugTraceEnabled = false;

  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    const method = request.method();
    if (!path.startsWith("/api/")) {
      return route.fallback();
    }
    let body: unknown;
    try {
      body = request.postData() ? request.postDataJSON() : undefined;
    } catch {
      body = undefined;
    }
    requests.push({ method, path, body });
    const status = options.backendStatus ?? "ready";
    const message = options.backendMessage ?? (status === "ready" ? "Desktop backend ready." : "Fixture state.");

    if (path === "/api/events") {
      return route.fulfill({ status: 204, body: "" });
    }
    if (path === "/api/bootstrap") {
      return json(route, bootstrap(status, message));
    }
    if (path === "/api/health") {
      return json(route, bootstrap(status, message).connection);
    }

    if (path === "/api/debug/control" && method === "GET") {
      return json(route, {
        enabled: debugTraceEnabled,
        armedAt: debugTraceEnabled ? "2026-05-24T00:00:00Z" : null,
        retentionEpoch: debugTraceEnabled ? "epoch_fixture" : null,
        warning: "调试记录可能包含原始用户文本",
        limits: { maxRecords: 200, maxRecordBytes: 1048576, maxTotalBytes: 16777216 },
      });
    }
    if (path === "/api/debug/control" && method === "PUT") {
      const body = request.postDataJSON() as { enabled?: boolean };
      debugTraceEnabled = Boolean(body.enabled);
      return json(route, {
        enabled: debugTraceEnabled,
        armedAt: debugTraceEnabled ? "2026-05-24T00:00:00Z" : null,
        retentionEpoch: debugTraceEnabled ? "epoch_fixture" : null,
        warning: "调试记录可能包含原始用户文本",
        limits: { maxRecords: 200, maxRecordBytes: 1048576, maxTotalBytes: 16777216 },
      });
    }
    if (path === "/api/debug/traces" && method === "GET") {
      return json(route, {
        items: debugTraceEnabled
          ? [
              {
                traceId: "trace_fixture_done",
                method: "chat",
                source: "agent_loop",
                agentType: "assistant",
                sessionId: "ast_1",
                workflowId: "wf_fixture",
                workUnitId: null,
                iteration: 1,
                outcome: "succeeded",
                detailAvailability: "full_text",
                retainedBytes: 128,
                createdAt: "2026-05-24T00:00:00Z",
                completedAt: "2026-05-24T00:00:01Z",
                summary: "text_chars:14",
                linkedTransitionIds: ["tr_fixture"],
              },
            ]
          : [],
        retainedBytes: debugTraceEnabled ? 128 : 0,
        omittedCount: 0,
        warning: "armed",
      });
    }
    if (path === "/api/debug/traces" && method === "DELETE") {
      return route.fulfill({ status: 204, headers: jsonHeaders, body: "" });
    }
    if (path === "/api/debug/traces/trace_fixture_done" && method === "GET") {
      return json(route, {
        traceId: "trace_fixture_done",
        method: "chat",
        source: "agent_loop",
        agentType: "assistant",
        sessionId: "ast_1",
        workflowId: "wf_fixture",
        workUnitId: null,
        iteration: 1,
        inputMessages: [{ role: "user", content: "fixture prompt" }],
        inputMedia: [],
        inputTools: null,
        outputContent: "fixture answer",
        outputToolCalls: [],
        outcome: "succeeded",
        errorSummary: null,
        detailAvailability: "full_text",
        retainedBytes: 128,
        linkedTransitionIds: ["tr_fixture"],
        createdAt: "2026-05-24T00:00:00Z",
        completedAt: "2026-05-24T00:00:01Z",
      });
    }
    if (path === "/api/debug/flows" && method === "GET") {
      return json(route, {
        items: [
          {
            workflowId: "wf_fixture",
            transitionCount: 1,
            lastEventType: "assistant_delegation_completed",
            lastCreatedAt: "2026-05-24T00:00:01Z",
            linkedTraceCount: 1,
          },
        ],
      });
    }
    if (path === "/api/debug/flows/wf_fixture" && method === "GET") {
      return json(route, {
        workflowId: "wf_fixture",
        transitions: [
          {
            transitionId: "tr_fixture",
            eventType: "assistant_delegation_completed",
            status: "completed",
            fromSession: { sessionId: "child", agentType: "specialist" },
            toSession: { sessionId: "ast_1", agentType: "assistant" },
            reason: "completed",
            detail: { output: { success: true } },
            detailProvenance: "ephemeral_debug_capture",
            detailAvailability: "full_text",
            traceIds: ["trace_fixture_done"],
            linkStatus: "linked",
            createdAt: "2026-05-24T00:00:01Z",
          },
        ],
      });
    }
    if (path.startsWith("/api/debug/references/") && method === "GET") {
      return json(route, {
        referenceId: decodeURIComponent(path.split("/").pop() ?? ""),
        content: "fixture expanded reference",
        available: true,
        truncated: false,
        nextChunk: null,
      });
    }

    if (path === "/api/assistant/sessions" && method === "GET") {
      return json(route, {
        items: [
          {
            sessionId: "ast_1",
            title: "E2E conversation",
            preview: "Fixture conversation",
            status: "active",
            createdAt: new Date().toISOString(),
            updatedAt: new Date().toISOString(),
            dateLabel: "2026-05-10",
          },
        ],
        hasMore: false,
      });
    }
    if (path === "/api/assistant/sessions" && method === "POST") {
      return json(route, { sessionId: "ast_1" });
    }
    if (path === "/api/assistant/sessions/ast_1" && method === "PATCH") {
      const body = request.postDataJSON() as { title?: string };
      return json(route, {
        sessionId: "ast_1",
        title: body.title ?? "E2E conversation",
        preview: "Fixture conversation",
        status: "active",
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString(),
        dateLabel: "2026-05-10",
      });
    }
    if (path === "/api/assistant/sessions/ast_1" && method === "DELETE") {
      return json(route, { archived: true });
    }
    if (path === "/api/assistant/sessions/ast_1/messages" && method === "GET") {
      return json(route, {
        items: [
          {
            sequence: 1,
            role: "assistant",
            content: assistantMessagePosted ? "### 已收到\n- fixture response" : "### Ready",
            createdAt: new Date().toISOString(),
            rendering: "safe_markdown",
          },
        ],
        hasMoreBefore: false,
        nextBeforeSequence: null,
      });
    }
    if (path === "/api/assistant/sessions/ast_1/messages" && method === "POST") {
      assistantMessagePosted = true;
      return json(route, { accepted: true, sessionId: "ast_1" });
    }
    if (path === "/api/assistant/segment-boundary" && method === "POST") {
      return json(route, { segment_id: "seg_new", status: "pending" });
    }
    if (path.includes("/api/assistant/confirmations/")) {
      return json(route, { requestId: "req_1", decision: "approve", accepted: true });
    }

    if (path === "/api/teaching/readiness") {
      return json(route, {
        modes: [
          { mode: "browser", status: "ready", message: "可录制浏览器操作。", actions: [] },
          { mode: "extension", status: "ready", message: "可通过浏览器扩展触发录制。", actions: [] },
          { mode: "desktop", status: "ready", message: "可录制桌面操作。", actions: [] },
        ],
      });
    }
    if (path === "/api/teaching/runs") {
      return json(route, { workflowId: "rec_1", mode: "browser", stage: "selecting", summary: {} });
    }
    if (path.endsWith("/recording/start")) {
      return json(route, { workflowId: "rec_1", mode: "browser", stage: "recording", summary: {} });
    }
    if (path.endsWith("/recording/stop")) {
      return json(route, { workflowId: "rec_1", mode: "browser", stage: "intent_confirmation", summary: {} });
    }
    if (path.endsWith("/intent/confirm")) {
      return json(route, { workflowId: "rec_1", mode: "browser", stage: "learning", summary: {} });
    }
    if (path.endsWith("/intent/reply")) {
      return json(route, { workflowId: "rec_1", mode: "browser", stage: "intent_confirmation", summary: {} });
    }
    if (path.endsWith("/trial/start")) {
      return json(route, { workflowId: "rec_1", mode: "browser", stage: "trial_validation", summary: {} });
    }

    if (path === "/api/skills") {
      const category = url.searchParams.get("category");
      if (category === "published") {
        return json(route, {
          category,
          count: 2,
          items: [
            {
              toolId: "tool_a",
              name: "Published Skill",
              description: "Ready to reuse",
              status: "published",
              source: "teaching",
              trialSuccessCount: 3,
            },
            {
              toolId: "tool_b",
              name: "Second Skill",
              description: "Runs after first",
              status: "published",
              source: "teaching",
              trialSuccessCount: 3,
            },
          ],
        });
      }
      if (category === "failed") {
        return json(route, {
          category,
          count: 1,
          items: [
            {
              toolId: "tool_failed",
              name: "Failed Skill",
              description: "Retryable failure",
              status: "failed",
              source: "teaching",
              trialSuccessCount: 0,
              workflowId: "wf_failed",
              failureStage: "trial",
              errorSummary: "Timed out",
            },
          ],
        });
      }
      return json(route, {
        category: "pending",
        count: 1,
        items: [
          {
            toolId: "tool_pending",
            name: "Pending Skill",
            description: "Needs validation",
            status: "pending",
            source: "teaching",
            trialSuccessCount: 0,
          },
        ],
      });
    }
    if (path.includes("/api/skills/") || path.includes("/api/skills/failures/")) {
      return json(route, { accepted: true, workflowId: "wf_fixture" });
    }

    if (path === "/api/compositions" && method === "GET") {
      return json(route, { items: [] });
    }
    if (path === "/api/compositions" && method === "POST") {
      compositionCounter += 1;
      const body = request.postDataJSON() as Record<string, unknown>;
      return json(route, {
        compositionId: `comp_${compositionCounter}`,
        status: "draft",
        displayStatus: "draft",
        needsReview: false,
        ...body,
      });
    }
    if (path.includes("/api/compositions/") && path.endsWith("/trial")) {
      return json(route, { accepted: true, sessionId: "trial_1" });
    }
    if (path.includes("/api/compositions/") && path.endsWith("/publish")) {
      return json(route, {
        compositionId: path.split("/")[3],
        name: "Published Composition",
        description: "Published",
        mode: "ordered",
        status: "published",
        displayStatus: "published",
        needsReview: false,
        applicability: "When fixture applies",
        members: [{ toolId: "tool_a", selectedOrder: 1, executionOrder: 1 }],
      });
    }

    if (path === "/api/brain/zones") {
      return json(route, {
        zones: [
          { zone: "hot", label: "热区", entry_count: 1, fading_count: 0 },
          { zone: "persistent", label: "持久区", entry_count: 1, fading_count: 0 },
          { zone: "archive", label: "归档区", entry_count: 0, fading_count: 0 },
          { zone: "subconscious", label: "潜意识区", entry_count: 0, fading_count: 0 },
          { zone: "failure", label: "失败区", entry_count: 0, fading_count: 0 },
          { zone: "prediction", label: "猜测区", entry_count: 0, fading_count: 0 },
        ],
      });
    }
    if (path === "/api/brain/zones/hot/entries") {
      return json(route, {
        items: [
          {
            entry_id: "entry_hot_1",
            zone: "hot",
            entry_type: "insight",
            content: "用户偏好先给结论",
            status: "active",
            origin: "distillation",
            reason: "多次对话沉淀",
            scope: "沟通",
            loaded_count: 1,
            referenced_count: 1,
            superseded_by: null,
            verification_checkpoint: null,
            verification_status: null,
            verification_rationale: null,
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          },
        ],
        total: 1,
        limit: 50,
        offset: 0,
      });
    }
    if (path.startsWith("/api/brain/zones/") && path.endsWith("/entries")) {
      return json(route, { items: [], total: 0, limit: 50, offset: 0 });
    }
    if (path === "/api/brain/entries/entry_hot_1/evolution") {
      return json(route, {
        chain: [
          {
            entry_id: "entry_hot_1",
            zone: "hot",
            entry_type: "insight",
            content: "用户偏好先给结论",
            status: "active",
            origin: "distillation",
            reason: "多次对话沉淀",
            scope: "沟通",
            loaded_count: 1,
            referenced_count: 1,
            superseded_by: null,
            verification_checkpoint: null,
            verification_status: null,
            verification_rationale: null,
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          },
        ],
      });
    }
    if (path.startsWith("/api/brain/entries/")) {
      return json(route, { accepted: true });
    }
    if (path === "/api/brain/segments") {
      return json(route, {
        items: [{ segment_id: "seg_1", session_id: "ast_1", status: "failed", retry_count: 1, boundary_reason: "idle" }],
        total: 1,
      });
    }
    if (path.startsWith("/api/brain/segments/") && path.endsWith("/retry")) {
      return json(route, { segment_id: path.split("/")[4], status: "pending" });
    }
    if (path === "/api/brain/skill-pool") {
      return json(route, { skills: [{ tool_id: "tool_a", name: "Published Skill", description: "Ready to reuse" }] });
    }
    if (path.startsWith("/api/brain/skill-pool/")) {
      return json(route, { accepted: true });
    }
    if (path === "/api/brain/specialists") {
      if (method === "POST") {
        const body = request.postDataJSON() as Record<string, unknown>;
        return json(route, {
          specialist_id: "spec_new",
          origin: "user_management_ui",
          reason: "通过管理界面创建",
          current_version: 1,
          is_active: true,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
          ...body,
        });
      }
      return json(route, {
        items: [
          {
            specialist_id: "spec_1",
            name: "报表专员",
            description: "处理周期报表",
            role_definition: "你负责处理报表。",
            tool_whitelist: ["tool_a"],
            origin: "auto_recruitment",
            reason: "检测到持续报表委托",
            current_version: 1,
            is_active: true,
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          },
        ],
        total: 1,
        limit: 50,
        offset: 0,
      });
    }
    if (path === "/api/brain/specialists/spec_1/versions") {
      return json(route, { items: [{ version_id: "v1", specialist_id: "spec_1", version: 1, name: "报表专员", change_reason: "初始创建" }] });
    }
    if (path.startsWith("/api/brain/specialists/")) {
      return json(route, { accepted: true });
    }

    if (path === "/api/settings/schema") {
      return json(route, {
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
            actions: [{ key: "test_ai_connection", label: "测试 AI 连接", section: "ai", valueKind: "action", status: "available" }],
          },
          {
            id: "about",
            label: "关于",
            items: [],
            actions: [{ key: "check_updates", label: "检查更新", section: "about", valueKind: "action", status: "available" }],
          },
        ],
      });
    }
    if (path === "/api/settings/values" && method === "PATCH") {
      const body = request.postDataJSON() as { values?: Record<string, string> };
      settingsModel = body.values?.["ai.model"] ?? settingsModel;
      return json(route, settingsValues(settingsModel, secretPresent));
    }
    if (path === "/api/settings/values" || path === "/api/settings") {
      return json(route, settingsValues(settingsModel, secretPresent));
    }
    if (path === "/api/settings/secrets/ai.api_key" && method === "POST") {
      secretPresent = true;
      return json(route, { secretKey: "ai.api_key", present: true, masked: "••••••••" });
    }
    if (path === "/api/settings/secrets/ai.api_key" && method === "DELETE") {
      secretPresent = false;
      return json(route, { secretKey: "ai.api_key", present: false, masked: "" });
    }
    if (path === "/api/settings/actions/check_updates") {
      return json(route, { actionName: "check_updates", status: "unavailable", message: "当前构建未配置更新通道。", details: {} });
    }
    if (path.startsWith("/api/settings/actions/")) {
      return json(route, { actionName: path.split("/").pop(), status: "completed", message: "已完成。", details: {} });
    }

    return json(route, {});
  });

  return { requests };
}

function settingsValues(model: string, secretPresent: boolean) {
  return {
    values: { "ai.model": model, "ai.timeout": 120 },
    secrets: { "ai.api_key": { present: secretPresent, masked: secretPresent ? "••••••••" : "" } },
    status: { "ai.api_key": secretPresent ? "available" : "missing_secret" },
  };
}
