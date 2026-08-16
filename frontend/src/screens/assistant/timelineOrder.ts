import type { ActivityStep } from "../../state/assistantTypes";

/** 缺锚点的东西排到末尾——不硬塞开头，免得造成"它先发生"的假顺序。 */
export const NO_ANCHOR = Number.MAX_SAFE_INTEGER;

/**
 * 任务图在卡片时间流里的位置：主助理「启动图」那一步。
 *
 * 不能用图自己的 `userMessageSequence`——那是消息表里的序号（本轮用户消息
 * 是第几条），而同一个流里的 msg 和执行体用的是**本轮内的步骤计数**
 * （1、2、3…）。两个量纲混着排，图就会落在完全无关的位置：真机上一张
 * `userMessageSequence=2` 的图被排到了第 2 个步骤「创建任务」后面，而它
 * 其实是第 13 步才启动的。
 *
 * 按 graphId 在步骤文本里配对，所以一轮建多张图也各归各位。
 */
export function graphAnchorSeq(steps: ActivityStep[], graphId: string): number {
  return lastStepSeqMatching(steps, (name) => name === "start_graph", graphId);
}

/**
 * 执行体在卡片时间流里的位置：主助理「派出去」那一步。
 *
 * 执行体自带的 `anchorSeq` 来自实时事件（委派当下最后一个步骤号），只活在
 * 内存里。应用一重启，权威列表 `listSubagents` 补得回卡片却补不回锚点，
 * 执行体就会全部堆到时间流末尾，不再穿插在主助理的动作之间。这里按
 * 委派结果里的 taskId 从过程记录里把那一步找回来。
 */
export function executorAnchorSeq(steps: ActivityStep[], taskId: string | null | undefined): number {
  if (!taskId) return NO_ANCHOR;
  return lastStepSeqMatching(steps, (name) => name.startsWith("delegate_to"), taskId);
}

/** 找最后一个「工具名匹配 + 文本里带这个 id」的步骤号。 */
function lastStepSeqMatching(
  steps: ActivityStep[],
  matchToolName: (toolName: string) => boolean,
  id: string,
): number {
  let anchor: number | null = null;
  for (const step of steps) {
    if (!step.toolName || !matchToolName(step.toolName)) continue;
    if (!step.text || !step.text.includes(id)) continue;
    // 调用和结果两步都可能命中，取靠后的：卡片该出现在动作完成之后
    anchor = anchor === null ? step.seq : Math.max(anchor, step.seq);
  }
  return anchor ?? NO_ANCHOR;
}
