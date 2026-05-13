export function SafeMarkdown({ content }: { content: string }): JSX.Element {
  const lines = content.split(/\r?\n/);
  return (
    <div className="assistant-markdown">
      {lines.map((line, index) => {
        if (line.startsWith("### ")) {
          return <h4 key={`${line}-${index}`}>{line.slice(4)}</h4>;
        }
        if (line.startsWith("- ")) {
          return <p key={`${line}-${index}`}>• {line.slice(2)}</p>;
        }
        return <p key={`${line}-${index}`}>{line || "\u00a0"}</p>;
      })}
    </div>
  );
}

export default SafeMarkdown;
