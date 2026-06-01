import { Bot, ChevronDown, ChevronUp } from "lucide-react";
import { useState } from "react";

import { Button } from "../../components/primitives";
import EquipmentPanel from "./EquipmentPanel";

export function AssistantEquipmentCard(): JSX.Element {
  const [open, setOpen] = useState(false);
  return (
    <section className="assistant-equipment-card" aria-label="Assistant 本体方法论装备">
      <div>
        <span className="assistant-equipment-icon">
          <Bot size={16} />
        </span>
        <div>
          <strong>Assistant 本体</strong>
          <small>管理主助理可按需 load 的方法论清单</small>
        </div>
      </div>
      <Button kind="secondary" onClick={() => setOpen((value) => !value)}>
        {open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        装备
      </Button>
      {open ? <EquipmentPanel compact entityId="_assistant" /> : null}
    </section>
  );
}

export default AssistantEquipmentCard;
