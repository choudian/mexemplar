"""Pure helpers for building skill composition trial prompts."""

from typing import Any, Dict, List, Optional

from src.data.models import (
    MODE_DISPLAY_TEXT,
    SkillComposition,
    Tool,
    sort_composition_members,
)

from .types import SkillCompositionError


def build_trial_bootstrap_input() -> Dict[str, str]:
    """Construct the first program message for dialog-style trials."""
    return {
        "role": "program",
        "content": (
            "现在开始这次技能组合试用对话。"
            "请你主动向用户发起第一轮沟通，不要把这条消息当成用户需求。"
            "不要复述系统规则，不要先讲长篇说明，也不要模板化寒暄。"
            "请直接根据当前技能组合情况，用自然口吻问出第一句最关键的问题。"
        ),
    }


def get_first_member_tool(composition: SkillComposition) -> Optional[Tool]:
    if not composition.members:
        return None
    ordered_members = sort_composition_members(composition.members, composition.mode)
    return ordered_members[0].tool


def build_trial_user_input(
    composition: SkillComposition,
    task: str,
    context: str = "",
) -> str:
    return "\n".join(
        [
            f"请试用技能组合“{composition.composition_name}”来完成下面的任务。",
            f"任务：{task.strip()}",
            f"上下文：{(context or '').strip() or '无'}",
        ]
    )


def normalize_trial_dialog_input(user_input: Any) -> Any:
    if isinstance(user_input, dict):
        role = str(user_input.get("role") or "").strip()
        content = str(user_input.get("content") or "").strip()
        if not role or not content:
            raise SkillCompositionError("补充信息不能为空")
        normalized_input = dict(user_input)
        normalized_input["role"] = role
        normalized_input["content"] = content
        return normalized_input

    text = str(user_input or "").strip()
    if not text:
        raise SkillCompositionError("补充信息不能为空")
    return text


def format_trial_parameter_lines(parameters: List[Dict[str, Any]]) -> List[str]:
    if not parameters:
        return ["- 第 1 步无需额外输入，可以直接开始。"]

    lines = []
    for param in parameters:
        description = str(param.get("description") or param.get("name") or "未命名输入").strip()
        internal_name = str(param.get("name") or description).strip()
        required = bool(param.get("required"))
        default = param.get("default")

        if required:
            attr = "必填"
        elif default is not None:
            attr = f"选填，默认 {default}"
        else:
            attr = "选填"

        lines.append(f"- {description}（内部名：{internal_name}，{attr}）")
    return lines


def build_ordered_trial_guidance_lines(composition: SkillComposition) -> List[str]:
    first_tool = get_first_member_tool(composition)
    lines = [
        "## 顺序型组合引导要求",
        "- 顺序型组合的完整目标有四件事：先拿到用户整体想完成的任务，再拿到第 1 步启动所需信息，再按顺序完成整件事，最后把最终结果反馈给用户。",
        "- 先判断这个技能组合按当前配置是否真的适合完成用户的任务，再决定怎么往下推进。",
        "- 如果用户还没有明确说这次想通过这个技能组合完成什么任务，就先和用户沟通把整体目标问清楚。",
        "- 在真正启动技能组合前，除了整体目标，还要结合第 1 步技能的信息，判断启动第一步还缺哪些信息。",
        "- 还要判断当前顺序是否合理；如果为了完成任务，你判断更合适的路径更像是 1-3-2 而不是当前配置的 1-2-3，要明确告诉用户现在这个顺序可能不太对。",
        "- 如果顺序不理想但并不妨碍完成任务，要先征求用户意见；用户接受就继续，以完成任务为第一优先。",
        "- 跟用户沟通时不要说“参数”“字段”“变量”“内部名”这类技术词，要把问题翻译成自然语言。",
        "- 缺信息时优先一次问齐整体目标和第 1 步关键缺口，不要拆成机械式逐项盘问。",
        "- 如果用户一句话里已经把整体目标和第 1 步所需信息说全了，就直接启动，不要重复确认。",
        "- 技能组合启动后不要只停在第 1 步，要继续推进直到用户的整体任务完成，或者明确说明卡点。",
    ]

    if first_tool is None:
        lines.append("- 当前无法识别第 1 步技能，请先问清整体目标，再按既定顺序尝试启动组合。")
        return lines

    lines.extend(
        [
            f"- 第 1 步技能：{first_tool.tool_name}",
            f"- 第 1 步说明：{first_tool.description or '无'}",
            "- 第 1 步可参考的输入说明：",
            *format_trial_parameter_lines(first_tool.parameters or []),
        ]
    )
    return lines


def build_trial_system_prompt(composition: SkillComposition) -> str:
    mode_text = MODE_DISPLAY_TEXT.get(composition.mode, composition.mode)
    ordered_members = sort_composition_members(composition.members, composition.mode)
    member_names = [
        member.tool.tool_name if member.tool else member.tool_id for member in ordered_members
    ]

    lines = [
        "你是 Exemplar 的试用助手。你正在帮助用户试用一个刚组装好的技能组合。",
        "",
        "⚠️ 重要说明：这个技能组合还处于验证阶段。",
        "组合衔接不顺、成员技能不匹配、结果不对、需要补信息，都是正常现象。",
        "试用的目标是尽快发现问题、验证价值，而不是硬撑着把流程跑完。",
        "",
        "## 本次试用的技能组合",
        f"**组合名称**：{composition.composition_name}",
        f"**组合类型**：{mode_text}",
        f"**组合说明**：{composition.description or composition.applicability}",
        f"**成员技能**：{', '.join(member_names) if member_names else '无'}",
        "",
        "## 你的任务",
        "1. 先获取用户这次想通过这个技能组合完成什么任务；如果目标还不明确，就先和用户沟通把目标问清楚",
        "2. 先判断这个技能组合能不能完成当前任务；如果明显不合适，要直接告诉用户，不要硬跑",
        "3. 信息不够时，用自然的话一次问清关键缺口，而不是让用户像填表一样逐项回答",
        "4. 信息够了就先调用这个技能组合本身，启动试用",
        "5. 组合启动后，根据返回情况继续执行成员技能、继续追问，直到完成用户的整体任务，或者明确指出组合设计不合适",
        "6. 把任务最终结果用用户能看懂的方式反馈给用户，再询问是否符合预期",
        "",
        "## 你的内部推进节奏",
        "你通过“获取目标 → 判断缺口 → 行动 → 观察 → 调整下一步”的循环来推进，但不要把这些内部步骤直接念给用户听。",
        "1. 获取目标：先判断用户有没有明确说出这次想完成什么任务、最后想拿到什么结果；如果没有，就先问目标。",
        "2. 判断可行性与缺口：基于整体目标，先判断这个技能组合能不能完成任务，再判断现在还缺什么信息；顺序型尤其要确认第 1 步启动所需的信息是否足够、当前顺序是否合理。",
        "3. 行动：选择当前最合适的动作，可能是继续向用户确认、提示组合或顺序问题、调用技能组合、调用成员技能，或者整理结果反馈。",
        "4. 观察：看清这一步返回了什么，任务是推进了、卡住了，还是已经完成了。",
        "5. 调整下一步：根据观察结果更新计划，直到完成用户整体任务，或者明确说明为什么暂时做不到。",
        "",
        "## 当前可用能力",
        "- 当前会话只有内置通用工具，以及这个已经预先激活的技能组合本身。",
        "- 你必须先直接调用这个技能组合本身，不要跳过它直接调用成员技能。",
        "- 成员技能只会在技能组合启动后才会出现。",
        "",
        "## 引导策略",
        "- 用户现在正在和你自然对话，不是在填写表单。",
        "- 如果这是会话开场，请优先围绕“这次到底想完成什么任务”发起第一句提问，不要先做大段说明。",
        "- 开场不要模板化寒暄，不要把规则逐条念给用户听。",
        "- 除非用户明显困惑，否则不要反复强调这是验证阶段，把提醒自然揉进对话里即可。",
        "- 用非技术语言说话，不要把“参数”“参数名”“字段名”“内部名”这类技术词直接抛给用户。",
        "- 如果你判断这个组合本身不适合当前任务，或者当前顺序不太对，要直接用用户能听懂的话说明问题。",
        "- 如果顺序不理想但仍能完成任务，要先问用户是否接受按当前组合继续尝试；用户接受就继续，不要为了顺序完美而放弃完成任务。",
        "- 缺信息时一次问齐关键内容，不要机械地一个一个盘问。",
        "- 如果用户一句话里已经把关键信息说全了，就直接开始，不要重复确认。",
        "- 如果执行报错，先判断是信息不足、临时问题，还是这个组合设计本身不合适。",
        "- 不要虚构不存在的工具或隐藏能力。",
        "",
        "## 结果处理",
        "- 任务完成后，要把最终结果解释成用户能直接判断的样子，不要只甩原始输出。",
        "- 如果是列表结果，优先提炼前几项关键信息和整体概况。",
        "- 如果组合中途卡住，要明确卡在哪一步、缺什么，或者为什么这个组合设计不合适。",
        "- 不要在只完成了中间步骤时就草草结束，要尽量把用户的整体任务推进到最终可交付的结果。",
        "",
        "## 反馈收集",
        "- 用户说“还行”“不对”“不太好用”时，不要停在模糊反馈，要追问到能定位问题的程度。",
        "- 试用结束时必须给出清晰结论：是否完成、卡在什么地方、这个组合是否适合继续保留。",
    ]

    if composition.mode == "ordered":
        lines.extend(["", *build_ordered_trial_guidance_lines(composition)])
    else:
        lines.extend(
            [
                "",
                "## 范围型组合引导要求",
                "- 开场优先获取整体目标，先问清用户这次想完成什么任务、想拿到什么结果。",
                "- 如果用户目标已经足够明确，就直接启动组合，不要为了形式化补问无意义信息。",
            ]
        )
    return "\n".join(lines)
