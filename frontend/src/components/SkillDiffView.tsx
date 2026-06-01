import { useState } from "react";

import { Button } from "./primitives";

function lineKind(line: string): "add" | "remove" | "meta" | "context" {
  if (line.startsWith("+++") || line.startsWith("---") || line.startsWith("@@")) return "meta";
  if (line.startsWith("+")) return "add";
  if (line.startsWith("-")) return "remove";
  return "context";
}

export function SkillDiffView({
  body,
  diff,
}: {
  body: string;
  diff: string | null;
}): JSX.Element {
  const [mode, setMode] = useState<"body" | "diff">(diff ? "diff" : "body");
  const content = mode === "diff" ? diff || "首个版本无差异" : body;

  return (
    <div className="skill-diff-view">
      <div className="skill-diff-toggle">
        <Button kind={mode === "diff" ? "primary" : "ghost"} disabled={!diff} onClick={() => setMode("diff")}>
          Diff
        </Button>
        <Button kind={mode === "body" ? "primary" : "ghost"} onClick={() => setMode("body")}>
          正文
        </Button>
      </div>
      <pre className="skill-diff-pre">
        {String(content)
          .split("\n")
          .map((line, index) => (
            <span data-kind={lineKind(line)} key={`${index}-${line.slice(0, 8)}`}>
              {line || " "}
            </span>
          ))}
      </pre>
    </div>
  );
}

export default SkillDiffView;
