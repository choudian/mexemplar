import { MessageSquare, Network, Settings, Sparkles, Workflow } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import AssistantScreen from "../screens/assistant/AssistantScreen";
import CompositionListScreen from "../screens/compositions/CompositionListScreen";
import SettingsScreen from "../screens/settings/SettingsScreen";
import SkillListScreen from "../screens/skills/SkillListScreen";
import TeachingScreen from "../screens/teaching/TeachingScreen";
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
    label: "技能教学",
    shortLabel: "教学",
    icon: Sparkles,
    render: () => <TeachingScreen />,
  },
  {
    id: "skills",
    label: "技能列表",
    shortLabel: "技能",
    icon: Workflow,
    render: () => <SkillListScreen />,
  },
  {
    id: "compositions",
    label: "技能组合",
    shortLabel: "组合",
    icon: Network,
    render: () => <CompositionListScreen />,
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
