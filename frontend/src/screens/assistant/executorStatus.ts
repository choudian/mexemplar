import type { NodeTone } from "../../components/taskGraph/layoutDag";

/**
 * 把 SubagentStatus（running/done/suspended/failed）映射成视觉色调（data-t）。
 *
 * 用于执行体卡片的状态标签（`.st[data-t]`）。
 */
export function subagentStatusTone(status: string): NodeTone {
  switch (status) {
    case "done":
      return "done";
    case "running":
      return "run";
    case "suspended":
      return "you";
    case "failed":
      return "bug";
    default:
      return "todo";
  }
}

/** 执行体详情打开期间的刷新间隔。抽屉与任务图弹窗共用同一节奏。
 *  执行体一步通常几秒到几十秒，3s 够跟上又不至于打搅后端。 */
export const EXECUTOR_REFRESH_MS = 3000;
