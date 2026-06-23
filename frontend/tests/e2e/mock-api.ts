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
  let braveSecretPresent = false;
  let settingsModel = "claude-sonnet-4-20250514";
  let searchBackend = "auto";
  let summarySecretPresent = false;
  let summaryModel = "";
  let compositionCounter = 0;
  let debugTraceEnabled = false;
  let methodologyCreated = false;
  let methodologyEdited = false;
  let createdMethodologyName = "E2E 新建方法论";
  let createdMethodologyDescription = "把刚才的邮件处理流程沉淀成方法论";
  let createdMethodologyTrigger = "用户要求处理周期邮件";
  const equipmentByEntity: Record<string, string[]> = {
    _assistant: ["sk_bootstrap"],
    spec_1: [],
  };

  const bootstrapMethodology = {
    skill_id: "sk_bootstrap",
    name: "如何创建方法论",
    description: "系统内置方法论创建指引",
    trigger_conditions: ["用户要求把流程沉淀为方法论"],
    required_tools: [],
    version: 1,
    chain_root_id: "sk_bootstrap",
    origin: "system_bootstrap",
    is_protected: true,
    loaded_count: 0,
    referenced_count: 0,
    equipped_count: 1,
    last_referenced_at: null,
    created_at: "2026-05-20T00:00:00Z",
  };

  function createdMethodology() {
    return {
      skill_id: "sk_created",
      name: createdMethodologyName,
      description: createdMethodologyDescription,
      trigger_conditions: [createdMethodologyTrigger],
      required_tools: ["tool_a"],
      version: methodologyEdited ? 2 : 1,
      chain_root_id: "sk_created",
      origin: methodologyEdited ? "user_edit" : "assistant_tool_call",
      is_protected: false,
      loaded_count: 2,
      referenced_count: 1,
      equipped_count: [equipmentByEntity._assistant, equipmentByEntity.spec_1].filter((list) => list.includes("sk_created")).length,
      last_referenced_at: "2026-05-27T00:00:00Z",
      created_at: methodologyEdited ? "2026-05-28T00:00:00Z" : "2026-05-27T00:00:00Z",
    };
  }

  function activeMethodologies() {
    return methodologyCreated ? [createdMethodology(), bootstrapMethodology] : [bootstrapMethodology];
  }

  function methodologyDetail(skillId: string) {
    const summary = skillId === "sk_bootstrap" ? bootstrapMethodology : createdMethodology();
    return {
      ...summary,
      status: "active",
      parent_skill_id: methodologyEdited && skillId === "sk_created" ? "sk_created_v1" : null,
      body_markdown:
        skillId === "sk_bootstrap"
          ? "# 如何创建方法论\n\n按 trigger_conditions 选择性 load，不应单轮无差别 load 全清单。"
          : "# E2E 新建方法论\n\n1. 收集输入。\n2. 调用可用工具。\n3. 汇总结果。",
      source_segments: [{ segment_id: "seg_1", source_zone: "archive", segment_summary: "邮件处理复盘", segment_status: "active" }],
    };
  }

  function equipmentResponse(entityId: string) {
    const activeIds = equipmentByEntity[entityId] ?? [];
    return {
      entity_type: entityId === "_assistant" ? "assistant" : "specialist",
      entity_id: entityId,
      entity_name: entityId === "_assistant" ? "Assistant 本体" : "报表专员",
      tool_whitelist: ["tool_a"],
      active_equipment: activeIds
        .map((skillId, equipped_order) => {
          const summary = methodologyDetail(skillId);
          return {
            skill_id: summary.skill_id,
            chain_root_id: summary.chain_root_id,
            name: summary.name,
            description: summary.description,
            trigger_conditions: summary.trigger_conditions,
            required_tools: summary.required_tools,
            missing_required_tools: [],
            equipped_order,
            equipped_at: "2026-05-28T00:00:00Z",
          };
        }),
      token_budget_estimate: 256,
      token_budget_thresholds: { warn_threshold: 4096, danger_threshold: 8192 },
    };
  }

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
      methodologyCreated = true;
      if (!equipmentByEntity._assistant.includes("sk_created")) equipmentByEntity._assistant.push("sk_created");
      if (!equipmentByEntity.spec_1.includes("sk_created")) equipmentByEntity.spec_1.push("sk_created");
      return json(route, { accepted: true, sessionId: "ast_1" });
    }
    if (path === "/api/assistant/sessions/ast_1/task-graphs/current" && method === "GET") {
      return json(route, {
        graph: {
          graphId: "tg_fixture",
          sessionId: "ast_1",
          userMessageSequence: 1,
          version: 1,
          tasks: [
            {
              taskId: "tsk_fixture_root",
              graphId: "tg_fixture",
              parentTaskId: null,
              title: "整理报销",
              descriptionPreview: "整理本月报销并生成摘要",
              status: "running",
              displayPhase: "running",
              requiresReview: false,
              safeExplanation: "",
              suspendReason: null,
              assignee: null,
              adjudicationId: null,
              updatedAt: new Date().toISOString(),
            },
            {
              taskId: "tsk_fixture_child",
              graphId: "tg_fixture",
              parentTaskId: "tsk_fixture_root",
              title: "核对发票",
              descriptionPreview: "检查发票日期和金额",
              status: "suspended",
              displayPhase: "paused",
              requiresReview: false,
              safeExplanation: "等待继续",
              suspendReason: "user_stop",
              assignee: { type: "specialist", id: "spec_1", label: "财务专员" },
              adjudicationId: null,
              updatedAt: new Date().toISOString(),
            },
          ],
          edges: [
            { sourceTaskId: "tsk_fixture_root", targetTaskId: "tsk_fixture_child", type: "delegation" },
          ],
          adjudications: [],
        },
      });
    }
    if (path === "/api/assistant/sessions/ast_1/task-graphs/tg_fixture" && method === "GET") {
      return json(route, {
        graphId: "tg_fixture",
        sessionId: "ast_1",
        userMessageSequence: 1,
        version: 1,
        tasks: [],
        edges: [],
        adjudications: [],
      });
    }
    if (path === "/api/assistant/sessions/ast_1/task-board" && method === "GET") {
      return json(route, {
        items: [
          {
            taskId: "tsk_fixture_board",
            graphId: "tg_fixture",
            title: "补充票据截图",
            status: "pending_dispatch",
            claimStatus: "open",
            claimId: null,
            assignee: null,
            updatedAt: new Date().toISOString(),
          },
        ],
      });
    }
    if (path === "/api/assistant/sessions/ast_1/task-board/tsk_fixture_board/claim" && method === "POST") {
      return json(route, {
        accepted: true,
        claimId: "clm_fixture",
        taskId: "tsk_fixture_board",
        status: "claimed",
      });
    }
    if (path === "/api/assistant/sessions/ast_1/task-board/claims/clm_fixture/release" && method === "POST") {
      return json(route, {
        accepted: true,
        claimId: "clm_fixture",
        taskId: "tsk_fixture_board",
        status: "released",
      });
    }
    if (path === "/api/assistant/sessions/ast_1/meetings/mtg_fixture" && method === "GET") {
      return json(route, {
        channelId: "mtg_fixture",
        status: "open",
        participants: [
          { type: "specialist", id: "spec_1", label: "财务专员" },
          { type: "specialist", id: "spec_2", label: "邮件专员" },
        ],
        turnsUsed: 2,
        turnBudget: 12,
        messages: [
          {
            sequence: 1,
            senderId: "spec_1",
            content: "按日期核对票据。",
            createdAt: new Date().toISOString(),
          },
        ],
        nextAfterSequence: null,
        conclusion: null,
      });
    }
    if (path === "/api/assistant/sessions/ast_1/tasks/tsk_fixture_root/todos" && method === "GET") {
      return json(route, { taskId: "tsk_fixture_root", items: [] });
    }
    if (path === "/api/assistant/sessions/ast_1/tasks/tsk_fixture_child/todos" && method === "GET") {
      return json(route, {
        taskId: "tsk_fixture_child",
        items: [
          {
            todoId: "todo_fixture_1",
            text: "核对票据日期",
            status: "doing",
            sortOrder: 1,
          },
          {
            todoId: "todo_fixture_2",
            text: "标记缺失附件",
            status: "todo",
            sortOrder: 2,
          },
        ],
      });
    }
    if (path.endsWith("/todos") && path.startsWith("/api/assistant/sessions/ast_1/tasks/") && method === "PUT") {
      const body = request.postDataJSON() as { items?: unknown[] };
      return json(route, {
        taskId: path.split("/")[6],
        items: body.items ?? [],
      });
    }
    if (path === "/api/assistant/sessions/ast_1/stop" && method === "POST") {
      return json(route, { accepted: true });
    }
    if (path === "/api/assistant/sessions/ast_1/subagents" && method === "GET") {
      return json(route, {
        items: [
          {
            subagentId: "sub_1",
            label: "子助手",
            task: "检索季度报表",
            status: "suspended",
            lastOutput: "已检索到部分数据",
          },
        ],
      });
    }
    if (path === "/api/assistant/sessions/ast_1/transcript" && method === "GET") {
      return json(route, {
        steps: [
          { kind: "tool_call", toolName: "search", text: "查询报表", seq: 1 },
          { kind: "tool_result", toolName: "search", text: "命中 3 条", seq: 2 },
        ],
        compressed: false,
      });
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

    if (path === "/api/skills/methodology" && method === "GET") {
      return json(route, { items: activeMethodologies() });
    }
    if (path === "/api/skills/methodology/bootstrap-status" && method === "GET") {
      return json(route, {
        bootstrap_active_skill_id: "sk_bootstrap",
        fallback_used: false,
        seed_file_path: "src/business/brain/seed/how_to_create_skill_methodology.md",
        last_seed_check_at: "2026-05-28T00:00:00Z",
      });
    }
    if (path === "/api/skills/methodology/sk_created" && method === "PUT") {
      const body = request.postDataJSON() as {
        name?: string;
        description?: string;
        trigger_conditions?: string[];
      };
      methodologyEdited = true;
      createdMethodologyName = body.name ?? createdMethodologyName;
      createdMethodologyDescription = body.description ?? createdMethodologyDescription;
      createdMethodologyTrigger = body.trigger_conditions?.[0] ?? createdMethodologyTrigger;
      return json(route, methodologyDetail("sk_created"));
    }
    if (path === "/api/skills/methodology/sk_created/soft-delete" && method === "POST") {
      methodologyCreated = false;
      equipmentByEntity._assistant = equipmentByEntity._assistant.filter((skillId) => skillId !== "sk_created");
      equipmentByEntity.spec_1 = equipmentByEntity.spec_1.filter((skillId) => skillId !== "sk_created");
      return json(route, { deleted_skill_id: "sk_created", pruned_equipment_count: 2, affected_specialist_ids: ["spec_1"] });
    }
    if (path === "/api/skills/methodology/sk_created/history" && method === "GET") {
      return json(route, {
        chain_root_id: "sk_created",
        nodes: [
          {
            ...methodologyDetail("sk_created"),
            skill_id: "sk_created_v1",
            version: 1,
            origin: "assistant_tool_call",
            changed_by: "assistant",
            change_reason: "Assistant 从对话中创建",
            diff_from_previous: null,
            created_at: "2026-05-27T00:00:00Z",
          },
          {
            ...methodologyDetail("sk_created"),
            version: 2,
            origin: "user_edit",
            changed_by: "user",
            change_reason: "E2E edit reason",
            diff_from_previous: "+ updated",
            created_at: "2026-05-28T00:00:00Z",
          },
        ],
      });
    }
    if (path === "/api/skills/methodology/sk_bootstrap/history" && method === "GET") {
      return json(route, {
        chain_root_id: "sk_bootstrap",
        nodes: [
          {
            ...methodologyDetail("sk_bootstrap"),
            version: 1,
            changed_by: "system",
            change_reason: "系统内置",
            diff_from_previous: null,
          },
        ],
      });
    }
    if (path.endsWith("/audit-equipment") && path.startsWith("/api/skills/methodology/") && method === "GET") {
      const skillId = path.split("/")[4];
      return json(route, {
        skill_id: skillId,
        rows: [
          {
            equipped_entity_type: "assistant",
            equipped_entity_id: "_assistant",
            equipped_entity_name: "Assistant 本体",
            status: "active",
            equipped_at: "2026-05-28T00:00:00Z",
            unequipped_at: null,
            unequipped_reason: null,
          },
          ...(skillId === "sk_created"
            ? [
                {
                  equipped_entity_type: "specialist",
                  equipped_entity_id: "spec_1",
                  equipped_entity_name: "报表专员",
                  status: "active",
                  equipped_at: "2026-05-28T00:00:00Z",
                  unequipped_at: null,
                  unequipped_reason: null,
                },
              ]
            : []),
        ],
      });
    }
    if (path === "/api/skills/methodology/sk_created" && method === "GET") {
      return json(route, methodologyDetail("sk_created"));
    }
    if (path === "/api/skills/methodology/sk_bootstrap" && method === "GET") {
      return json(route, methodologyDetail("sk_bootstrap"));
    }
    if (path.startsWith("/api/specialists/") && path.endsWith("/equipment") && method === "GET") {
      const entityId = decodeURIComponent(path.split("/")[3]);
      return json(route, equipmentResponse(entityId));
    }
    if (path.startsWith("/api/specialists/") && path.endsWith("/equipment") && method === "PUT") {
      const entityId = decodeURIComponent(path.split("/")[3]);
      const body = request.postDataJSON() as { skills?: Array<{ skill_id: string }> };
      equipmentByEntity[entityId] = body.skills?.map((item) => item.skill_id) ?? [];
      return json(route, {
        active_equipment_count: equipmentByEntity[entityId].length,
        newly_equipped: equipmentByEntity[entityId],
        newly_unequipped: [],
      });
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
                status: "available",
                advanced: false,
              },
            ],
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
      searchBackend = body.values?.["web.search_backend"] ?? searchBackend;
      summaryModel = body.values?.["agent_tools.output.semantic_summary.model"] ?? summaryModel;
      return json(
        route,
        settingsValues(
          settingsModel,
          secretPresent,
          searchBackend,
          braveSecretPresent,
          summaryModel,
          summarySecretPresent,
        ),
      );
    }
    if (path === "/api/settings/values" || path === "/api/settings") {
      return json(
        route,
        settingsValues(
          settingsModel,
          secretPresent,
          searchBackend,
          braveSecretPresent,
          summaryModel,
          summarySecretPresent,
        ),
      );
    }
    if (path === "/api/settings/secrets/ai.api_key" && method === "POST") {
      secretPresent = true;
      return json(route, { secretKey: "ai.api_key", present: true, masked: "••••••••" });
    }
    if (path === "/api/settings/secrets/ai.api_key" && method === "DELETE") {
      secretPresent = false;
      return json(route, { secretKey: "ai.api_key", present: false, masked: "" });
    }
    if (path === "/api/settings/secrets/web.brave_api_key" && method === "POST") {
      braveSecretPresent = true;
      return json(route, { secretKey: "web.brave_api_key", present: true, masked: "••••••••" });
    }
    if (path === "/api/settings/secrets/web.brave_api_key" && method === "DELETE") {
      braveSecretPresent = false;
      return json(route, { secretKey: "web.brave_api_key", present: false, masked: "" });
    }
    if (path === "/api/settings/secrets/agent_tools.output.semantic_summary.api_key" && method === "POST") {
      summarySecretPresent = true;
      return json(route, {
        secretKey: "agent_tools.output.semantic_summary.api_key",
        present: true,
        masked: "••••••••",
      });
    }
    if (path === "/api/settings/secrets/agent_tools.output.semantic_summary.api_key" && method === "DELETE") {
      summarySecretPresent = false;
      return json(route, {
        secretKey: "agent_tools.output.semantic_summary.api_key",
        present: false,
        masked: "",
      });
    }
    if (path === "/api/settings/actions/test_tool_output_summary_connection") {
      if (!summarySecretPresent) {
        return json(route, {
          actionName: "test_tool_output_summary_connection",
          status: "failed",
          message: "缺少摘要 API Key。",
          details: { provider: "openai", model: summaryModel, code: "missing_secret" },
        });
      }
      return json(route, {
        actionName: "test_tool_output_summary_connection",
        status: "completed",
        message: "摘要模型连接成功。",
        details: { provider: "openai", model: summaryModel },
      });
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

function settingsValues(
  model: string,
  secretPresent: boolean,
  searchBackend: string,
  braveSecretPresent: boolean,
  summaryModel: string,
  summarySecretPresent: boolean,
) {
  return {
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
  };
}
