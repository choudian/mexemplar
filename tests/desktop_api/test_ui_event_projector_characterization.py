"""Characterization tests for project_internal_event.

锁定每个内部 event_name → 公开 UiEventDraft 的当前投影行为，作为
projector 注册表化重构（#2）的安全网。重构后这些断言必须保持 green。
"""

from __future__ import annotations

from src.desktop_api.ui_event_projector import project_internal_event

# 统一用 session_id="s1" → scope={"sessionId":"s1"}, causation_id="s1"
_S = {"sessionId": "s1"}
_C = "s1"


# ===== recording 域 =====


def test_recording_started_fans_out_progress_and_stage():
    drafts = project_internal_event(
        "recording_started", {"session_id": "s1", "recording_mode": "browser"}
    )
    assert len(drafts) == 2
    assert drafts[0].event_type == "recording.progress"
    assert drafts[0].payload == {
        "status": "recording",
        "message": "Recording started.",
        "recordingMode": "browser",
    }
    assert drafts[0].scope == _S and drafts[0].causation_id == _C
    assert drafts[1].event_type == "teaching.stage_changed"
    assert drafts[1].payload == {"stage": "recording"}


def test_recording_stopped_fans_out_progress_and_intent_stage():
    drafts = project_internal_event(
        "recording_stopped", {"session_id": "s1", "recording_mode": "desktop"}
    )
    assert len(drafts) == 2
    assert drafts[0].payload["status"] == "stopped"
    assert drafts[1].payload == {"stage": "intent_confirmation"}


def test_recording_completed_single_envelope():
    drafts = project_internal_event("recording_completed", {"session_id": "s1"})
    assert len(drafts) == 1
    assert drafts[0].event_type == "recording.progress"
    assert drafts[0].payload == {"status": "completed", "message": "Recording completed."}


def test_desktop_action_count_changed():
    drafts = project_internal_event(
        "desktop_action_count_changed", {"session_id": "s1", "action_count": 7}
    )
    assert len(drafts) == 1
    assert drafts[0].payload == {"status": "recording", "actionCount": 7}


def test_desktop_recording_degraded_projects_degraded_status():
    drafts = project_internal_event(
        "desktop_recording_degraded",
        {"session_id": "s1", "message": "掉帧", "subsystem": "capture"},
    )
    assert len(drafts) == 1
    assert drafts[0].payload["status"] == "degraded"
    assert drafts[0].payload["degraded"] is True
    assert drafts[0].payload["subsystem"] == "capture"
    assert drafts[0].payload["message"] == "掉帧"


def test_desktop_recorder_start_failed_projects_failed_status():
    drafts = project_internal_event(
        "desktop_recorder_start_failed", {"session_id": "s1", "error": "boom"}
    )
    assert drafts[0].payload["status"] == "failed"
    assert drafts[0].payload["degraded"] is False
    assert drafts[0].payload["error"] == "boom"


# ===== agent_needs_user_input（5 路 guard）=====


def test_agent_needs_user_input_pm_routes_to_teaching():
    drafts = project_internal_event(
        "agent_needs_user_input",
        {"session_id": "s1", "agent_type": "pm", "question": "Q?"},
    )
    assert drafts[0].event_type == "teaching.progress"
    assert drafts[0].payload == {
        "status": "waiting_for_user",
        "headline": "Q?",
        "question": "Q?",
    }


def test_agent_needs_user_input_trial_routes_to_trial():
    drafts = project_internal_event(
        "agent_needs_user_input",
        {"session_id": "s1", "agent_type": "trial", "message": "M"},
    )
    assert drafts[0].event_type == "trial.progress"
    assert drafts[0].payload == {"status": "waiting_for_user", "headline": "M"}


def test_agent_needs_user_input_session_routes_to_assistant():
    drafts = project_internal_event("agent_needs_user_input", {"session_id": "s1", "question": "Q"})
    assert drafts[0].event_type == "assistant.progress"
    assert drafts[0].payload == {
        "status": "waiting_for_user",
        "headline": "Q",
        "question": "Q",
    }


def test_agent_needs_user_input_no_context_returns_empty():
    drafts = project_internal_event("agent_needs_user_input", {"question": "Q"})
    assert drafts == []


# ===== agent_error（4 路 guard）=====


def test_agent_error_trial_routes_to_trial_failed():
    drafts = project_internal_event(
        "agent_error", {"session_id": "s1", "agent_type": "trial", "message": "x", "type": "T"}
    )
    assert drafts[0].event_type == "trial.progress"
    assert drafts[0].payload == {"status": "failed", "error": "x", "type": "T"}


def test_agent_error_with_session_routes_to_assistant_error():
    drafts = project_internal_event(
        "agent_error", {"session_id": "s1", "message": "boom", "type": "T"}
    )
    assert drafts[0].event_type == "assistant.error"
    assert drafts[0].payload == {"message": "boom", "type": "T"}


def test_agent_error_no_context_routes_to_teaching_failed():
    drafts = project_internal_event("agent_error", {"message": "x"})
    assert drafts[0].event_type == "teaching.progress"
    assert drafts[0].payload == {"status": "failed", "error": "x"}


# ===== teaching 域 =====


def test_requirement_confirmed_fans_out():
    drafts = project_internal_event("requirement_confirmed", {"session_id": "s1"})
    assert len(drafts) == 2
    assert drafts[0].event_type == "teaching.stage_changed"
    assert drafts[0].payload == {"stage": "learning", "message": "Requirements confirmed."}
    assert drafts[1].event_type == "teaching.progress"
    assert drafts[1].payload == {"status": "running", "headline": "Skill learning started"}


def test_code_completed_fans_out():
    drafts = project_internal_event("code_completed", {"session_id": "s1"})
    assert len(drafts) == 2
    assert drafts[0].payload == {
        "stage": "trial_validation",
        "message": "Skill learning completed.",
    }
    assert drafts[1].payload == {"status": "succeeded", "headline": "Skill learning completed"}


def test_review_passed_shares_code_completed_projection():
    drafts = project_internal_event("review_passed", {"session_id": "s1"})
    assert drafts[0].payload["stage"] == "trial_validation"
    assert drafts[1].payload["status"] == "succeeded"


def test_review_failed_fans_out_with_failure_stage():
    drafts = project_internal_event(
        "review_failed", {"session_id": "s1", "failed_stage": "code", "error": "E"}
    )
    assert len(drafts) == 2
    assert drafts[0].payload == {"stage": "failed", "failureStage": "code"}
    assert drafts[1].payload == {
        "status": "failed",
        "failureStage": "code",
        "error": "E",
    }


def test_teaching_failure_updated_shares_review_failed_projection():
    drafts = project_internal_event(
        "teaching_failure_updated",
        {"session_id": "s1", "failed_stage": "trial", "message": "M"},
    )
    assert drafts[0].payload["stage"] == "failed"
    assert drafts[1].payload["error"] == "M"


def test_teaching_failure_resolved_single():
    drafts = project_internal_event("teaching_failure_resolved", {"session_id": "s1"})
    assert len(drafts) == 1
    assert drafts[0].payload == {"status": "succeeded", "headline": "Teaching failure resolved"}


def test_teaching_failure_retrying_single():
    drafts = project_internal_event("teaching_failure_retrying", {"session_id": "s1"})
    assert drafts[0].payload == {"status": "running", "headline": "Skill teaching retry started"}


# ===== trial 域 =====


def test_trial_requested_single():
    drafts = project_internal_event("trial_requested", {"session_id": "s1"})
    assert drafts[0].event_type == "trial.progress"
    assert drafts[0].payload == {"status": "running", "headline": "Skill trial requested"}


def test_trial_success_without_published_single_envelope():
    drafts = project_internal_event("trial_success", {"session_id": "s1", "success_count": 3})
    assert len(drafts) == 1
    assert drafts[0].payload == {"status": "succeeded", "published": False, "successCount": 3}


def test_trial_success_with_published_appends_stage():
    drafts = project_internal_event(
        "trial_success", {"session_id": "s1", "published": True, "trial_success_count": 1}
    )
    assert len(drafts) == 2
    assert drafts[0].payload["published"] is True
    assert drafts[1].event_type == "teaching.stage_changed"
    assert drafts[1].payload == {"stage": "published", "published": True}


def test_trial_failed_single():
    drafts = project_internal_event("trial_failed", {"session_id": "s1"})
    assert drafts[0].event_type == "teaching.stage_changed"
    assert drafts[0].payload == {"stage": "failed", "failureStage": "trial"}


def test_desktop_trial_finished_single():
    drafts = project_internal_event(
        "desktop_trial_finished", {"session_id": "s1", "trial_id": "t1", "result": "ok"}
    )
    assert drafts[0].event_type == "trial.progress"
    assert drafts[0].payload == {"status": "succeeded", "trialId": "t1", "result": "ok"}


# ===== tools 域 =====


def test_tool_saved_sets_status_saved():
    drafts = project_internal_event("tool_saved", {"session_id": "s1", "tool_id": "tl1"})
    assert drafts[0].event_type == "tools.changed"
    assert drafts[0].payload == {
        "reason": "catalog_invalidated",
        "toolId": "tl1",
        "status": "saved",
    }


def test_tool_published_sets_status_published():
    drafts = project_internal_event("tool_published", {"session_id": "s1", "tool_id": "tl1"})
    assert drafts[0].payload["status"] == "published"


def test_tools_changed_no_status():
    drafts = project_internal_event("tools_changed", {"session_id": "s1", "tool_id": "tl1"})
    assert "status" not in drafts[0].payload
    assert drafts[0].payload["reason"] == "catalog_invalidated"


# ===== skill 域（自定义 scope）=====


def test_brain_skill_changed_uses_skill_scope():
    drafts = project_internal_event(
        "brain_skill_changed",
        {"session_id": "s1", "skill_id": "sk1", "operation": "edit", "new_skill_id": "sk2"},
    )
    assert drafts[0].event_type == "skill.changed"
    assert drafts[0].payload == {
        "reason": "edit",
        "skillId": "sk1",
        "chainRootId": "sk1",
        "newSkillId": "sk2",
        "callerType": None,
        "callerId": None,
    }
    assert drafts[0].scope == {"skillId": "sk1"}


def test_brain_skill_bootstrap_fallback_used():
    drafts = project_internal_event(
        "brain_skill_bootstrap_fallback_used",
        {"session_id": "s1", "skill_id": "sk1", "reason": "missing", "seed_file_path": "p"},
    )
    assert drafts[0].payload["reason"] == "bootstrap_fallback_used"
    assert drafts[0].payload["callerType"] == "system"
    assert drafts[0].payload["bootstrapFallbackInfo"] == {"reason": "missing", "seedFilePath": "p"}
    assert drafts[0].scope == {"skillId": "sk1"}


def test_brain_skill_equipment_changed_filters_scope():
    drafts = project_internal_event(
        "brain_skill_equipment_changed",
        {
            "session_id": "s1",
            "skill_id": "sk1",
            "entity_id": "e1",
            "change_type": "unequip",
            "entity_type": "specialist",
        },
    )
    assert drafts[0].event_type == "skill.equipment.changed"
    assert drafts[0].payload["entityId"] == "e1"
    assert drafts[0].scope == {"skillId": "sk1", "entityId": "e1"}


def test_brain_skill_equipment_changed_without_entity_excludes_from_scope():
    drafts = project_internal_event(
        "brain_skill_equipment_changed",
        {"session_id": "s1", "skill_id": "sk1", "change_type": "equip"},
    )
    assert drafts[0].scope == {"skillId": "sk1"}


def test_brain_skill_supersede_completed_suppressed():
    drafts = project_internal_event(
        "brain_skill_supersede_completed", {"session_id": "s1", "skill_id": "sk1"}
    )
    assert drafts == []


# ===== composition / settings / brain 域 =====


def test_composition_review_needed():
    drafts = project_internal_event(
        "composition_review_needed", {"session_id": "s1", "composition_id": "c1"}
    )
    assert drafts[0].event_type == "compositions.changed"
    assert drafts[0].payload == {"reason": "catalog_invalidated", "compositionId": "c1"}


def test_settings_changed():
    drafts = project_internal_event("settings_changed", {"session_id": "s1", "keys": ["a", "b"]})
    assert drafts[0].event_type == "settings.changed"
    assert drafts[0].payload == {"reason": "settings_invalidated", "keys": ["a", "b"]}


def test_brain_zone_changed():
    drafts = project_internal_event(
        "brain_zone_changed",
        {"session_id": "s1", "zone": "archive", "entry_id": "e1", "change_type": "add"},
    )
    assert drafts[0].event_type == "brain_zone_changed"
    assert drafts[0].payload == {"zone": "archive", "entryId": "e1", "changeType": "add"}


def test_brain_specialist_recruited_hardcodes_management_url():
    drafts = project_internal_event(
        "brain_specialist_recruited",
        {"session_id": "s1", "specialist_id": "sp1", "name": "专员", "reason": "auto"},
    )
    assert drafts[0].event_type == "brain_specialist_recruited"
    assert drafts[0].payload == {
        "specialistId": "sp1",
        "name": "专员",
        "reason": "auto",
        "managementUrl": "/brain/specialists",
    }


def test_brain_specialist_changed():
    drafts = project_internal_event(
        "brain_specialist_changed",
        {"session_id": "s1", "specialist_id": "sp1", "change_type": "rename"},
    )
    assert drafts[0].event_type == "brain_specialist_changed"
    assert drafts[0].payload == {"specialistId": "sp1", "changeType": "rename"}


def test_brain_context_ready():
    drafts = project_internal_event("brain_context_ready", {"session_id": "s1"})
    assert drafts[0].event_type == "brain_context_ready"
    assert drafts[0].payload == {"sessionId": "s1"}


# ===== subagent finished（observability 已覆盖 started/paused）=====


def test_assistant_subagent_finished_projects_lifecycle():
    drafts = project_internal_event(
        "assistant_subagent_finished",
        {"session_id": "s1", "subagent_id": "c1", "status": "finished"},
    )
    assert drafts[0].event_type == "assistant.subagent"
    assert drafts[0].payload["subagentId"] == "c1"
    assert drafts[0].payload["status"] == "finished"


# ===== improvement proposal（026）=====


def test_improvement_proposal_changed_projects_public_event():
    drafts = project_internal_event(
        "improvement_proposal_changed",
        {
            "session_id": "s1",
            "proposal_id": "prop_1",
            "source_review_id": "rev_1",
            "status": "approved",
            "severity": "med",
            "change_type": "approved",
        },
    )
    assert len(drafts) == 1
    assert drafts[0].event_type == "improvement_proposal.changed"
    assert drafts[0].payload == {
        "proposalId": "prop_1",
        "sourceReviewId": "rev_1",
        "status": "approved",
        "severity": "med",
        "changeType": "approved",
    }
    assert drafts[0].scope == _S and drafts[0].causation_id == _C


# ===== 未注册事件静默丢弃（重构后改为告警）=====


def test_unregistered_event_silently_dropped():
    # 重构后此行为改为 warning；当前锁定 return []
    assert project_internal_event("totally_unknown_event", {"session_id": "s1"}) == []
