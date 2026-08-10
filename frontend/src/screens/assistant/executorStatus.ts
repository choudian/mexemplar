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
