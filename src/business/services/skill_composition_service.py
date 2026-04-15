"""
Backward-compatible shim.

The SkillCompositionService class now lives in
src.business.services.skill_composition.service.
"""

from .skill_composition.service import SkillCompositionService  # noqa: F401
from .skill_composition.types import (  # noqa: F401
    SkillCompositionError,
    SkillCompositionTrialResult,
    SkillCompositionTrialSessionStart,
)
