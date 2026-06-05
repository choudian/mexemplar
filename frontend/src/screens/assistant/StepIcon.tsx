import { Brain, Wrench, CornerDownRight } from "lucide-react";

import type { ActivityStepKind } from "../../state/assistantTypes";

/** 活动步骤图标（reasoning / tool_call / tool_result）——共享于 ActivityTimeline 与 SubagentDetailDrawer。 */
export function StepIcon({ kind }: { kind: ActivityStepKind }): JSX.Element {
  if (kind === "tool_call") return <Wrench size={13} />;
  if (kind === "tool_result") return <CornerDownRight size={13} />;
  return <Brain size={13} />;
}
