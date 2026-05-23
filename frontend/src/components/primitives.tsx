import type { ButtonHTMLAttributes, PropsWithChildren } from "react";

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

export function Toggle({
  pressed,
  onPressedChange,
  children,
  label,
  ...props
}: PropsWithChildren<
  ButtonHTMLAttributes<HTMLButtonElement> & {
    pressed: boolean;
    onPressedChange: (pressed: boolean) => void;
    label: string;
  }
>) {
  return (
    <button
      className={`me-toggle ${pressed ? "me-toggle-active" : ""}`}
      type="button"
      role="switch"
      aria-checked={pressed}
      aria-label={label}
      title={label}
      onClick={() => onPressedChange(!pressed)}
      {...props}
    >
      {children}
    </button>
  );
}