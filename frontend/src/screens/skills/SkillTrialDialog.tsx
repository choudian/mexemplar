import { X } from "lucide-react";

import { IconButton } from "../../components/primitives";
import { useTeachingStore } from "../../state/teachingStore";
import { TrialStage } from "../teaching/TrialStage";

export function SkillTrialDialog(): JSX.Element | null {
  const skillTrialToolId = useTeachingStore((state) => state.skillTrialToolId);
  const closeSkillTrial = useTeachingStore((state) => state.closeSkillTrial);

  if (!skillTrialToolId) return null;

  return (
    <div className="trial-dialog-overlay" onClick={closeSkillTrial} role="presentation">
      <div
        className="trial-dialog trial-dialog--wide"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-label="技能试用"
      >
        <div className="trial-dialog-header">
          <h3>技能试用</h3>
          <IconButton label="关闭" onClick={closeSkillTrial}>
            <X size={16} />
          </IconButton>
        </div>
        <div className="trial-dialog-body">
          <TrialStage />
        </div>
      </div>
    </div>
  );
}

export default SkillTrialDialog;
