import { memo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

const REMARK_PLUGINS = [remarkGfm];

export const SafeMarkdown = memo(function SafeMarkdown({ content }: { content: string }): JSX.Element {
  return (
    <div className="assistant-markdown">
      <ReactMarkdown remarkPlugins={REMARK_PLUGINS}>{content}</ReactMarkdown>
    </div>
  );
});

export default SafeMarkdown;
