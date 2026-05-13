import type { ButtonHTMLAttributes, PropsWithChildren, ReactNode } from "react";

export function Button({
  children,
  kind = "primary",
  ...props
}: PropsWithChildren<
  ButtonHTMLAttributes<HTMLButtonElement> & { kind?: "primary" | "secondary" | "ghost" | "danger" }
>) {
  return (
    <button className={`me-button me-button-${kind}`} type="button" {...props}>
      {children}
    </button>
  );
}

export function IconButton({
  label,
  children,
  ...props
}: PropsWithChildren<ButtonHTMLAttributes<HTMLButtonElement> & { label: string }>) {
  return (
    <button className="me-icon-button" type="button" aria-label={label} title={label} {...props}>
      {children}
    </button>
  );
}

export function Badge({
  children,
  tone = "neutral",
}: PropsWithChildren<{ tone?: "neutral" | "ok" | "warn" | "danger" }>) {
  return <span className={`me-badge me-badge-${tone}`}>{children}</span>;
}

export function Panel({ title, children, action }: PropsWithChildren<{ title: string; action?: ReactNode }>) {
  return (
    <section className="me-panel" aria-labelledby={`${title}-heading`}>
      <div className="me-panel-header">
        <h2 id={`${title}-heading`}>{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}
