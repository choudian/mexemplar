import { ChevronRight } from "lucide-react";

import { routes } from "./routes";
import type { RouteId } from "../state/shellStore";
import { useBrainStore } from "../state/brainStore";
import { useSkillMethodologyStore } from "../state/skillMethodologyStore";

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

function badgeForRoute(
  route: RouteId,
  counts: NavRailProps["counts"],
  methodologyUnread: number,
  pendingProposalCount: number,
): number | null {
  if (route === "skills") {
    return counts.pendingSkillCount || null;
  }
  if (route === "skill-methodology") {
    return methodologyUnread || null;
  }
  // FR-020：pending_review 提案在全局大脑导航项上可见，避免静悄悄躺在管理屏无人知。
  if (route === "brain") {
    return pendingProposalCount || null;
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
  const methodologyUnread = useSkillMethodologyStore((state) => state.unreadBadgeCount);
  const pendingProposalCount = useBrainStore(
    (state) => state.improvementProposals.filter((p) => p.status === "pending_review").length,
  );
  return (
    <nav
      aria-label="主导航"
      className="me-nav-rail"
    >
      <div className="me-nav-brand">
        <span className="me-logo-mark" aria-hidden="true">
          <span />
          <i />
        </span>
        <span className="me-logo-text">
          <strong>Mexemplar</strong>
          <small>师徒模式 · 桌面助手</small>
        </span>
      </div>

      <div className="me-nav-list">
        {routes.map((route) => {
          const Icon = route.icon;
          const active = route.id === activeRoute;
          const badge = badgeForRoute(route.id, counts, methodologyUnread, pendingProposalCount);
          return (
            <button
              className="me-nav-item"
              key={route.id}
              data-active={active}
              type="button"
              aria-current={active ? "page" : undefined}
              onClick={() => onRouteChange(route.id)}
            >
              <Icon size={17} strokeWidth={active ? 2.2 : 1.8} />
              <span style={{ flex: 1 }}>{route.label}</span>
              {badge !== null ? <span className="me-badge">{badge}</span> : null}
            </button>
          );
        })}
      </div>

      <div className="me-user-card">
        <div className="me-user-avatar" aria-hidden="true">
          {userDisplayName.trim().slice(0, 1) || "M"}
        </div>
        <div className="me-user-copy">
          <div>{userDisplayName}</div>
          <small>{userStatusLabel}</small>
        </div>
        <ChevronRight size={14} aria-hidden="true" />
      </div>
    </nav>
  );
}
