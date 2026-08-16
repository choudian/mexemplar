import { Loader2, Play, ChevronRight } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  continueUserTask,
  getUserTaskDistribution,
  getUserTaskGraphs,
  type TaskDistribution,
  type UserTaskContinueResponse,
  type UserTaskGraphSummary,
} from "../../api/userTasks";
import { getAssistantTaskGraph, getAssistantTaskTodos } from "../../api/assistantTasks";
import type { AssistantTaskSnapshot, AssistantTodoItem } from "../../api/assistantTasks";
import TaskGraphPeek from "./TaskGraphPeek";
import ExecutorCard from "./ExecutorCard";
import { ActivityStepRow } from "./ActivityStepRow";
import { executorAnchorSeq, graphAnchorSeq } from "./timelineOrder";
import type { ActivityStep, Subagent } from "../../state/assistantTypes";
import { useAssistantTaskStore } from "../../state/assistantTaskStore";

/** 执行节点状态 → 执行体卡片状态。done/skipped 是已办完，不能显示成"正在干"。 */
function executorStatusOf(
  taskStatus: string,
): "running" | "done" | "suspended" | "failed" {
  if (taskStatus === "suspended") return "suspended";
  if (taskStatus === "done" || taskStatus === "skipped" || taskStatus === "delivered") return "done";
  if (taskStatus === "failed" || taskStatus === "abandoned" || taskStatus === "cancelled") return "failed";
  return "running";
}

/** 分布条各段的配置：key → 颜色类 + 标签。顺序决定渲染顺序。
 *
 * 分布 key 用 ``suspend_reason``（后端 ``status_distribution_for_user_task``
 * 按 ``suspended:{suspend_reason}`` 聚合）。每个暂停原因一个 key，前端可以
 * 精确区分「等用户回答」（``waiting_user``，不可继续）和「用户手动停」
 * （``user_stop``，可继续）。
 */
const DISTRIBUTION_SEGMENTS: { key: string; cls: string; label: string }[] = [
  { key: "done", cls: "s-done", label: "已完成" },
  { key: "skipped", cls: "s-done", label: "已跳过" },
  { key: "delivered", cls: "s-rev", label: "待验收" },
  { key: "running", cls: "s-run", label: "进行中" },
  { key: "pending_dispatch", cls: "s-todo", label: "待开始" },
  { key: "suspended:waiting_user", cls: "s-you", label: "等你回答" },
  { key: "suspended:quota_exhausted", cls: "s-you", label: "额度耗尽" },
  { key: "suspended:user_stop", cls: "s-you", label: "已暂停" },
  { key: "suspended:interrupted", cls: "s-you", label: "已中断" },
  { key: "suspended:blocked_by_defect", cls: "s-bug", label: "需处理" },
  { key: "suspended:budget_exhausted", cls: "s-bug", label: "轮次耗尽" },
  { key: "suspended:waiting_system", cls: "s-bug", label: "等待中" },
];

const STATUS_LABELS: Record<string, string> = {
  active: "在办",
  cooling: "冷却",
  done: "办完",
  dropped: "不办了",
};

/** 不可继续的暂停原因：等用户回答（要先回答问题）和撞缺陷（重试无用）。 */
const UNPUSHABLE_SUSPEND_REASONS = new Set([
  "suspended:waiting_user",
  "suspended:blocked_by_defect",
]);

/**
 * 判断有没有可以"继续"的暂停。
 *
 * 用 ``suspend_reason`` 维度判断（与后端 ``_CONTINUE_CANNOT_MOVE`` 同维度）：
 * ``waiting_user`` 要先回答问题、``blocked_by_defect`` 重试必是同样的结果，
 * 这两种不给继续按钮。其余暂停原因（``user_stop``、``interrupted``、
 * ``quota_exhausted`` 等）点继续都能推动。
 */
function hasPushable(distribution: TaskDistribution | null): boolean {
  if (!distribution) return false;
  return Object.entries(distribution).some(
    ([key, count]) =>
      key.startsWith("suspended:") &&
      !UNPUSHABLE_SUSPEND_REASONS.has(key) &&
      (count ?? 0) > 0,
  );
}

/** 需要用户关注的暂停原因：等用户回答、撞缺陷、额度耗尽、待验收。 */
function needsAttention(distribution: TaskDistribution | null): boolean {
  if (!distribution) return false;
  return Object.entries(distribution).some(([key, count]) => {
    if ((count ?? 0) === 0) return false;
    return (
      key === "suspended:waiting_user" ||
      key === "suspended:blocked_by_defect" ||
      key === "suspended:quota_exhausted" ||
      key === "delivered"
    );
  });
}

/**
 * 用户任务卡片（⑦ 界面层）：折叠在对话流里，展示一件事的状态。
 *
 * 折叠行：▶ [迷你分布条] 任务标题  N/M
 * 展开后：分布条 + 状态计数 + 局部图 + 继续按钮（有推得动的暂停时显示）
 * 点继续后就地显示回报（几摊动了/没动/原因）
 */
function UserTaskCard({
  sessionId,
  taskId,
  title,
  status = "active",
  steps = [],
  subagents = [],
  taskIdByExecutorSession: taskIdMapFromScreen = {},
  running = false,
  onOpenFullGraph,
  onOpenExecutor,
}: {
  sessionId: string;
  /** 没建任务的轮次为空——那时卡片只展示这一轮的过程，不拉任务相关数据。 */
  taskId?: string;
  title: string;
  status?: string;
  /** 主助理为这件事做的动作。**只含它自己的**——`subagentId` 非空的那些属于
   *  子代理，要收在子代理卡片后面，点开才看，不能铺在第一层。 */
  steps?: ActivityStep[];
  /** 派出去的执行体。用实时的 turn.subagents（委派一发生就有、自带 anchorSeq），
   *  不从图快照反查——那条链要等建图 + 绑定会话 + 卡片展开，委派当下是空的。 */
  subagents?: Subagent[];
  /** 执行会话 id → task id。todo 按 task_id 存，卡片手上只有会话 id。 */
  taskIdByExecutorSession?: Record<string, string>;
  running?: boolean;
  onOpenFullGraph: (graphId: string, title: string) => void;
  onOpenExecutor: (executorSessionId: string, label: string) => void;
}): JSX.Element {
  const [open, setOpen] = useState(false);
  const [distribution, setDistribution] = useState<TaskDistribution | null>(null);
  const [loadingDist, setLoadingDist] = useState(false);
  const [graphs, setGraphs] = useState<UserTaskGraphSummary[]>([]);
  const [executorTasks, setExecutorTasks] = useState<AssistantTaskSnapshot[]>([]);
  const [todosByTaskId, setTodosByTaskId] = useState<Record<string, AssistantTodoItem[]>>({});
  const [continueResult, setContinueResult] = useState<UserTaskContinueResponse | null>(null);
  const [continuing, setContinuing] = useState(false);
  // 后端 user_task.changed(progress_changed) 到达时递增，驱动卡片重新拉数据
  const userTaskVersion = useAssistantTaskStore((state) => state.userTaskVersion);
  // 执行体的 todolist 用 store 里那份：它由 assistant.todo.changed 事件驱动，
  // 子代理跑到一半创建清单、勾掉一条，卡片正面都会跟着变。自己拉一份就没有这个。
  const storeTodos = useAssistantTaskStore((state) => state.todosByTaskId);
  const loadTodos = useAssistantTaskStore((state) => state.loadTodos);

  const loadDistribution = useCallback(() => {
    if (!taskId) return;
    setLoadingDist(true);
    getUserTaskDistribution(sessionId, taskId)
      .then((res) => setDistribution(res.distribution))
      .catch(() => setDistribution(null))
      .finally(() => setLoadingDist(false));
  }, [sessionId, taskId]);

  // 加载 distribution（summary 需要它显示继续按钮/缺陷标签）。
  // 依赖 userTaskVersion：后端执行节点变化会发 user_task.changed(progress_changed)，
  // store 递增该版本号——否则卡片只在挂载时拉一次，之后执行体跑完、todo 打勾
  // 都看不到，一直停在委派那一刻的快照上。
  useEffect(() => {
    loadDistribution();
  }, [loadDistribution, userTaskVersion]);

  useEffect(() => {
    if (!open || !taskId) return;
    getUserTaskGraphs(sessionId, taskId)
      .then((res) => {
        const gs = res.graphs ?? [];
        setGraphs(gs);
        // 设计 [95]: 图里节点派出去的只从图里进（局部图/全图弹窗）；
        // 卡片下只放直接挂载的执行体。request 容器图（kind!=plan）的节点都是
        // 委派执行体——不管几张、几个节点，一律平铺；plan 图走局部图不在这列。
        const directGraphs = gs.filter((g) => g.kind !== "plan");
        if (directGraphs.length === 0) {
          setExecutorTasks([]);
          return;
        }
        // 拉快照列出这些图的全部执行节点（根容器无 executorSessionId 自然跳过）
        return Promise.all(
          directGraphs.map((g) =>
            getAssistantTaskGraph(sessionId, g.graphId).catch(() => null),
          ),
        ).then((snapshots) => {
          const tasks: AssistantTaskSnapshot[] = [];
          const taskIdsToLoad: string[] = [];
          for (const snap of snapshots) {
            if (!snap) continue;
            for (const t of snap.tasks) {
              // 已完成的也要列出来：用户要能回头看历史任务里子代理干了什么
              // （它的 todolist、工具调用、msg）——任务办完之后卡片变空，
              // 等于把过程记录藏了。
              if (t.executorSessionId) {
                tasks.push(t);
                taskIdsToLoad.push(t.taskId);
              }
            }
          }
          setExecutorTasks(tasks);
          // 加载这些执行体的 todo（⑦ 核心规则：执行体卡片正面展示 todolist）
          return Promise.all(
            taskIdsToLoad.map((tid) =>
              getAssistantTaskTodos(sessionId, tid)
                .then((r) => ({ tid, items: r.items }))
                .catch(() => ({ tid, items: [] as AssistantTodoItem[] })),
            ),
          );
        }).then((todoResults) => {
          if (!todoResults) return;
          const map: Record<string, AssistantTodoItem[]> = {};
          for (const { tid, items } of todoResults) {
            map[tid] = items;
          }
          setTodosByTaskId(map);
        });
      })
      .catch(() => {
        setGraphs([]);
        setExecutorTasks([]);
      });
  }, [open, sessionId, taskId, loadDistribution, userTaskVersion]);

  const total = distribution
    ? Object.values(distribution).reduce((a, b) => a + b, 0)
    : 0;
  const done =
    (distribution?.["done"] ?? 0) + (distribution?.["skipped"] ?? 0);

  // 三类东西按发生顺序合成一个流：主助理的 msg（step.seq）、派出去的执行体
  // （anchorSeq = 委派那一刻的步骤号）、建的任务图（启动图那一步的步骤号）。
  // 三者必须是同一个量纲——本轮内的步骤计数，见 timelineOrder.ts。
  // 同一 seq 时用 tie 决定先后：msg → 执行体 → 任务图。
  // 只有 planner 的 DAG（kind=plan）画局部图；request 容器图的节点是委派执行体，
  // 一律平铺为执行体卡片（真机验证踩中：request 图 nodeCount>1 被当任务图展示）。
  const graphsWithNodes = graphs.filter((g) => g.kind === "plan" && g.nodeCount > 1);

  // 子代理刚出现时它可能还没建 todolist；等它建了会发 assistant.todo.changed，
  // store 走 resync 补上。这里只负责首次把已有的拉进来。
  useEffect(() => {
    for (const sub of subagents) {
      const tid = sub.taskId ?? taskIdMapFromScreen[sub.subagentId];
      if (tid && !(tid in storeTodos)) {
        void loadTodos(sessionId, tid);
      }
    }
  }, [subagents, storeTodos, loadTodos, sessionId, taskIdMapFromScreen]);

  // todo 按 task_id 存，而执行体卡片手上只有会话 id——用图快照建立映射
  const taskIdByExecutorSession = useMemo(() => {
    const map: Record<string, string> = { ...taskIdMapFromScreen };
    for (const t of executorTasks) {
      if (t.executorSessionId) map[t.executorSessionId] = t.taskId;
    }
    return map;
  }, [executorTasks, taskIdMapFromScreen]);

  const timeline = useMemo(() => {
    const entries: { seq: number; tie: number; node: JSX.Element }[] = [];
    for (const step of steps) {
      entries.push({
        seq: step.seq,
        tie: 0,
        node: (
          <div key={`step_${step.seq}`} className="assistant-step" data-kind={step.kind}>
            <ActivityStepRow
              kind={step.kind}
              seq={step.seq}
              toolName={step.toolName}
              text={step.text}
              redacted={step.redacted}
            />
          </div>
        ),
      });
    }
    for (const sub of subagents) {
      // 委派那一刻的步骤号；两条路都查不到时落到末尾，不硬塞开头造成假顺序
      const taskId = sub.taskId ?? taskIdByExecutorSession[sub.subagentId];
      // plan 图（DAG）节点的执行体不平铺——它们从局部图/全图弹窗里看。
      //
      // 归属由执行体自带（后端按 attempt→task→图根反查 graph_kind），不再靠本卡片
      // 拉 plan 图快照收集节点 id 去比对：那份名单是会话级事实，却存在卡片私有
      // state 里，而只有第一个过程块的卡片绑着用户任务、才会去加载它——其余每一轮
      // 的卡片名单恒空，DAG 节点的执行体于是全被平铺出来（真机发现）。
      // graphKind 为空 = 归属未知（无 attempt / 图根缺失），宁可平铺不隐藏。
      if (sub.graphKind === "plan") continue;
      entries.push({
        // 实时锚点优先；重启后内存里没有它，从过程记录里按 taskId 找回委派那一步
        seq: sub.anchorSeq ?? executorAnchorSeq(steps, taskId),
        tie: 1,
        node: (
          <ExecutorCard
            key={`exec_${sub.subagentId}`}
            summary={{
              subagentId: sub.subagentId,
              label: sub.label,
              task: sub.task,
              status: sub.status,
              lastOutput: sub.lastOutput ?? null,
              turnStartSequence: null,
            }}
            todos={taskId ? (storeTodos[taskId] ?? todosByTaskId[taskId]) : undefined}
            onClick={() => onOpenExecutor(sub.subagentId, sub.label)}
          />
        ),
      });
    }
    for (const g of graphsWithNodes) {
      entries.push({
        seq: graphAnchorSeq(steps, g.graphId),
        tie: 2,
        node: (
          <TaskGraphPeek
            key={`graph_${g.graphId}`}
            sessionId={sessionId}
            graphId={g.graphId}
            title={g.title}
            onOpenFullGraph={() => onOpenFullGraph(g.graphId, title)}
          />
        ),
      });
    }
    return entries.sort((a, b) => a.seq - b.seq || a.tie - b.tie);
  }, [
    steps,
    subagents,
    graphsWithNodes,
    todosByTaskId,
    storeTodos,
    taskIdByExecutorSession,
    sessionId,
    title,
    onOpenExecutor,
    onOpenFullGraph,
  ]);

  const showContinue = Boolean(taskId) && hasPushable(distribution);
  const defectCount = distribution?.["suspended:blocked_by_defect"] ?? 0;
  const hasDefect = defectCount > 0;
  const shouldAutoOpen = needsAttention(distribution) || continueResult != null;

  useEffect(() => {
    if (shouldAutoOpen) setOpen(true);
  }, [shouldAutoOpen]);

  const handleContinue = () => {
    if (!taskId) return; // 没建任务就没有"继续"这回事，按钮本身也不会出现
    setContinuing(true);
    setContinueResult(null);
    continueUserTask(sessionId, taskId)
      .then((res) => {
        setContinueResult(res);
        loadDistribution();
      })
      .catch(() => {
        setContinueResult({
          pushed: [],
          notPushed: [],
          stillFinishing: [],
          total: 0,
          success: false,
        });
      })
      .finally(() => setContinuing(false));
  };

  // 迷你分布条段
  const miniSegments = DISTRIBUTION_SEGMENTS.filter(
    (seg) => (distribution?.[seg.key] ?? 0) > 0,
  );

  // 多节点图（nodeCount > 1）才显示局部图入口

  return (
    <details
      className="assistant-activity me-task-fold"
      open={open}
      onToggle={(e) => setOpen(e.currentTarget.open)}
    >
      <summary>
        {loadingDist && open ? (
          <Loader2 size={13} className="assistant-spin" />
        ) : (
          <ChevronRight size={13} className={`me-chev${open ? " me-chev-open" : ""}`} />
        )}
        {miniSegments.length > 0 ? (
          <span className="me-mini">
            {miniSegments.map((seg) => (
              <i
                key={seg.key}
                className={seg.cls}
                style={{ flex: distribution?.[seg.key] ?? 0 }}
              />
            ))}
          </span>
        ) : null}
        <span className="me-task-fold-title">{title}</span>
        {total > 0 ? (
          <span className="assistant-activity-count">
            {done}/{total}
          </span>
        ) : null}
        {hasDefect ? (
          <span className="me-attention-tag">需处理</span>
        ) : null}
        {showContinue ? (
          <button
            type="button"
            className="assistant-activity-graph-btn assistant-activity-graph-continue"
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              handleContinue();
            }}
            disabled={continuing}
            title="继续这件事"
          >
            {continuing ? <Loader2 size={12} className="assistant-spin" /> : <Play size={12} />}
            继续
          </button>
        ) : null}
      </summary>
      <div className="assistant-activity-body">
        <div className="me-task">
          {/* 标题行 + 状态标签 */}
          <div className="me-task-head">
            <span className="me-task-title">{title}</span>
            {/* 没建任务的轮次没有"在办/办完"这种状态可言，标签留空 */}
            {taskId ? (
              <span className="me-pill" data-status={status}>
                {STATUS_LABELS[status] ?? status}
              </span>
            ) : null}
          </div>

          {/* 分布条 */}
          {miniSegments.length > 0 ? (
            <>
              <div className="me-bar">
                {miniSegments.map((seg) => (
                  <i
                    key={seg.key}
                    className={seg.cls}
                    style={{ flex: distribution?.[seg.key] ?? 0 }}
                  />
                ))}
              </div>
              <div className="me-legend">
                {miniSegments.map((seg) => (
                  <span key={seg.key}>
                    <i className={seg.cls} />
                    <b>
                      {seg.label} {distribution?.[seg.key] ?? 0}
                    </b>
                  </span>
                ))}
              </div>
            </>
          ) : (
            <p className="me-empty">暂无执行进度</p>
          )}

          {/* 主助理为这件事做的过程：msg、派出去的执行体卡片、建的任务图，
              **按发生顺序排成一个流**——它可能先调研一番、再建图、再委派，
              这些就该按这个次序出现，而不是分成三堆各占一块。
              抽屉里是同一个形状（那一层的 msg + 它派出去的下一层）。 */}
          {timeline.length > 0 ? (
            <div className="me-task-flow">
              {timeline.map((entry) => entry.node)}
            </div>
          ) : null}

          {/* 撞缺陷提示（设计 295 行：不给「继续」，给说明） */}
          {hasDefect ? (
            <p className="me-defect-notice">
              有 {defectCount} 步遇到程序问题，做不下去了。已记录详情，正在处理。
            </p>
          ) : null}

          {/* 额度耗尽提示（设计 307-308 行：只提示这一种原因） */}
          {(distribution?.["suspended:quota_exhausted"] ?? 0) > 0 ? (
            <p className="me-defect-notice">模型额度耗尽。</p>
          ) : null}

          {/* 继续回报 */}
          {continueResult ? (
            <div className="me-report">
              {continueResult.success ? (
                <p className="me-report-head">
                  已继续 · {continueResult.pushed.length + continueResult.notPushed.length + continueResult.stillFinishing.length} 摊里动了{" "}
                  {continueResult.pushed.length} 摊
                </p>
              ) : (
                <p className="me-report-head me-report-fail">
                  没有推动任何任务
                </p>
              )}
              {continueResult.pushed.length > 0 ? (
                <ul className="me-report-list">
                  {continueResult.pushed.map((item, i) => (
                    <li key={`p${i}`} className="me-report-pushed">
                      动了 &nbsp;{item.title} —— 已重新开工
                    </li>
                  ))}
                </ul>
              ) : null}
              {continueResult.stillFinishing.length > 0 ? (
                <ul className="me-report-list">
                  {continueResult.stillFinishing.map((item, i) => (
                    <li key={`s${i}`} className="me-report-blocked">
                      收尾中 &nbsp;{item.title} —— {item.reason ?? "正在收尾，尚未重新开工"}
                    </li>
                  ))}
                </ul>
              ) : null}
              {continueResult.notPushed.length > 0 ? (
                <ul className="me-report-list">
                  {continueResult.notPushed.map((item, i) => (
                    <li key={`n${i}`} className="me-report-blocked">
                      没动 &nbsp;{item.title} —— {item.reason}
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          ) : null}
        </div>
      </div>
    </details>
  );
}

export default UserTaskCard;
