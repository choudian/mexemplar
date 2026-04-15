"""Skill composition support package."""

from .composition_llm_helper import CompositionLLMHelper
from .service import SkillCompositionService
from .composition_normalizer import (
    build_composition_orm,
    build_member_orms,
    member_to_payload,
    normalize_members,
    to_composition_model,
    to_tool_model,
)
from .trial_prompt_builder import (
    build_ordered_trial_guidance_lines,
    build_trial_bootstrap_input,
    build_trial_system_prompt,
    build_trial_user_input,
    format_trial_parameter_lines,
    get_first_member_tool,
    normalize_trial_dialog_input,
)
from .trial_runner import TrialRunner
from .trial_snapshot_codec import (
    build_trial_session_snapshot_payload,
    coerce_snapshot_int,
    deserialize_trial_session_tool,
    normalize_generated_text,
    normalize_trial_session_member_snapshot,
    parse_trial_session_snapshot,
)
from .types import (
    SkillCompositionError,
    SkillCompositionTrialResult,
    SkillCompositionTrialSessionStart,
)

__all__ = [
    "CompositionLLMHelper",
    "SkillCompositionService",
    "TrialRunner",
    "SkillCompositionError",
    "SkillCompositionTrialResult",
    "SkillCompositionTrialSessionStart",
    "build_composition_orm",
    "build_member_orms",
    "member_to_payload",
    "normalize_members",
    "to_composition_model",
    "to_tool_model",
    "build_ordered_trial_guidance_lines",
    "build_trial_bootstrap_input",
    "build_trial_system_prompt",
    "build_trial_user_input",
    "format_trial_parameter_lines",
    "get_first_member_tool",
    "normalize_trial_dialog_input",
    "build_trial_session_snapshot_payload",
    "coerce_snapshot_int",
    "deserialize_trial_session_tool",
    "normalize_generated_text",
    "normalize_trial_session_member_snapshot",
    "parse_trial_session_snapshot",
]
