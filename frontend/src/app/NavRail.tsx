import { ChevronRight } from "lucide-react";

import { routes } from "./routes";
import type { RouteId } from "../state/shellStore";

interface NavRailProps {
  activeRoute: RouteId;
  counts: {
    pendingSkillCount: number;
    publishedSkillCount: number;
    failureCount: number;
    compositionCount: number;
  };
  userDisplayName: string;
  userStatusLabel: string;
  onRouteChange: (route: RouteId) => void;
}

function badgeForRoute(route: RouteId, counts: NavRailProps["counts"]): number | null {
  if (route === "skills") {
    return counts.pendingSkillCount + counts.publishedSkillCount + counts.failureCount;
  }
  if (route === "compositions") {
    return counts.compositionCount;
  }
  return null;
}

export function NavRail({
  activeRoute,
  counts,
  userDisplayName,
  userStatusLabel,
  onRouteChange,
}: NavRailProps): JSX.Element {
  return (
    <nav
      aria-label="主导航"
      style={{
        display: "flex",
        width: 220,
        flexShrink: 0,
        flexDirection: "column",
        borderRight: "1px solid var(--border-1)",
        background: "var(--surface-2)",
      }}
    >
      <div
        style={{
          display: "flex",
          height: 38,
          alignItems: "center",
          gap: 9,
          padding: "0 14px",
          borderBottom: "1px solid var(--border-1)",
          fontWeight: 700,
        }}
      >
        <span
          aria-hidden="true"
          style={{
            width: 22,
            height: 22,
            borderRadius: 7,
            background: "var(--accent)",
            display: "inline-block",
          }}
        />
        Mexemplar
      </div>

      <div style={{ display: "flex", flex: 1, flexDirection: "column", gap: 2, padding: 18 }}>
        {routes.map((route) => {
          const Icon = route.icon;
          const active = route.id === activeRoute;
          const badge = badgeForRoute(route.id, counts);
          return (
            <button
              key={route.id}
              type="button"
              aria-current={active ? "page" : undefined}
              onClick={() => onRouteChange(route.id)}
              style={{
                display: "flex",
                width: "100%",
                height: 36,
                alignItems: "center",
                gap: 11,
                padding: "0 12px",
                cursor: "pointer",
                border: 0,
                borderRadius: "var(--radius-md)",
                background: active ? "var(--accent-weak)" : "transparent",
                color: active ? "var(--accent)" : "var(--text-2)",
                fontWeight: active ? 700 : 600,
                textAlign: "left",
              }}
            >
              <Icon size={17} strokeWidth={active ? 2.2 : 1.8} />
              <span style={{ flex: 1 }}>{route.label}</span>
              {badge !== null ? <span className="me-badge">{badge}</span> : null}
            </button>
          );
        })}
      </div>

      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 10,
          padding: 12,
          borderTop: "1px solid var(--border-1)",
        }}
      >
        <div
          aria-hidden="true"
          style={{
            width: 30,
            height: 30,
            borderRadius: "50%",
            background: "linear-gradient(135deg, var(--accent), oklch(70% 0.06 195))",
          }}
        />
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontSize: 12.5 }}>
            {userDisplayName}
          </div>
          <div style={{ color: "var(--text-muted)", fontSize: 10.5 }}>{userStatusLabel}</div>
        </div>
        <ChevronRight size={14} aria-hidden="true" />
      </div>
    </nav>
  );
}
