/**
 * ⑦ UserTaskCard 组件测试
 *
 * 验证：
 * - 折叠态显示标题
 * - 有推得动的暂停时显示「继续」按钮
 * - 撞缺陷时显示「需处理」标签 + 说明
 * - 等用户回答时不显示「继续」按钮
 * - 点继续后显示回报（动了/没动/原因）
 */

import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

import type { UserTaskContinueResponse } from "../../src/api/userTasks";
import UserTaskCard from "../../src/screens/assistant/UserTaskCard";
import { useAssistantTaskStore } from "../../src/state/assistantTaskStore";

function mockFetch(responseMap: Record<string, (url: string, init?: RequestInit) => unknown>) {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    for (const [pattern, handler] of Object.entries(responseMap)) {
      if (url.includes(pattern)) {
        const body = handler(url, init);
        return {
          ok: true,
          status: 200,
          json: async () => body,
          text: async () => JSON.stringify(body),
        };
      }
    }
    return {
      ok: true,
      status: 200,
      json: async () => ({ tasks: [], distribution: {} }),
      text: async () => "{}",
    };
  });
}

function jsonResponse(data: unknown) {
  return {
    ok: true,
    status: 200,
    json: async () => data,
    text: async () => JSON.stringify(data),
  };
}

describe("UserTaskCard", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ distribution: {} })));
  });

  it("shows the task title in collapsed state", async () => {
    render(
      <UserTaskCard sessionId="s1" taskId="utsk_1" title="季度报告" onOpenFullGraph={() => {}} onOpenExecutor={() => {}} />,
    );
    await waitFor(() => {
      expect(screen.getAllByText("季度报告")[0]).toBeInTheDocument();
    });
    // 标题同时出现在折叠 summary 和展开 body 的 me-task-title 里
    expect(screen.getAllByText("季度报告").length).toBeGreaterThanOrEqual(1);
  });

  it("shows continue button when user_stop maps to suspended:user", async () => {
    // user_stop（用户手动停）和 interrupted（崩溃重启）都映射到 waiting_on=user，
    // 分布 key 是 suspended:user。设计 294 行：waiting_on==user → 自动展开 + 继续。
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse({
          distribution: { running: 2, "suspended:user_stop": 1, done: 3 },
        }),
      ),
    );
    render(
      <UserTaskCard sessionId="s1" taskId="utsk_1" title="季度报告" onOpenFullGraph={() => {}} onOpenExecutor={() => {}} />,
    );
    await waitFor(() => {
      expect(screen.getByTitle("继续这件事")).toBeInTheDocument();
    });
  });

  it("hides continue button when only blocked_by_defect", async () => {
    // suspended:assistant = 撞上程序缺陷，重试必是同样的结果，不给继续按钮。
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse({
          distribution: { "suspended:blocked_by_defect": 2, done: 1 },
        }),
      ),
    );
    render(
      <UserTaskCard sessionId="s1" taskId="utsk_1" title="季度报告" onOpenFullGraph={() => {}} onOpenExecutor={() => {}} />,
    );
    await waitFor(() => {
      expect(screen.getAllByText("季度报告")[0]).toBeInTheDocument();
    });
    expect(screen.queryByTitle("继续这件事")).not.toBeInTheDocument();
  });

  it("shows defect tag and notice when suspended:assistant > 0", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse({
          distribution: { "suspended:blocked_by_defect": 1, done: 2 },
        }),
      ),
    );
    render(
      <UserTaskCard sessionId="s1" taskId="utsk_1" title="季度报告" onOpenFullGraph={() => {}} onOpenExecutor={() => {}} />,
    );
    await waitFor(() => {
      expect(screen.getByText("需处理")).toBeInTheDocument();
    });
    // 展开后应有缺陷说明
    const summary = screen.getAllByText("季度报告")[0].closest("summary");
    if (summary) fireEvent.click(summary);
    await waitFor(() => {
      expect(screen.getByText(/遇到程序问题/)).toBeInTheDocument();
    });
  });

  it("displays continue report after clicking continue", async () => {
    const continueResponse: UserTaskContinueResponse = {
      pushed: [{ title: "整理区域明细" }],
      notPushed: [{ title: "华东区口径", reason: "在等你回答" }],
      stillFinishing: [],
      total: 2,
      success: true,
    };
    let callCount = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/continue")) {
          callCount++;
          return jsonResponse(continueResponse);
        }
        return jsonResponse({
          distribution: { "suspended:user_stop": 1, done: 1 },
        });
      }),
    );
    render(
      <UserTaskCard sessionId="s1" taskId="utsk_1" title="季度报告" onOpenFullGraph={() => {}} onOpenExecutor={() => {}} />,
    );
    await waitFor(() => {
      expect(screen.getByTitle("继续这件事")).toBeInTheDocument();
    });
    fireEvent.click(screen.getByTitle("继续这件事"));
    await waitFor(() => {
      expect(screen.getByText(/摊里动了/)).toBeInTheDocument();
    });
    expect(screen.getByText(/整理区域明细/)).toBeInTheDocument();
    expect(screen.getByText(/华东区口径/)).toBeInTheDocument();
  });

  it("shows failure message when nothing was pushed", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/continue")) {
          return jsonResponse({
            pushed: [],
            notPushed: [],
            stillFinishing: [],
            total: 0,
            success: false,
          });
        }
        return jsonResponse({
          distribution: { "suspended:budget_exhausted": 1 },
        });
      }),
    );
    render(
      <UserTaskCard sessionId="s1" taskId="utsk_1" title="季度报告" onOpenFullGraph={() => {}} onOpenExecutor={() => {}} />,
    );
    await waitFor(() => {
      expect(screen.getByTitle("继续这件事")).toBeInTheDocument();
    });
    fireEvent.click(screen.getByTitle("继续这件事"));
    await waitFor(() => {
      expect(screen.getByText("没有推动任何任务")).toBeInTheDocument();
    });
  });

  it("后端进度事件到达时重新拉取，而不是停在挂载那一刻的快照", async () => {
    // 卡片展示的是"底下卡在谁手上"，随执行节点变化。后端节点状态变化会发
    // user_task.changed(progress_changed)，store 递增 userTaskVersion；
    // 卡片必须跟着重拉，否则子代理跑完、todo 打勾都看不到。
    let distribution: Record<string, number> = { running: 1 };
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        if (String(input).includes("/distribution")) {
          return jsonResponse({ distribution });
        }
        return jsonResponse({ graphs: [] });
      }),
    );
    render(
      <UserTaskCard sessionId="s1" taskId="utsk_1" title="季度报告" onOpenFullGraph={() => {}} onOpenExecutor={() => {}} />,
    );
    await waitFor(() => {
      expect(screen.getByText(/进行中 1/)).toBeInTheDocument();
    });

    // 执行节点跑完 → 后端发 progress_changed → store 递增版本号
    distribution = { done: 1 };
    act(() => {
      useAssistantTaskStore.getState().applyEvent({
        type: "user_task.changed",
        payload: { userTaskId: "utsk_1", changeType: "progress_changed", sessionId: "s1" },
      } as never);
    });

    await waitFor(() => {
      expect(screen.getByText(/已完成 1/)).toBeInTheDocument();
    });
  });

  it("派出子代理后出现子代理卡片，它的 msg 不外泄到第一层", async () => {
    // 之前的 bug：卡片里没出现子代理卡片，反而直接铺出了子代理的 msg。
    // 第一层只放主助理自己的动作；子代理是一张卡片，msg 收在卡片后面。
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ distribution: { running: 1 } })));
    render(
      <UserTaskCard
        sessionId="s1"
        taskId="utsk_1"
        title="季度报告"
        steps={[{ seq: 1, kind: "reasoning", text: "主助理：先拆解一下" }]}
        subagents={[
          { subagentId: "sub_1", label: "通用子代理", task: "抓取榜单", status: "running", anchorSeq: 2 },
        ]}
        onOpenFullGraph={() => {}}
        onOpenExecutor={() => {}}
      />,
    );
    const summary = (await screen.findAllByText("季度报告"))[0].closest("summary");
    fireEvent.click(summary!);
    await waitFor(() => {
      expect(screen.getByText("通用子代理")).toBeInTheDocument();
    });
    expect(screen.getByText(/主助理：先拆解一下/)).toBeInTheDocument();
  });

  it("子代理跑起来后创建/更新 todolist，卡片正面跟着变", async () => {
    // 刚派出时没有 todo，卡片只有标题行；子代理跑到一半建了清单、勾掉一条，
    // 卡片正面要实时跟上——todo 走 store 的 todosByTaskId，由事件驱动更新。
    useAssistantTaskStore.setState({ todosByTaskId: {} });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/distribution")) return jsonResponse({ distribution: { running: 1 } });
        if (url.includes("/todos")) return jsonResponse({ items: [] });
        return jsonResponse({ graphs: [] });
      }),
    );
    render(
      <UserTaskCard
        sessionId="s1"
        taskId="utsk_1"
        title="季度报告"
        subagents={[
          { subagentId: "sub_1", label: "通用子代理", task: "查榜单", status: "running", taskId: "tsk_1", anchorSeq: 1 },
        ]}
        onOpenFullGraph={() => {}}
        onOpenExecutor={() => {}}
      />,
    );
    const summary = (await screen.findAllByText("季度报告"))[0].closest("summary");
    fireEvent.click(summary!);
    // 刚派出：卡片在，但没有 todo
    await waitFor(() => {
      expect(screen.getByText("通用子代理")).toBeInTheDocument();
    });
    expect(screen.queryByText("抓取日榜")).not.toBeInTheDocument();

    // 子代理建了清单
    act(() => {
      useAssistantTaskStore.setState({
        todosByTaskId: {
          tsk_1: [
            { todoId: "t1", text: "抓取日榜", status: "doing", sortOrder: 1 },
          ],
        },
      });
    });
    await waitFor(() => {
      expect(screen.getByText("抓取日榜")).toBeInTheDocument();
    });
    expect(screen.getByText("进行")).toBeInTheDocument();

    // 勾掉之后状态跟着变
    act(() => {
      useAssistantTaskStore.setState({
        todosByTaskId: {
          tsk_1: [
            { todoId: "t1", text: "抓取日榜", status: "done", sortOrder: 1 },
          ],
        },
      });
    });
    await waitFor(() => {
      expect(screen.getByText("完成")).toBeInTheDocument();
    });
  });

  it("实时 subagent 没有 taskId 时，用上层映射拿到它的 todolist", async () => {
    // 打包版实测断在这：subagent 来自实时事件（无 taskId），而卡片自己那条
    // 「拉图列表→拉快照→反查」的慢链没数据，于是取不到 todo 的 key。
    // 上层用 currentTaskGraph 建映射传下来，与 store 里的 todo 同源。
    // store 里已有这个 task 的 todo（AssistantScreen 拉的）
    useAssistantTaskStore.setState({
      todosByTaskId: {
        tsk_7c5b: [
          { todoId: "1", text: "抓取 Daily 页面", status: "done", sortOrder: 1 },
          { todoId: "2", text: "抓取 Weekly 页面", status: "done", sortOrder: 2 },
        ],
      },
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/distribution")) return jsonResponse({ distribution: { done: 1 } });
        // graphs 返回空 —— 复现慢链没数据的情形
        return jsonResponse({ graphs: [] });
      }),
    );
    render(
      <UserTaskCard
        sessionId="s1"
        taskId="utsk_1"
        title="查询 GitHub"
        subagents={[
          { subagentId: "010bf4dd", label: "通用子代理", task: "查榜单", status: "done", anchorSeq: 1 },
        ]}
        taskIdByExecutorSession={{ "010bf4dd": "tsk_7c5b" }}
        onOpenFullGraph={() => {}}
        onOpenExecutor={() => {}}
      />,
    );
    const summary = (await screen.findAllByText("查询 GitHub"))[0].closest("summary");
    fireEvent.click(summary!);
    await waitFor(() => {
      expect(screen.getByText("通用子代理")).toBeInTheDocument();
    });
    expect(screen.getByText("抓取 Daily 页面")).toBeInTheDocument();
    expect(screen.getByText("抓取 Weekly 页面")).toBeInTheDocument();
  });

  it("工具的参数/结果默认折叠，点开才展示内容", async () => {
    // 一次委派的 JSON 摊开有几十行，会把周围的步骤全挤走。
    const bigJson = JSON.stringify({ task: "查榜单", context: "x".repeat(200) }, null, 2);
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ distribution: { running: 1 } })));
    render(
      <UserTaskCard
        sessionId="s1"
        taskId="utsk_1"
        title="季度报告"
        steps={[{ seq: 1, kind: "tool_call", toolName: "delegate_to_subagent", text: bigJson }]}
        onOpenFullGraph={() => {}}
        onOpenExecutor={() => {}}
      />,
    );
    const summary = (await screen.findAllByText("季度报告"))[0].closest("summary");
    fireEvent.click(summary!);
    // 折叠态：只有摘要，内容不可见
    await waitFor(() => {
      expect(screen.getByText(/参数 · \d+ 行/)).toBeInTheDocument();
    });
    const fold = screen.getByText(/参数 · \d+ 行/).closest("details");
    expect(fold).not.toHaveAttribute("open");
    // 点开后内容出现
    fireEvent.click(screen.getByText(/参数 · \d+ 行/));
    await waitFor(() => {
      expect(fold).toHaveAttribute("open");
    });
  });

  it("没建任务的轮次：同一张卡片、默认标题，照样能看过程和子代理", async () => {
    // 不是每轮都建任务。没建的那轮要看的就是主助理自己的 msg 和它派出去的人，
    // 用户视角只有一种卡片，不该因为"这轮有没有建任务"而换形态。
    const fetchMock = vi.fn(async (_input: RequestInfo | URL) =>
      jsonResponse({ distribution: {} }),
    );
    vi.stubGlobal("fetch", fetchMock);
    render(
      <UserTaskCard
        sessionId="s1"
        title="这一轮做了什么"
        steps={[{ seq: 1, kind: "reasoning", text: "查一下昨天的结论" }]}
        subagents={[
          { subagentId: "sub_x", label: "通用子代理", task: "翻记录", status: "running", anchorSeq: 2 },
        ]}
        onOpenFullGraph={() => {}}
        onOpenExecutor={() => {}}
      />,
    );
    const summary = (await screen.findAllByText("这一轮做了什么"))[0].closest("summary");
    fireEvent.click(summary!);
    await waitFor(() => {
      expect(screen.getByText(/查一下昨天的结论/)).toBeInTheDocument();
    });
    // 子代理照样在，可点开下钻
    expect(screen.getByText("通用子代理")).toBeInTheDocument();
    // 没有任务身份：不发任务相关请求、不出现继续按钮和状态标签
    expect(
      fetchMock.mock.calls.some((c) => String(c[0] ?? "").includes("/distribution")),
    ).toBe(false);
    expect(screen.queryByTitle("继续这件事")).not.toBeInTheDocument();
    expect(screen.queryByText("在办")).not.toBeInTheDocument();
  });

  it("主助理的 msg、执行体卡片、任务图按发生顺序排成一个流", async () => {
    // 设计 [87]：「里边可以看完成任务的具体的操作，比如调用了什么工具」。
    // 原本对话流里有个独立的「正在处理 N 项」框，与卡片并排讲同一件事。
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ distribution: { running: 1 } })));
    render(
      <UserTaskCard
        sessionId="s1"
        taskId="utsk_1"
        title="季度报告"
        steps={[
          { seq: 1, kind: "reasoning", text: "先看看要查哪几个维度" },
          { seq: 2, kind: "tool_call", toolName: "delegate_to_subagent", text: "{}" },
        ]}
        onOpenFullGraph={() => {}}
        onOpenExecutor={() => {}}
      />,
    );
    const summary = (await screen.findAllByText("季度报告"))[0].closest("summary");
    fireEvent.click(summary!);
    // 主助理的动作直接出现在流里，不再折叠进「做了什么」
    await waitFor(() => {
      expect(screen.getByText(/先看看要查哪几个维度/)).toBeInTheDocument();
    });
  });

  it("已办完的执行体仍然列出来（历史任务要能回看子代理做了什么）", async () => {
    // 重开历史会话时 refreshSubagents 会从后端拉权威列表恢复，所以办完的
    // 执行体照样有卡片；任务办完卡片就空掉等于把过程记录藏了。
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/distribution")) return jsonResponse({ distribution: { done: 1 } });
        return jsonResponse({ graphs: [] });
      }),
    );
    render(
      <UserTaskCard
        sessionId="s1"
        taskId="utsk_1"
        title="季度报告"
        subagents={[
          { subagentId: "sub_done", label: "通用助手", task: "查 GitHub", status: "done", anchorSeq: 1 },
        ]}
        onOpenFullGraph={() => {}}
        onOpenExecutor={() => {}}
      />,
    );
    const summary = (await screen.findAllByText("季度报告"))[0].closest("summary");
    fireEvent.click(summary!);
    await waitFor(() => {
      expect(screen.getByText("通用助手")).toBeInTheDocument();
    });
    // 已办完要显示"完成"，不能显示成"正在干"
    expect(screen.getByText("完成")).toBeInTheDocument();
  });
});
