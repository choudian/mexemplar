import { BookOpenCheck, Brain, ListTodo, MessageSquare, Network, Settings, Sparkles, UserCog, Workflow } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import AssistantScreen from "../screens/assistant/AssistantScreen";
import BrainScreen from "../screens/BrainScreen";
import CompositionListScreen from "../screens/compositions/CompositionListScreen";
import DebugScreen from "../screens/debug/DebugScreen";
import SettingsScreen from "../screens/settings/SettingsScreen";
import SkillMethodologyScreen from "../screens/SkillMethodologyScreen";
import SkillListScreen from "../screens/skills/SkillListScreen";
import SpecialistScreen from "../screens/SpecialistScreen";
import TeachingScreen from "../screens/teaching/TeachingScreen";
import UserTodoScreen from "../screens/UserTodoScreen/UserTodoScreen";
import type { RouteId } from "../state/shellStore";

export interface RouteDefinition {
  id: RouteId;
  label: string;
  shortLabel: string;
  icon: LucideIcon;
  render: () => JSX.Element;
}

export const routes: RouteDefinition[] = [
  {
    id: "assistant",
    label: "AI 助手",
    shortLabel: "助手",
    icon: MessageSquare,
    render: () => <AssistantScreen />,
  },
  {
    id: "teaching",
    label: "工具教学",
    shortLabel: "教学",
    icon: Sparkles,
    render: () => <TeachingScreen />,
  },
  {
    id: "skills",
    label: "工具列表",
    shortLabel: "工具",
    icon: Workflow,
    render: () => <SkillListScreen />,
  },
  {
    id: "compositions",
    label: "工具组合",
    shortLabel: "组合",
    icon: Network,
    render: () => <CompositionListScreen />,
  },
  {
    id: "user-todos",
    label: "待办列表",
    shortLabel: "待办",
    icon: ListTodo,
    render: () => <UserTodoScreen />,
  },
  {
    id: "brain",
    label: "大脑管理",
    shortLabel: "大脑",
    icon: Brain,
    render: () => <BrainScreen />,
  },
  {
    id: "brain-specialists",
    label: "专员管理",
    shortLabel: "专员",
    icon: UserCog,
    render: () => <SpecialistScreen />,
  },
  {
    id: "skill-methodology",
    label: "方法论 / Skill",
    shortLabel: "方法论",
    icon: BookOpenCheck,
    render: () => <SkillMethodologyScreen />,
  },
  {
    id: "settings",
    label: "应用设置",
    shortLabel: "设置",
    icon: Settings,
    render: () => <SettingsScreen />,
  },
];

export function getRoute(routeId: RouteId): RouteDefinition {
  return routes.find((route) => route.id === routeId) ?? routes[0];
}

export const routePaths: Record<RouteId, string> = {
  assistant: "/",
  teaching: "/tools/teaching",
  skills: "/tools/list",
  compositions: "/tools/compositions",
  "user-todos": "/todos",
  brain: "/brain",
  "brain-specialists": "/brain/specialists",
  "skill-methodology": "/skills/methodology",
  settings: "/settings",
};

// sorted longest-first so /brain/specialists matches before /brain in routeIdFromPath
const _ROUTE_PATH_ENTRIES = (Object.entries(routePaths) as [RouteId, string][]).sort(
  (a, b) => b[1].length - a[1].length,
);

export function routeIdFromPath(pathname: string): RouteId | null {
  for (const [id, path] of _ROUTE_PATH_ENTRIES) {
    if (path === "/") {
      if (pathname === "/" || pathname === "") return id;
    } else if (pathname.startsWith(path)) {
      return id;
    }
  }
  return null;
}

export function redirectPathFor(pathname: string, search = ""): string | null {
  if (pathname === "/skills") return `/tools/list${search}`;
  if (pathname.startsWith("/skills/teaching")) {
    return "/tools/teaching" + pathname.slice("/skills/teaching".length) + search;
  }
  if (pathname.startsWith("/skills/compositions")) {
    return "/tools/compositions" + pathname.slice("/skills/compositions".length) + search;
  }
  // catch-all: any other /skills/* path (except /skills/methodology) → /tools/list
  if (pathname.startsWith("/skills/") && !pathname.startsWith("/skills/methodology")) {
    return `/tools/list${search}`;
  }
  return null;
}

export interface HiddenRouteDefinition {
  id: "debug";
  label: string;
  render: () => JSX.Element;
}

export function getHiddenRoute(pathname: string): HiddenRouteDefinition | null {
  if (pathname === "/debug") {
    return {
      id: "debug",
      label: "Debug Inspector",
      render: () => <DebugScreen />,
    };
  }
  return null;
}
