# Blueprint: Agent Built-in Tools Upgrade

**Branch**: `015-agent-builtin-tools-upgrade` | **Date**: 2026-06-08
**Mode**: `doc-only`
**Total Tasks**: 86 | **Files**: 17 new, 14 modified, 0 deleted

## Key Decisions

- Keep `src/business/agents/tools/builtin_general_tools.py` as the stable public registry facade, while moving upgraded built-in implementations into focused modules. This preserves existing import surfaces and gives file, search, command, permission, and output governance their own testable boundaries. → T003, T017, T027, T038, T050, T062, T076, T083
- Treat the common built-in result envelope as the only Agent-visible contract for upgraded foundational tools. AgentLoop converts built-in successes, standardized errors, skipped calls, unknown tools, pre-hook rejections, and governance fallbacks through one persistence boundary so every tool call still receives one paired result. → T006, T009, T010, T015, T016, T074
- Use runtime workspace resolution plus fixed external-path policy. Workspace reads and mutations are normal, outside-workspace reads require high-risk confirmation, and outside-workspace mutations, patch operations, and execution are denied before side effects. → T008, T011, T026, T037, T049, T061
- File mutation requires current observation evidence. Existing-file replace, edit, delete, and patch update/delete operations require a matching baseline, while new file creation can omit a baseline only when the path does not exist. → T023, T030, T034, T035, T047, T048
- Process records are in-memory and sidecar-session scoped; durable recovery belongs only to raw-output references, not to live process handles. → T004, T054, T057, T058, T059, T060
- Persistent raw-output metadata belongs to the SQLite Repository layer, and blob paths remain internal. Agent-visible output receives opaque references, bounded loading, redaction, retention, and log-safe diagnostics. → T066, T069, T070, T071, T072, T073, T075, T077
- Runtime caps are non-UI engineering knobs read through unified configuration and mirrored into defaults, example config, and living docs. → T007, T012, T013, T014, T079, T080, T081, T082

## Implementation Order

```text
Phase 1: T001, T002, T003, T004, T005
Phase 2: T006, T007, T008, T009, T010, T011, T012, T013, T014, T015, T016, T017, T018
Phase 3: T019, T020, T021, T022, T023, T024, T025, T026, T027, T028, T029
Phase 4: T030, T031, T032, T033, T034, T035, T036, T037, T038, T039, T040
Phase 5: T041, T042, T043, T044, T045, T046, T047, T048, T049, T050, T051, T052
Phase 6: T053, T054, T055, T056, T057, T058, T059, T060, T061, T062, T063, T064
Phase 7: T065, T066, T067, T068, T069, T070, T071, T072, T073, T074, T075, T076, T077, T078
Phase 8: T079, T080, T081, T082, T083, T084, T085, T086
```

---

## Phase 1: Setup

### T001: Create shared built-in contract module skeleton

**File**: `src/business/agents/tools/builtin_contracts.py` (new)

**Requirements**: FR-001, FR-022, FR-024

**Dependencies**: none

Apply the complete file content from **Appendix A1**. This first file is immediately useful because the final content includes the shared envelope, stable outcomes, stable errors, references, verification metadata, and serialization helpers.

**Verification**: `python -m py_compile src/business/agents/tools/builtin_contracts.py`

---

### T002: Create workspace permission module skeleton

**File**: `src/business/agents/tools/builtin_permissions.py` (new)

**Requirements**: FR-003, FR-016, FR-017

**Dependencies**: none

Apply the complete file content from **Appendix A2**.

**Verification**: `python -m py_compile src/business/agents/tools/builtin_permissions.py`

---

### T003: Create focused built-in tool module skeletons

**File**: `src/business/agents/tools/file_tools.py` (new)
**File**: `src/business/agents/tools/search_tools.py` (new)
**File**: `src/business/agents/tools/command_tools.py` (new)
**File**: `src/business/agents/tools/output_governance.py` (new)

**Requirements**: FR-004, FR-008, FR-013, FR-014, FR-015, FR-018, FR-019, FR-021

**Dependencies**: T001, T002

Apply the complete file contents from **Appendix A3**, **Appendix A4**, **Appendix A7**, and **Appendix A8**.

**Verification**: `python -m py_compile src/business/agents/tools/file_tools.py src/business/agents/tools/search_tools.py src/business/agents/tools/command_tools.py src/business/agents/tools/output_governance.py`

---

### T004: Create execution boundary module skeletons

**File**: `src/execution/command_runner.py` (new)
**File**: `src/execution/process_manager.py` (new)

**Requirements**: FR-018, FR-019, FR-020

**Dependencies**: none

Apply the complete file contents from **Appendix A5** and **Appendix A6**.

**Verification**: `python -m py_compile src/execution/command_runner.py src/execution/process_manager.py`

---

### T005: Create focused test files

**File**: `tests/business/agents/test_builtin_file_tools.py` (new)
**File**: `tests/business/agents/test_builtin_search_tools.py` (new)
**File**: `tests/business/agents/test_builtin_command_tools.py` (new)
**File**: `tests/business/agents/test_builtin_output_governance.py` (new)
**File**: `tests/data/test_tool_output_repository.py` (new)
**File**: `tests/integration/test_agent_builtin_tool_contracts.py` (new)
**File**: `tests/integration/test_agent_builtin_process_lifecycle.py` (new)

**Requirements**: FR-025

**Dependencies**: none

Create the test files using the complete contents from **Appendix B1** through **Appendix B7**. The files start with executable assertions rather than empty placeholders.

**Verification**: `uv run pytest tests/business/agents/test_builtin_file_tools.py tests/business/agents/test_builtin_search_tools.py tests/business/agents/test_builtin_command_tools.py tests/business/agents/test_builtin_output_governance.py tests/data/test_tool_output_repository.py tests/integration/test_agent_builtin_tool_contracts.py tests/integration/test_agent_builtin_process_lifecycle.py`

---

## Phase 2: Foundational

### T006: Add JSON-schema and stable error-code tests

**File**: `tests/integration/test_agent_builtin_tool_contracts.py` (new)

**Requirements**: FR-001, FR-024, FR-025

**Dependencies**: T001

Use **Appendix B6**. It validates the envelope shape through local schema checks and asserts stable error codes for upgraded tool failures.

**Verification**: `uv run pytest tests/integration/test_agent_builtin_tool_contracts.py -q`

---

### T007: Add unified configuration getter/default validation tests

**File**: `tests/data/test_tool_output_repository.py` (new)

**Requirements**: FR-026

**Dependencies**: T012, T013, T014

Use **Appendix B5**. It verifies config defaults and bounds through `UnifiedConfigManager` typed getters.

**Verification**: `uv run pytest tests/data/test_tool_output_repository.py -q`

---

### T008: Add workspace path classification and confirmation-summary safety tests

**File**: `tests/guardrails/test_agent_builtin_tool_boundaries.py` (new)

**Requirements**: FR-003, FR-016, FR-017, CC-004, CC-007

**Dependencies**: T011

Use **Appendix B8**.

**Verification**: `uv run pytest tests/guardrails/test_agent_builtin_tool_boundaries.py -q`

---

### T009: Add AgentLoop exactly-one-result tests

**File**: `tests/integration/test_agent_builtin_tool_contracts.py` (new)

**Requirements**: FR-022, CC-002

**Dependencies**: T015, T016

Use **Appendix B6**.

**Verification**: `uv run pytest tests/integration/test_agent_builtin_tool_contracts.py -q`

---

### T010: Implement common built-in contracts

**File**: `src/business/agents/tools/builtin_contracts.py` (new)

**Requirements**: FR-001, FR-022, FR-024

**Dependencies**: T001

Apply **Appendix A1**.

**Verification**: `python -m py_compile src/business/agents/tools/builtin_contracts.py`

---

### T011: Implement workspace resolution, classification, risk, and summaries

**File**: `src/business/agents/tools/builtin_permissions.py` (new)

**Requirements**: FR-003, FR-016, FR-017, CC-004, CC-007, CC-009

**Dependencies**: T002, T010

Apply **Appendix A2**.

**Verification**: `uv run pytest tests/guardrails/test_agent_builtin_tool_boundaries.py -q`

---

### T012: Add agent tool config dataclasses

**File**: `src/data/config_models.py` (modify)

**Requirements**: FR-026, CC-006

**Dependencies**: none

**Before** (line 281):

```python
@dataclass
class BrainConfig:
    """大脑配置"""

    segment: BrainSegmentConfig = field(default_factory=BrainSegmentConfig)
    worker: BrainWorkerConfig = field(default_factory=BrainWorkerConfig)
    injection: BrainInjectionConfig = field(default_factory=BrainInjectionConfig)
    decay: BrainDecayConfig = field(default_factory=BrainDecayConfig)
    recruitment: BrainRecruitmentConfig = field(default_factory=BrainRecruitmentConfig)
    skill: BrainSkillConfig = field(default_factory=BrainSkillConfig)
```

**After**:

```python
@dataclass
class BrainConfig:
    """大脑配置"""

    segment: BrainSegmentConfig = field(default_factory=BrainSegmentConfig)
    worker: BrainWorkerConfig = field(default_factory=BrainWorkerConfig)
    injection: BrainInjectionConfig = field(default_factory=BrainInjectionConfig)
    decay: BrainDecayConfig = field(default_factory=BrainDecayConfig)
    recruitment: BrainRecruitmentConfig = field(default_factory=BrainRecruitmentConfig)
    skill: BrainSkillConfig = field(default_factory=BrainSkillConfig)


@dataclass
class AgentToolsFileConfig:
    """Agent built-in file tool runtime caps."""

    default_max_lines: int = 200
    max_window_chars: int = 50000
    max_decode_bytes: int = 1048576


@dataclass
class AgentToolsOutputConfig:
    """Agent built-in visible output and raw-reference caps."""

    visible_char_cap: int = 12000
    raw_reference_threshold_chars: int = 20000
    max_artifact_bytes: int = 10485760
    retention_days: int = 14


@dataclass
class AgentToolsSearchConfig:
    """Agent built-in search caps."""

    default_page_size: int = 100
    max_files_scanned: int = 50000
    max_bytes_per_file: int = 1048576
    max_elapsed_ms: int = 30000


@dataclass
class AgentToolsProcessConfig:
    """Agent built-in command and process caps."""

    default_timeout_ms: int = 30000
    max_timeout_ms: int = 600000
    log_tail_chars: int = 4000
    max_background_processes: int = 16


@dataclass
class AgentToolsConfig:
    """Agent built-in foundational tool configuration."""

    file: AgentToolsFileConfig = field(default_factory=AgentToolsFileConfig)
    output: AgentToolsOutputConfig = field(default_factory=AgentToolsOutputConfig)
    search: AgentToolsSearchConfig = field(default_factory=AgentToolsSearchConfig)
    process: AgentToolsProcessConfig = field(default_factory=AgentToolsProcessConfig)
```

**Before** (line 293):

```python
@dataclass
class AppConfig:
    """应用配置"""

    app_name: str = "Mexemplar"
    version: str = "0.1.0"
    debug: bool = False
    ai: AIConfig = field(default_factory=AIConfig)
    recording: RecordingConfig = field(default_factory=RecordingConfig)
    ui: UIConfig = field(default_factory=UIConfig)
    brain: BrainConfig = field(default_factory=BrainConfig)
```

**After**:

```python
@dataclass
class AppConfig:
    """应用配置"""

    app_name: str = "Mexemplar"
    version: str = "0.1.0"
    debug: bool = False
    ai: AIConfig = field(default_factory=AIConfig)
    recording: RecordingConfig = field(default_factory=RecordingConfig)
    ui: UIConfig = field(default_factory=UIConfig)
    brain: BrainConfig = field(default_factory=BrainConfig)
    agent_tools: AgentToolsConfig = field(default_factory=AgentToolsConfig)
```

**Before** (line 358):

```python
            config.brain = BrainConfig(**brain_data)

        if "app_name" in data:
            config.app_name = data["app_name"]
```

**After**:

```python
            config.brain = BrainConfig(**brain_data)

        if "agent_tools" in data:
            agent_tools_data = _filter_dataclass_fields(data["agent_tools"], AgentToolsConfig)
            for key, sub_cls in (
                ("file", AgentToolsFileConfig),
                ("output", AgentToolsOutputConfig),
                ("search", AgentToolsSearchConfig),
                ("process", AgentToolsProcessConfig),
            ):
                val = agent_tools_data.get(key)
                if isinstance(val, dict):
                    agent_tools_data[key] = sub_cls(**_filter_dataclass_fields(val, sub_cls))
            config.agent_tools = AgentToolsConfig(**agent_tools_data)

        if "app_name" in data:
            config.app_name = data["app_name"]
```

**Verification**: `python -m py_compile src/data/config_models.py`

---

### T013: Add typed getters and validation

**File**: `src/data/unified_config.py` (modify)

**Requirements**: FR-026

**Dependencies**: T012

**Before** (line 496):

```python
    def get_brain_skill_seed_file_path(self) -> str:
        """内置'如何创建方法论' seed 文件路径。"""
        value = self.get(
            "brain.skill.seed_file_path",
            default="src/business/brain/seed/how_to_create_skill_methodology.md",
        )
        text = str(value or "").strip()
        return text or "src/business/brain/seed/how_to_create_skill_methodology.md"
```

**After**:

```python
    def get_brain_skill_seed_file_path(self) -> str:
        """内置'如何创建方法论' seed 文件路径。"""
        value = self.get(
            "brain.skill.seed_file_path",
            default="src/business/brain/seed/how_to_create_skill_methodology.md",
        )
        text = str(value or "").strip()
        return text or "src/business/brain/seed/how_to_create_skill_methodology.md"

    def _get_bounded_positive_int(
        self,
        key: str,
        default: int,
        *,
        minimum: int = 1,
        maximum: int | None = None,
    ) -> int:
        raw = self.get(key, default=default)
        try:
            value = int(raw)
        except (TypeError, ValueError):
            logger.warning("[配置] %s 非法，回退到 %d", key, default)
            return default
        if value < minimum:
            logger.warning("[配置] %s 小于下限，回退到 %d", key, default)
            return default
        if maximum is not None and value > maximum:
            logger.warning("[配置] %s 大于上限，回退到 %d", key, default)
            return default
        return value

    def get_agent_tools_file_default_max_lines(self) -> int:
        return self._get_bounded_positive_int(
            "agent_tools.file.default_max_lines", 200, maximum=1000
        )

    def get_agent_tools_file_max_window_chars(self) -> int:
        return self._get_bounded_positive_int(
            "agent_tools.file.max_window_chars", 50000, maximum=250000
        )

    def get_agent_tools_file_max_decode_bytes(self) -> int:
        return self._get_bounded_positive_int(
            "agent_tools.file.max_decode_bytes", 1048576, maximum=10485760
        )

    def get_agent_tools_output_visible_char_cap(self) -> int:
        return self._get_bounded_positive_int(
            "agent_tools.output.visible_char_cap", 12000, maximum=50000
        )

    def get_agent_tools_output_raw_reference_threshold_chars(self) -> int:
        visible = self.get_agent_tools_output_visible_char_cap()
        return self._get_bounded_positive_int(
            "agent_tools.output.raw_reference_threshold_chars",
            20000,
            minimum=visible,
        )

    def get_agent_tools_output_max_artifact_bytes(self) -> int:
        return self._get_bounded_positive_int(
            "agent_tools.output.max_artifact_bytes", 10485760, maximum=104857600
        )

    def get_agent_tools_output_retention_days(self) -> int:
        return self._get_bounded_positive_int(
            "agent_tools.output.retention_days", 14, maximum=90
        )

    def get_agent_tools_search_default_page_size(self) -> int:
        return self._get_bounded_positive_int(
            "agent_tools.search.default_page_size", 100, maximum=500
        )

    def get_agent_tools_search_max_files_scanned(self) -> int:
        return self._get_bounded_positive_int(
            "agent_tools.search.max_files_scanned", 50000
        )

    def get_agent_tools_search_max_bytes_per_file(self) -> int:
        return self._get_bounded_positive_int(
            "agent_tools.search.max_bytes_per_file", 1048576
        )

    def get_agent_tools_search_max_elapsed_ms(self) -> int:
        return self._get_bounded_positive_int(
            "agent_tools.search.max_elapsed_ms", 30000
        )

    def get_agent_tools_process_default_timeout_ms(self) -> int:
        return self._get_bounded_positive_int(
            "agent_tools.process.default_timeout_ms", 30000
        )

    def get_agent_tools_process_max_timeout_ms(self) -> int:
        default = self.get_agent_tools_process_default_timeout_ms()
        return self._get_bounded_positive_int(
            "agent_tools.process.max_timeout_ms", 600000, minimum=default
        )

    def get_agent_tools_process_log_tail_chars(self) -> int:
        output_cap = self.get_agent_tools_output_visible_char_cap()
        return self._get_bounded_positive_int(
            "agent_tools.process.log_tail_chars", 4000, maximum=output_cap
        )

    def get_agent_tools_process_max_background_processes(self) -> int:
        return self._get_bounded_positive_int(
            "agent_tools.process.max_background_processes", 16
        )
```

**Verification**: `python -m py_compile src/data/unified_config.py`

---

### T014: Update `agent_tools` defaults

**File**: `config.example.json` (modify)

**Requirements**: FR-026

**Dependencies**: T012, T013

**Before** (near the end of the root object):

```json
  "brain": {
    "segment": {
      "idle_threshold_seconds": 300,
      "max_distillation_retries": 3
    }
  }
}
```

**After**:

```json
  "brain": {
    "segment": {
      "idle_threshold_seconds": 300,
      "max_distillation_retries": 3
    }
  },
  "agent_tools": {
    "file": {
      "default_max_lines": 200,
      "max_window_chars": 50000,
      "max_decode_bytes": 1048576
    },
    "output": {
      "visible_char_cap": 12000,
      "raw_reference_threshold_chars": 20000,
      "max_artifact_bytes": 10485760,
      "retention_days": 14
    },
    "search": {
      "default_page_size": 100,
      "max_files_scanned": 50000,
      "max_bytes_per_file": 1048576,
      "max_elapsed_ms": 30000
    },
    "process": {
      "default_timeout_ms": 30000,
      "max_timeout_ms": 600000,
      "log_tail_chars": 4000,
      "max_background_processes": 16
    }
  }
}
```

Keep the existing full `brain` object intact; insert the new sibling key after it.

**Verification**: `python -m json.tool config.example.json > $null`

---

### T015: Implement AgentLoop governed tool-result persistence wrapper

**File**: `src/business/agents/agent_loop.py` (modify)

**Requirements**: FR-001, FR-021, FR-022, FR-024

**Dependencies**: T010, T073

**Before** (line 174):

```python
        self._msg_repo = MessageRepository()  # 复用 MessageRepository，避免每次重建
        self._session_repo = SessionRepository()
```

**After**:

```python
        self._msg_repo = MessageRepository()  # 复用 MessageRepository，避免每次重建
        self._session_repo = SessionRepository()
        self._governed_builtin_tool_names = {
            "read_file",
            "write_file",
            "edit_file",
            "apply_patch",
            "search_files",
            "search_content",
            "exec",
            "process_list",
            "process_poll",
            "process_logs",
            "process_wait",
            "process_stop",
            "process_send_input",
            "process_close",
            "load_tool_output",
        }
```

**Before** (line 696):

```python
    def _save_error(
        self, tc: ToolCallInfo, ctx: ContextManager, error_code: str, message: str, **extra
    ):
        """Save a standardized error result for a tool call."""
        ctx.save_tool_result(
            tool_call_id=tc.id,
            tool_name=tc.name,
            content=make_error_result(error_code, message, **extra),
        )
```

**After**:

```python
    def _persist_tool_result(
        self,
        ctx: ContextManager,
        *,
        tool_call_id: str,
        tool_name: str,
        content: str,
    ):
        """Persist one tool result through the built-in governance boundary."""
        final_content = content
        if tool_name in self._governed_builtin_tool_names:
            try:
                from src.business.agents.tools.output_governance import govern_tool_result

                final_content = govern_tool_result(
                    tool_name=tool_name,
                    tool_call_id=tool_call_id,
                    session_id=ctx.session_id,
                    content=content,
                    config=self._unified_config,
                )
            except Exception as exc:
                logger.warning(
                    "[Agent Loop] tool result governance fallback: tool=%s error_type=%s",
                    tool_name,
                    type(exc).__name__,
                    exc_info=True,
                )
                from src.business.agents.tools.builtin_contracts import fallback_envelope_json

                final_content = fallback_envelope_json(
                    tool=tool_name,
                    error_code="compaction_failed_fallback",
                    message="Tool result governance failed; returning safe fallback.",
                    payload={"visible": str(content)[:1000]},
                )
        return ctx.save_tool_result(
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            content=final_content,
        )

    def _save_error(
        self, tc: ToolCallInfo, ctx: ContextManager, error_code: str, message: str, **extra
    ):
        """Save a standardized error result for a tool call."""
        self._persist_tool_result(
            ctx,
            tool_call_id=tc.id,
            tool_name=tc.name,
            content=make_error_result(error_code, message, **extra),
        )
```

**Verification**: `uv run pytest tests/integration/test_agent_builtin_tool_contracts.py -q`

---

### T016: Route save call sites through the governed persistence wrapper

**File**: `src/business/agents/agent_loop.py` (modify)

**Requirements**: FR-022, CC-002

**Dependencies**: T015

Replace all direct `ctx.save_tool_result` calls in `_handle_tool_result`, `_execute_tool_batch`, and `_execute_solo_interrupt` with `self._persist_tool_result` using the same tool call id, tool name, and content arguments. Keep the existing `save_assistant_message` behavior untouched.

**Before** (line 673):

```python
            ctx.save_tool_result(tool_call_id=tc.id, tool_name=tc.name, content=result)
```

**After**:

```python
            self._persist_tool_result(
                ctx,
                tool_call_id=tc.id,
                tool_name=tc.name,
                content=result,
            )
```

Apply the same replacement shape at lines 555, 591, 700, and 717.

**Verification**: `Select-String -Path src/business/agents/agent_loop.py -Pattern 'ctx.save_tool_result'` should return no matches inside `AgentLoop` except the single call inside `_persist_tool_result`.

---

### T017: Update built-in general facade

**File**: `src/business/agents/tools/builtin_general_tools.py` (modify)

**Requirements**: FR-002, CC-008

**Dependencies**: T003, T010, T011

Keep `web_search`, `web_fetch`, `list_dir`, and the confirmation mechanism in this file. Replace the legacy `read_file`, `write_file`, `edit_file`, and `exec` schemas/handlers/pre-hooks with delegated imports and add the new built-ins.

**Before** (line 825):

```python
READ_FILE_SCHEMA = make_tool_schema(
    name="read_file",
    description="读取本地文件的内容。支持文本文件。",
```

**After**:

```python
from src.business.agents.tools.file_tools import (
    APPLY_PATCH_SCHEMA,
    EDIT_FILE_SCHEMA,
    READ_FILE_SCHEMA,
    WRITE_FILE_SCHEMA,
    apply_patch_handler,
    edit_file_handler,
    read_file_handler,
    write_file_handler,
)
from src.business.agents.tools.search_tools import (
    SEARCH_CONTENT_SCHEMA,
    SEARCH_FILES_SCHEMA,
    search_content_handler,
    search_files_handler,
)
from src.business.agents.tools.command_tools import (
    EXEC_SCHEMA,
    PROCESS_CLOSE_SCHEMA,
    PROCESS_LIST_SCHEMA,
    PROCESS_LOGS_SCHEMA,
    PROCESS_POLL_SCHEMA,
    PROCESS_SEND_INPUT_SCHEMA,
    PROCESS_STOP_SCHEMA,
    PROCESS_WAIT_SCHEMA,
    exec_handler,
    process_close_handler,
    process_list_handler,
    process_logs_handler,
    process_poll_handler,
    process_send_input_handler,
    process_stop_handler,
    process_wait_handler,
)
from src.business.agents.tools.output_governance import (
    LOAD_TOOL_OUTPUT_SCHEMA,
    load_tool_output_handler,
)
from src.business.agents.tools.builtin_permissions import (
    build_command_confirmation_summary,
    build_mutation_confirmation_summary,
    build_read_confirmation_summary,
    classify_command_request,
    classify_path_request,
)
```

The import block belongs with the existing imports near the top of the file. Then remove the legacy handler blocks from `READ_FILE_SCHEMA` through `exec_handler`.

**Verification**: `uv run pytest tests/business/agents/test_builtin_general_tools.py tests/guardrails/test_agent_builtin_tool_boundaries.py -q`

---

### T018: Add guard tests for layer and SQL boundaries

**File**: `tests/guardrails/test_agent_builtin_tool_boundaries.py` (new)

**Requirements**: CC-005, CC-006

**Dependencies**: T071, T079

Use **Appendix B8**.

**Verification**: `uv run pytest tests/guardrails/test_agent_builtin_tool_boundaries.py -q`

---

## Phase 3: User Story 1 - Safe File Inspection

### T019: Add read-file window, baseline, continuation, and repeat-read tests

**File**: `tests/business/agents/test_builtin_file_tools.py` (new)

**Requirements**: FR-004, FR-007, FR-025

**Dependencies**: T023, T024

Use **Appendix B1**.

**Verification**: `uv run pytest tests/business/agents/test_builtin_file_tools.py -q`

---

### T020: Add binary/media refusal and decode-failure tests

**File**: `tests/business/agents/test_builtin_file_tools.py` (new)

**Requirements**: FR-005, FR-025

**Dependencies**: T025

Use **Appendix B1**.

**Verification**: `uv run pytest tests/business/agents/test_builtin_file_tools.py -q`

---

### T021: Add outside-workspace read confirmation and fail-closed integration tests

**File**: `tests/integration/test_agent_builtin_tool_contracts.py` (new)

**Requirements**: FR-003, FR-017, FR-022

**Dependencies**: T026, T027

Use **Appendix B6**.

**Verification**: `uv run pytest tests/integration/test_agent_builtin_tool_contracts.py -q`

---

### T022: Add read redaction and binary leak guard tests

**File**: `tests/guardrails/test_agent_builtin_tool_boundaries.py` (new)

**Requirements**: FR-005, FR-006, FR-023

**Dependencies**: T025

Use **Appendix B8**.

**Verification**: `uv run pytest tests/guardrails/test_agent_builtin_tool_boundaries.py -q`

---

### T023: Implement baseline hashing and line-window metadata helpers

**File**: `src/business/agents/tools/file_tools.py` (new)

**Requirements**: FR-004, FR-007, FR-024

**Dependencies**: T010, T011

Apply **Appendix A3**.

**Verification**: `python -m py_compile src/business/agents/tools/file_tools.py`

---

### T024: Implement bounded `read_file` rendering

**File**: `src/business/agents/tools/file_tools.py` (new)

**Requirements**: FR-004, SC-001

**Dependencies**: T023

Apply **Appendix A3**.

**Verification**: `uv run pytest tests/business/agents/test_builtin_file_tools.py -q`

---

### T025: Implement binary/media refusal, decode failure, redaction, repeat-read metadata

**File**: `src/business/agents/tools/file_tools.py` (new)

**Requirements**: FR-005, FR-006, FR-007

**Dependencies**: T023, T024

Apply **Appendix A3**.

**Verification**: `uv run pytest tests/business/agents/test_builtin_file_tools.py tests/guardrails/test_agent_builtin_tool_boundaries.py -q`

---

### T026: Apply workspace read policy

**File**: `src/business/agents/tools/builtin_permissions.py` (new)

**Requirements**: FR-003, FR-016, FR-017

**Dependencies**: T011

Apply **Appendix A2** and wire the facade pre-hook from T017.

**Verification**: `uv run pytest tests/integration/test_agent_builtin_tool_contracts.py -q`

---

### T027: Replace legacy `read_file` schema, handler, and pre-hook wiring

**File**: `src/business/agents/tools/builtin_general_tools.py` (modify)

**Requirements**: FR-002, FR-004, FR-005, FR-006, FR-007

**Dependencies**: T017, T023, T024, T025, T026

After T017, register `read_file` with `READ_FILE_SCHEMA`, `read_file_handler`, and `read_file_pre_hook`; `has_side_effects=False`.

**Verification**: `uv run pytest tests/business/agents/test_builtin_file_tools.py tests/business/agents/test_builtin_general_tools.py -q`

---

### T028: Update Agent-facing `read_file` description

**File**: `src/business/agents/tools/builtin_general_tools.py` (modify)

**Requirements**: FR-004, FR-005, FR-006, FR-007, SC-010

**Dependencies**: T027

Use the description embedded in `READ_FILE_SCHEMA` from **Appendix A3**. It explicitly mentions bounded windows, baselines, redaction, unsupported binary/media behavior, and continuation metadata.

**Verification**: `uv run pytest tests/guardrails/test_agent_builtin_tool_boundaries.py -q`

---

### T029: Run US1 focused tests

**File**: `specs/015-agent-builtin-tools-upgrade/quickstart.md` (existing verification path)

**Requirements**: SC-001

**Dependencies**: T019 through T028

Run the US1 subset:

```powershell
uv run pytest tests/business/agents/test_builtin_file_tools.py tests/integration/test_agent_builtin_tool_contracts.py tests/guardrails/test_agent_builtin_tool_boundaries.py -q
```

**Verification**: All US1 tests pass.

---

## Phase 4: User Story 2 - Recoverable File Changes

### T030: Add write-file baseline and verification tests

**File**: `tests/business/agents/test_builtin_file_tools.py` (new)

**Requirements**: FR-008, FR-009, FR-025

**Dependencies**: T034

Use **Appendix B1**.

**Verification**: `uv run pytest tests/business/agents/test_builtin_file_tools.py -q`

---

### T031: Add edit-file replacement, style, and stale-baseline tests

**File**: `tests/business/agents/test_builtin_file_tools.py` (new)

**Requirements**: FR-009, FR-010, FR-011, FR-012

**Dependencies**: T035

Use **Appendix B1**.

**Verification**: `uv run pytest tests/business/agents/test_builtin_file_tools.py -q`

---

### T032: Add multi-tool AgentLoop stale mutation pairing tests

**File**: `tests/integration/test_agent_builtin_tool_contracts.py` (new)

**Requirements**: FR-022, CC-002

**Dependencies**: T034, T035, T038

Use **Appendix B6**.

**Verification**: `uv run pytest tests/integration/test_agent_builtin_tool_contracts.py -q`

---

### T033: Add confirmation-summary leak tests for write/edit

**File**: `tests/guardrails/test_agent_builtin_tool_boundaries.py` (new)

**Requirements**: CC-004, FR-023

**Dependencies**: T037

Use **Appendix B8**.

**Verification**: `uv run pytest tests/guardrails/test_agent_builtin_tool_boundaries.py -q`

---

### T034: Implement baseline-aware `write_file`

**File**: `src/business/agents/tools/file_tools.py` (new)

**Requirements**: FR-008, FR-009, FR-024

**Dependencies**: T023

Apply **Appendix A3**.

**Verification**: `uv run pytest tests/business/agents/test_builtin_file_tools.py -q`

---

### T035: Implement targeted `edit_file`

**File**: `src/business/agents/tools/file_tools.py` (new)

**Requirements**: FR-009, FR-010, FR-011, FR-012

**Dependencies**: T023, T034

Apply **Appendix A3**.

**Verification**: `uv run pytest tests/business/agents/test_builtin_file_tools.py -q`

---

### T036: Add per-file mutation serialization

**File**: `src/business/agents/tools/file_tools.py` (new)

**Requirements**: FR-009, SC-002

**Dependencies**: T034, T035

Apply **Appendix A3**. The module-level per-path lock registry serializes writes inside the current process; stale baseline checks still occur immediately before mutation.

**Verification**: `uv run pytest tests/business/agents/test_builtin_file_tools.py -q`

---

### T037: Apply workspace mutation policy and safe summaries

**File**: `src/business/agents/tools/builtin_permissions.py` (new)

**Requirements**: FR-003, FR-016, FR-017, CC-004, CC-007

**Dependencies**: T011

Apply **Appendix A2** and the facade wiring from T017.

**Verification**: `uv run pytest tests/guardrails/test_agent_builtin_tool_boundaries.py -q`

---

### T038: Replace legacy `write_file` and `edit_file` schemas, handlers, and pre-hooks

**File**: `src/business/agents/tools/builtin_general_tools.py` (modify)

**Requirements**: FR-002, FR-008, FR-009, FR-010, FR-011, FR-012

**Dependencies**: T034, T035, T037

Register `write_file` and `edit_file` from **Appendix A3** through the facade. Remove legacy `old_text` and `new_text` schema fields from `edit_file`; the new schema uses `replacements`.

**Verification**: `uv run pytest tests/business/agents/test_builtin_file_tools.py tests/test_hook_protocol.py -q`

---

### T039: Remove legacy write/edit result assumptions

**File**: `tests/test_hook_protocol.py` (modify)

**Requirements**: FR-002, CC-008

**Dependencies**: T038

**Before** (line 650):

```python
    assert target.read_text(encoding="utf-8") == "yes"
    assert json.loads(_tool_results(loop, "hook-confirm-approved")[0].content)["success"] is True
```

**After**:

```python
    assert target.read_text(encoding="utf-8") == "yes"
    payload = json.loads(_tool_results(loop, "hook-confirm-approved")[0].content)
    assert payload["schemaVersion"] == 1
    assert payload["tool"] == "write_file"
    assert payload["outcome"] == "success"
```

Also update edit-file hook tests to pass `expectedBaselineId` and `replacements` using a baseline produced by `read_file_handler`.

**Verification**: `uv run pytest tests/test_hook_protocol.py -q`

---

### T040: Run US2 scenarios

**File**: `specs/015-agent-builtin-tools-upgrade/quickstart.md` (existing verification path)

**Requirements**: SC-002, SC-010

**Dependencies**: T030 through T039

Run the US2 subset:

```powershell
uv run pytest tests/business/agents/test_builtin_file_tools.py tests/integration/test_agent_builtin_tool_contracts.py tests/test_hook_protocol.py -q
```

**Verification**: All US2 tests pass.

---

## Phase 5: User Story 3 - Search and Patch Workflows

### T041: Add `search_files` tests

**File**: `tests/business/agents/test_builtin_search_tools.py` (new)

**Requirements**: FR-014, FR-025

**Dependencies**: T045

Use **Appendix B2**.

**Verification**: `uv run pytest tests/business/agents/test_builtin_search_tools.py -q`

---

### T042: Add `search_content` tests

**File**: `tests/business/agents/test_builtin_search_tools.py` (new)

**Requirements**: FR-015, FR-025

**Dependencies**: T046

Use **Appendix B2**.

**Verification**: `uv run pytest tests/business/agents/test_builtin_search_tools.py -q`

---

### T043: Add `apply_patch` tests

**File**: `tests/business/agents/test_builtin_file_tools.py` (new)

**Requirements**: FR-013, FR-025

**Dependencies**: T047, T048

Use **Appendix B1**.

**Verification**: `uv run pytest tests/business/agents/test_builtin_file_tools.py -q`

---

### T044: Add search/patch boundary guard tests

**File**: `tests/guardrails/test_agent_builtin_tool_boundaries.py` (new)

**Requirements**: FR-003, FR-013, FR-014, FR-015, SC-003, SC-004

**Dependencies**: T049

Use **Appendix B8**.

**Verification**: `uv run pytest tests/guardrails/test_agent_builtin_tool_boundaries.py -q`

---

### T045: Implement structured file traversal

**File**: `src/business/agents/tools/search_tools.py` (new)

**Requirements**: FR-014

**Dependencies**: T010, T011

Apply **Appendix A4**.

**Verification**: `uv run pytest tests/business/agents/test_builtin_search_tools.py -q`

---

### T046: Implement structured content search

**File**: `src/business/agents/tools/search_tools.py` (new)

**Requirements**: FR-006, FR-015

**Dependencies**: T045

Apply **Appendix A4**.

**Verification**: `uv run pytest tests/business/agents/test_builtin_search_tools.py -q`

---

### T047: Implement `PatchOperation` validation and dry-run planning

**File**: `src/business/agents/tools/file_tools.py` (new)

**Requirements**: FR-013

**Dependencies**: T034, T035

Apply **Appendix A3**.

**Verification**: `uv run pytest tests/business/agents/test_builtin_file_tools.py -q`

---

### T048: Implement `apply_patch` mutation and verification

**File**: `src/business/agents/tools/file_tools.py` (new)

**Requirements**: FR-013, FR-024

**Dependencies**: T047

Apply **Appendix A3**.

**Verification**: `uv run pytest tests/business/agents/test_builtin_file_tools.py -q`

---

### T049: Apply workspace and patch policy

**File**: `src/business/agents/tools/builtin_permissions.py` (new)

**Requirements**: FR-003, FR-013, FR-016, CC-007

**Dependencies**: T011

Apply **Appendix A2** and facade wiring from T017.

**Verification**: `uv run pytest tests/guardrails/test_agent_builtin_tool_boundaries.py -q`

---

### T050: Register search and patch schemas and handlers

**File**: `src/business/agents/tools/builtin_general_tools.py` (modify)

**Requirements**: FR-002, FR-013, FR-014, FR-015

**Dependencies**: T045, T046, T048, T049

Add `search_files`, `search_content`, and `apply_patch` to `BUILTIN_GENERAL_TOOLS`. `search_files` and `search_content` are `has_side_effects=False`; `apply_patch` keeps side effects enabled.

**Verification**: `uv run pytest tests/business/agents/test_builtin_search_tools.py tests/business/agents/test_builtin_file_tools.py -q`

---

### T051: Update Agent-facing descriptions to prefer structured search and patch

**File**: `src/business/agents/tools/builtin_general_tools.py` (modify)

**Requirements**: FR-013, FR-014, FR-015

**Dependencies**: T050

Use descriptions from **Appendix A3** and **Appendix A4**. They tell Agents to use structured search and patch built-ins instead of shell parsing for repository navigation and multi-file mutation.

**Verification**: `uv run pytest tests/guardrails/test_agent_builtin_tool_boundaries.py -q`

---

### T052: Run US3 scenarios

**File**: `specs/015-agent-builtin-tools-upgrade/quickstart.md` (existing verification path)

**Requirements**: SC-003, SC-004

**Dependencies**: T041 through T051

Run:

```powershell
uv run pytest tests/business/agents/test_builtin_search_tools.py tests/business/agents/test_builtin_file_tools.py tests/guardrails/test_agent_builtin_tool_boundaries.py -q
```

**Verification**: All US3 tests pass.

---

## Phase 6: User Story 4 - Commands and Processes

### T053: Add synchronous `exec` tests

**File**: `tests/business/agents/test_builtin_command_tools.py` (new)

**Requirements**: FR-018, FR-025

**Dependencies**: T056, T060, T061

Use **Appendix B3**.

**Verification**: `uv run pytest tests/business/agents/test_builtin_command_tools.py -q`

---

### T054: Add background process lifecycle tests

**File**: `tests/integration/test_agent_builtin_process_lifecycle.py` (new)

**Requirements**: FR-019, FR-020, FR-025

**Dependencies**: T057, T058, T059, T060

Use **Appendix B7**.

**Verification**: `uv run pytest tests/integration/test_agent_builtin_process_lifecycle.py -q`

---

### T055: Add command/process guard tests

**File**: `tests/guardrails/test_agent_builtin_tool_boundaries.py` (new)

**Requirements**: FR-003, FR-016, FR-017, CC-004, FR-023

**Dependencies**: T061

Use **Appendix B8**.

**Verification**: `uv run pytest tests/guardrails/test_agent_builtin_tool_boundaries.py -q`

---

### T056: Implement synchronous command boundary

**File**: `src/execution/command_runner.py` (new)

**Requirements**: FR-018

**Dependencies**: T011, T013

Apply **Appendix A5**.

**Verification**: `python -m py_compile src/execution/command_runner.py`

---

### T057: Implement process record registry and log rings

**File**: `src/execution/process_manager.py` (new)

**Requirements**: FR-019

**Dependencies**: T056

Apply **Appendix A6**.

**Verification**: `python -m py_compile src/execution/process_manager.py`

---

### T058: Implement duplicate background start detection

**File**: `src/execution/process_manager.py` (new)

**Requirements**: FR-020

**Dependencies**: T057

Apply **Appendix A6**.

**Verification**: `uv run pytest tests/integration/test_agent_builtin_process_lifecycle.py -q`

---

### T059: Implement stop, cleanup, stdin, close, and restart-unavailable behavior

**File**: `src/execution/process_manager.py` (new)

**Requirements**: FR-019, FR-020

**Dependencies**: T057, T058

Apply **Appendix A6**.

**Verification**: `uv run pytest tests/integration/test_agent_builtin_process_lifecycle.py -q`

---

### T060: Implement command and process handlers

**File**: `src/business/agents/tools/command_tools.py` (new)

**Requirements**: FR-018, FR-019, FR-020

**Dependencies**: T056, T057, T058, T059

Apply **Appendix A7**.

**Verification**: `uv run pytest tests/business/agents/test_builtin_command_tools.py tests/integration/test_agent_builtin_process_lifecycle.py -q`

---

### T061: Apply command workspace policy and confirmation summaries

**File**: `src/business/agents/tools/builtin_permissions.py` (new)

**Requirements**: FR-003, FR-016, FR-017, CC-004

**Dependencies**: T011, T060

Apply **Appendix A2** and facade wiring from T017.

**Verification**: `uv run pytest tests/guardrails/test_agent_builtin_tool_boundaries.py -q`

---

### T062: Register command and process schemas and handlers

**File**: `src/business/agents/tools/builtin_general_tools.py` (modify)

**Requirements**: FR-002, FR-018, FR-019

**Dependencies**: T060, T061

Add `exec`, `process_list`, `process_poll`, `process_logs`, `process_wait`, `process_stop`, `process_send_input`, and `process_close` to `BUILTIN_GENERAL_TOOLS`.

**Verification**: `uv run pytest tests/business/agents/test_builtin_command_tools.py tests/business/agents/test_builtin_general_tools.py -q`

---

### T063: Remove legacy `exec` timeout/output/result-shape assumptions

**File**: `tests/test_hook_protocol.py` (modify)

**Requirements**: FR-002, FR-018, CC-008

**Dependencies**: T062

Update assertions from legacy `returncode`, `stdout`, `stderr`, or plain standardized error to the envelope fields: `schemaVersion`, `tool`, `outcome`, `payload.status`, `payload.exitCode`, `limits`, and `error.code`.

**Verification**: `uv run pytest tests/test_hook_protocol.py -q`

---

### T064: Run US4 scenarios

**File**: `specs/015-agent-builtin-tools-upgrade/quickstart.md` (existing verification path)

**Requirements**: SC-007, SC-008

**Dependencies**: T053 through T063

Run:

```powershell
uv run pytest tests/business/agents/test_builtin_command_tools.py tests/integration/test_agent_builtin_process_lifecycle.py tests/guardrails/test_agent_builtin_tool_boundaries.py -q
```

**Verification**: All US4 tests pass.

---

## Phase 7: User Story 5 - Compact and Recover Tool Results

### T065: Add output governance tests

**File**: `tests/business/agents/test_builtin_output_governance.py` (new)

**Requirements**: FR-021, FR-022, FR-023, FR-024

**Dependencies**: T073, T075

Use **Appendix B4**.

**Verification**: `uv run pytest tests/business/agents/test_builtin_output_governance.py -q`

---

### T066: Add `ToolOutputRepository` tests

**File**: `tests/data/test_tool_output_repository.py` (new)

**Requirements**: FR-021, FR-023

**Dependencies**: T071, T072

Use **Appendix B5**.

**Verification**: `uv run pytest tests/data/test_tool_output_repository.py -q`

---

### T067: Add AgentLoop oversized-output and restart recovery tests

**File**: `tests/integration/test_agent_builtin_tool_contracts.py` (new)

**Requirements**: FR-021, FR-022, FR-023

**Dependencies**: T074, T075

Use **Appendix B6**.

**Verification**: `uv run pytest tests/integration/test_agent_builtin_tool_contracts.py -q`

---

### T068: Add raw artifact security leak tests

**File**: `tests/guardrails/test_agent_builtin_tool_boundaries.py` (new)

**Requirements**: FR-006, FR-023, CC-004

**Dependencies**: T072, T073, T075

Use **Appendix B8**.

**Verification**: `uv run pytest tests/guardrails/test_agent_builtin_tool_boundaries.py -q`

---

### T069: Add `ToolOutputReference` ORM model

**File**: `src/data/models_sqlite.py` (modify)

**Requirements**: FR-021, FR-023

**Dependencies**: T010

Insert after `AppSettings`.

```python
class ToolOutputReferenceRecord(Base):
    """Persistent metadata for raw built-in tool output blobs."""

    __tablename__ = "tool_output_references"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'expired', 'deleted')",
            name="ck_tool_output_reference_status",
        ),
        Index("idx_tool_output_reference_session", "session_id"),
        Index("idx_tool_output_reference_tool_call", "tool_call_id"),
        Index("idx_tool_output_reference_status", "status"),
        Index("idx_tool_output_reference_expires", "expires_at"),
    )

    reference_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False)
    session_id: Mapped[str] = mapped_column(String(50), nullable=False)
    tool_call_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    storage_root_kind: Mapped[str] = mapped_column(String(40), nullable=False, default="tool_outputs")
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False, default="text/plain")
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    owner_workspace_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    redaction_profile: Mapped[str] = mapped_column(String(40), nullable=False, default="standard")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
```

**Verification**: `python -m py_compile src/data/models_sqlite.py`

---

### T070: Add v13 SQLite migration

**File**: `src/data/migrations.py` (modify)

**Requirements**: FR-021, FR-023, CC-006

**Dependencies**: T069

Insert `migrate_to_v13` after `migrate_to_v12`, then append `(13, migrate_to_v13)` to `_MIGRATIONS`.

```python
def migrate_to_v13(engine):
    """迁移到版本 13：Agent built-in raw output references."""
    with engine.connect() as conn:
        try:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS tool_output_references (
                    reference_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    tool_call_id TEXT,
                    storage_key TEXT NOT NULL,
                    storage_root_kind TEXT NOT NULL DEFAULT 'tool_outputs',
                    size_bytes INTEGER NOT NULL,
                    content_type TEXT NOT NULL DEFAULT 'text/plain',
                    sha256 TEXT NOT NULL,
                    owner_workspace_hash TEXT NOT NULL,
                    redaction_profile TEXT NOT NULL DEFAULT 'standard',
                    status TEXT NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'expired', 'deleted')),
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    expires_at DATETIME,
                    deleted_at DATETIME
                )
            """))
            for index_sql in [
                "CREATE INDEX IF NOT EXISTS idx_tool_output_reference_session ON tool_output_references(session_id)",
                "CREATE INDEX IF NOT EXISTS idx_tool_output_reference_tool_call ON tool_output_references(tool_call_id)",
                "CREATE INDEX IF NOT EXISTS idx_tool_output_reference_status ON tool_output_references(status)",
                "CREATE INDEX IF NOT EXISTS idx_tool_output_reference_expires ON tool_output_references(expires_at)",
            ]:
                conn.execute(text(index_sql))
            conn.execute(text("UPDATE schema_version SET version = :v"), {"v": 13})
            conn.commit()
            logger.info("数据库迁移到版本 13 完成：Agent built-in raw output references")
        except Exception as e:
            conn.rollback()
            logger.error(f"迁移到版本 13 失败: {e}")
            raise
```

**Rollback strategy**: This project uses forward-only migrations. Recovery is to stop registering `load_tool_output`; the metadata stays inert and retention cleanup removes expired blobs.

**Verification**: `uv run pytest tests/data/test_migrations.py tests/data/test_tool_output_repository.py -q`

---

### T071: Implement `ToolOutputRepository`

**File**: `src/data/repos/tool_output_repository.py` (new)

**Requirements**: FR-021, FR-023

**Dependencies**: T069, T070

Apply **Appendix A9**.

**Verification**: `uv run pytest tests/data/test_tool_output_repository.py -q`

---

### T072: Implement private blob storage and cleanup

**File**: `src/data/repos/tool_output_repository.py` (new)

**Requirements**: FR-021, FR-023, FR-027

**Dependencies**: T071

Apply **Appendix A9**.

**Verification**: `uv run pytest tests/data/test_tool_output_repository.py -q`

---

### T073: Implement output governance

**File**: `src/business/agents/tools/output_governance.py` (new)

**Requirements**: FR-006, FR-021, FR-022, FR-023, FR-024

**Dependencies**: T010, T071, T072

Apply **Appendix A8**.

**Verification**: `uv run pytest tests/business/agents/test_builtin_output_governance.py -q`

---

### T074: Extend AgentLoop governed persistence wrapper

**File**: `src/business/agents/agent_loop.py` (modify)

**Requirements**: FR-021, FR-022

**Dependencies**: T015, T073

The wrapper from T015 already delegates to `govern_tool_result`; after T073 is implemented, oversized built-in envelopes receive raw references before persistence.

**Verification**: `uv run pytest tests/integration/test_agent_builtin_tool_contracts.py -q`

---

### T075: Implement `load_tool_output`

**File**: `src/business/agents/tools/output_governance.py` (new)

**Requirements**: FR-021, FR-023

**Dependencies**: T071, T073

Apply **Appendix A8**.

**Verification**: `uv run pytest tests/business/agents/test_builtin_output_governance.py tests/integration/test_agent_builtin_tool_contracts.py -q`

---

### T076: Register `load_tool_output`

**File**: `src/business/agents/tools/builtin_general_tools.py` (modify)

**Requirements**: FR-002, FR-021, FR-023

**Dependencies**: T075

Add `load_tool_output` with `has_side_effects=False`.

**Verification**: `uv run pytest tests/business/agents/test_builtin_general_tools.py tests/business/agents/test_builtin_output_governance.py -q`

---

### T077: Add retention cleanup entrypoints and runtime health counters

**File**: `src/business/agents/tools/output_governance.py` (new)

**Requirements**: FR-027

**Dependencies**: T071, T073

Apply **Appendix A8**.

**Verification**: `uv run pytest tests/business/agents/test_builtin_output_governance.py tests/data/test_tool_output_repository.py -q`

---

### T078: Run US5 scenarios

**File**: `specs/015-agent-builtin-tools-upgrade/quickstart.md` (existing verification path)

**Requirements**: SC-005, SC-006, SC-011

**Dependencies**: T065 through T077

Run:

```powershell
uv run pytest tests/business/agents/test_builtin_output_governance.py tests/data/test_tool_output_repository.py tests/integration/test_agent_builtin_tool_contracts.py tests/guardrails/test_agent_builtin_tool_boundaries.py -q
```

**Verification**: All US5 tests pass.

---

## Phase 8: Polish and Cross-Cutting

### T079: Update active project constraints

**File**: `docs/PROJECT_CONSTRAINTS.md` (modify)

**Requirements**: CC-004, CC-005, CC-006, CC-007, CC-008, CC-009

**Dependencies**: all implementation tasks

Append a section named `Agent Built-in Tool Boundaries` covering: stable envelopes, fixed workspace policy, baseline-required mutation, raw artifact security, process-session scope, non-UI tuning knobs, and no legacy compatibility window.

**Verification**: `Select-String -Path docs/PROJECT_CONSTRAINTS.md -Pattern 'Agent Built-in Tool Boundaries'`

---

### T080: Update runtime architecture notes

**File**: `docs/ARCHITECTURE.md` (modify)

**Requirements**: FR-019, FR-021, FR-023

**Dependencies**: T057, T071, T073

Add the built-in tool subsystem below the Agent Loop section: facade module, focused modules, execution process manager, raw-output repository, and governance boundary.

**Verification**: `Select-String -Path docs/ARCHITECTURE.md -Pattern 'built-in tool subsystem'`

---

### T081: Update mirrored root AI entry documents

**File**: `AGENTS.md` (modify)
**File**: `CLAUDE.md` (modify)
**File**: `GEMINI.md` (modify)

**Requirements**: CC-004, CC-005, CC-006, CC-007, CC-008

**Dependencies**: T079

Add identical guidance to all three files under Known Issues: built-in tools must use stable envelopes, workspace policy, baseline mutation, raw-output references, and unified config.

**Verification**: `fc AGENTS.md CLAUDE.md` and `fc AGENTS.md GEMINI.md`

---

### T082: Update mirrored backend AI entry documents

**File**: `src/AGENTS.md` (modify)
**File**: `src/CLAUDE.md` (modify)
**File**: `src/GEMINI.md` (modify)

**Requirements**: CC-004, CC-005, CC-006, CC-007, CC-008

**Dependencies**: T079

Add identical backend guidance under Agent and tool constraints.

**Verification**: `fc src\AGENTS.md src\CLAUDE.md` and `fc src\AGENTS.md src\GEMINI.md`

---

### T083: Remove remaining legacy compatibility assumptions

**File**: `src/business/agents/tools/builtin_general_tools.py` (modify)

**Requirements**: FR-002, CC-008, SC-009

**Dependencies**: T027, T038, T050, T062, T076

Remove exported legacy handler internals for migrated tools except stable names needed by tests or imports. The remaining facade must mount upgraded schemas and handlers only.

**Verification**: `uv run pytest tests/guardrails/test_agent_builtin_tool_boundaries.py -q`

---

### T084: Add no-legacy-built-in-contract guard

**File**: `tests/guardrails/test_agent_builtin_tool_boundaries.py` (new)

**Requirements**: FR-002, SC-009

**Dependencies**: T083

Use **Appendix B8**.

**Verification**: `uv run pytest tests/guardrails/test_agent_builtin_tool_boundaries.py -q`

---

### T085: Run focused quickstart test groups

**File**: `specs/015-agent-builtin-tools-upgrade/quickstart.md` (existing verification path)

**Requirements**: FR-025

**Dependencies**: T001 through T084

Run quickstart sections 1 through 3.

**Verification**: Focused unit, integration, and guardrail suites pass.

---

### T086: Run broad regression and formatting

**File**: `specs/015-agent-builtin-tools-upgrade/quickstart.md` (existing verification path)

**Requirements**: FR-025

**Dependencies**: T085

Run:

```powershell
uv run pytest tests/
uv run black src tests
uv run flake8 src tests
```

**Verification**: Record any local environment exception with reason, risk, and follow-up in the implementation report.

---

## Appendix A1: `src/business/agents/tools/builtin_contracts.py`

```python
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


SCHEMA_VERSION = 1

OUTCOME_SUCCESS = "success"
OUTCOME_ERROR = "error"
OUTCOME_REJECTED = "rejected"
OUTCOME_UNSUPPORTED = "unsupported"
OUTCOME_TIMEOUT = "timeout"
OUTCOME_BACKGROUND_STARTED = "background_started"
OUTCOME_NOT_EXECUTED = "not_executed"
OUTCOME_CONFIRMATION_REQUIRED = "confirmation_required"

OUTCOMES = frozenset(
    {
        OUTCOME_SUCCESS,
        OUTCOME_ERROR,
        OUTCOME_REJECTED,
        OUTCOME_UNSUPPORTED,
        OUTCOME_TIMEOUT,
        OUTCOME_BACKGROUND_STARTED,
        OUTCOME_NOT_EXECUTED,
        OUTCOME_CONFIRMATION_REQUIRED,
    }
)

ERROR_CODES = frozenset(
    {
        "path_not_found",
        "path_not_file",
        "path_not_directory",
        "path_outside_workspace",
        "path_hidden_or_system",
        "permission_denied",
        "confirmation_failed_closed",
        "unsupported_binary",
        "decode_failed",
        "baseline_required",
        "baseline_stale",
        "edit_target_not_found",
        "edit_target_not_unique",
        "patch_validation_failed",
        "search_pattern_invalid",
        "command_rejected",
        "command_timeout",
        "process_not_found",
        "process_unavailable_after_restart",
        "output_reference_not_found",
        "output_reference_expired",
        "compaction_failed_fallback",
        "internal_error",
        "unknown_tool",
        "pre_hook_rejected",
        "pre_hook_exception",
        "handler_exception",
        "handler_contract_violation",
        "invalid_model_output",
        "not_executed",
        "standardized_error",
    }
)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class ToolError:
    code: str
    message: str
    retryable: bool = False
    nextAction: str | None = None
    details: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.code not in ERROR_CODES:
            raise ValueError(f"unknown built-in tool error code: {self.code}")


@dataclass(frozen=True)
class PermissionDecision:
    scope: str
    risk: str
    decision: str
    summary: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class ToolOutputReference:
    referenceId: str
    kind: str
    sizeBytes: int
    contentType: str | None = None
    sha256: str | None = None
    expiresAt: str | None = None


@dataclass(frozen=True)
class VerificationResult:
    status: str
    oldBaseline: str | None = None
    newBaseline: str | None = None
    message: str | None = None


@dataclass(frozen=True)
class ToolResultEnvelope:
    tool: str
    outcome: str
    payload: dict[str, Any] = field(default_factory=dict)
    error: ToolError | None = None
    permission: PermissionDecision | None = None
    limits: dict[str, Any] | None = None
    references: list[ToolOutputReference] | None = None
    warnings: list[str] | None = None
    verification: VerificationResult | None = None
    createdAt: str = field(default_factory=utc_now_iso)
    schemaVersion: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.outcome not in OUTCOMES:
            raise ValueError(f"unknown built-in tool outcome: {self.outcome}")
        if self.outcome in {
            OUTCOME_ERROR,
            OUTCOME_REJECTED,
            OUTCOME_UNSUPPORTED,
            OUTCOME_TIMEOUT,
            OUTCOME_NOT_EXECUTED,
        } and self.error is None:
            raise ValueError(f"outcome {self.outcome} requires ToolError")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return {key: value for key, value in data.items() if value is not None}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)


def envelope_json(
    *,
    tool: str,
    outcome: str,
    payload: dict[str, Any] | None = None,
    error: ToolError | None = None,
    permission: PermissionDecision | None = None,
    limits: dict[str, Any] | None = None,
    references: list[ToolOutputReference] | None = None,
    warnings: list[str] | None = None,
    verification: VerificationResult | None = None,
) -> str:
    return ToolResultEnvelope(
        tool=tool,
        outcome=outcome,
        payload=payload or {},
        error=error,
        permission=permission,
        limits=limits,
        references=references,
        warnings=warnings,
        verification=verification,
    ).to_json()


def success_envelope_json(
    tool: str,
    payload: dict[str, Any],
    *,
    permission: PermissionDecision | None = None,
    limits: dict[str, Any] | None = None,
    references: list[ToolOutputReference] | None = None,
    warnings: list[str] | None = None,
    verification: VerificationResult | None = None,
    outcome: str = OUTCOME_SUCCESS,
) -> str:
    return envelope_json(
        tool=tool,
        outcome=outcome,
        payload=payload,
        permission=permission,
        limits=limits,
        references=references,
        warnings=warnings,
        verification=verification,
    )


def error_envelope_json(
    tool: str,
    code: str,
    message: str,
    *,
    outcome: str = OUTCOME_ERROR,
    retryable: bool = False,
    next_action: str | None = None,
    details: dict[str, Any] | None = None,
    permission: PermissionDecision | None = None,
    payload: dict[str, Any] | None = None,
) -> str:
    return envelope_json(
        tool=tool,
        outcome=outcome,
        payload=payload or {},
        error=ToolError(
            code=code,
            message=message,
            retryable=retryable,
            nextAction=next_action,
            details=details,
        ),
        permission=permission,
    )


def fallback_envelope_json(
    *,
    tool: str,
    error_code: str,
    message: str,
    payload: dict[str, Any] | None = None,
) -> str:
    return error_envelope_json(
        tool,
        error_code,
        message,
        outcome=OUTCOME_ERROR,
        payload=payload or {},
        retryable=True,
    )


def is_envelope_json(content: str) -> bool:
    try:
        data = json.loads(content)
    except Exception:
        return False
    return isinstance(data, dict) and data.get("schemaVersion") == SCHEMA_VERSION


def standardized_error_to_envelope(tool: str, content: str) -> str:
    try:
        data = json.loads(content)
    except Exception:
        return error_envelope_json(tool, "standardized_error", str(content))
    code = data.get("error")
    if not isinstance(code, str):
        return success_envelope_json(tool, {"result": data})
    if code not in ERROR_CODES:
        code = "standardized_error"
    message = str(data.get("message") or data.get("error") or "Tool call failed.")
    details = {k: v for k, v in data.items() if k not in {"error", "message"}}
    return error_envelope_json(
        tool,
        code,
        message,
        outcome=OUTCOME_REJECTED if code in {"pre_hook_rejected", "permission_denied"} else OUTCOME_ERROR,
        details=details or None,
    )
```

## Appendix A2: `src/business/agents/tools/builtin_permissions.py`

```python
from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from src.business.agents.hook_models import PreHookResult, ToolCallContext
from src.business.agents.tools.builtin_contracts import PermissionDecision


SYSTEM_ROOTS = tuple(Path(p) for p in ("C:/Windows", "C:/Program Files", "C:/Program Files (x86)", "/etc", "/usr", "/bin", "/sbin"))
SAFE_EXEC_COMMANDS = frozenset({"dir", "ls", "pwd", "echo", "type", "cat", "python --version", "python3 --version", "whoami", "hostname"})
SECRET_PATTERN = re.compile(r"(?i)(sk-[A-Za-z0-9_-]+|api[_-]?key\s*=\s*\S+|token\s*=\s*\S+|password\s*=\s*\S+|secret\s*=\s*\S+)")


@dataclass(frozen=True)
class PathClassification:
    requested: str
    resolved: Path
    workspace_root: Path
    scope: str
    reason: str

    @property
    def inside_workspace(self) -> bool:
        return self.scope == "workspace"


def workspace_root(explicit: str | None = None) -> Path:
    raw = explicit or os.environ.get("EXEMPLAR_AGENT_WORKSPACE") or os.getcwd()
    return Path(raw).expanduser().resolve()


def resolve_under_workspace(path: str, root: str | None = None) -> tuple[Path, Path]:
    base = workspace_root(root)
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = base / candidate
    return candidate.resolve(), base


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _is_hidden(path: Path) -> bool:
    return any(part.startswith(".") for part in path.parts if part not in {".", ".."})


def _is_system(path: Path) -> bool:
    for root in SYSTEM_ROOTS:
        try:
            resolved_root = root.resolve()
        except Exception:
            resolved_root = root
        if _is_relative_to(path, resolved_root):
            return True
    return False


def classify_path(path: str, root: str | None = None) -> PathClassification:
    resolved, base = resolve_under_workspace(path, root)
    if _is_relative_to(resolved, base):
        scope = "hidden" if _is_hidden(resolved.relative_to(base)) else "workspace"
        return PathClassification(path, resolved, base, scope, scope)
    if _is_system(resolved):
        return PathClassification(path, resolved, base, "system", "system_path")
    return PathClassification(path, resolved, base, "external", "outside_workspace")


def permission_for_path(
    path: str,
    *,
    operation: str,
    workspace: str | None = None,
) -> PermissionDecision:
    classified = classify_path(path, workspace)
    if operation == "read":
        if classified.scope == "workspace":
            return PermissionDecision("workspace", "read_only", "allowed", reason="workspace_read")
        return PermissionDecision(classified.scope, "elevated", "confirmation_required", build_read_confirmation_summary(classified.resolved), classified.reason)
    if classified.scope != "workspace":
        return PermissionDecision(classified.scope, "denied", "denied", reason="outside_workspace_mutation_denied")
    return PermissionDecision("workspace", "workspace_mutation", "allowed", reason="workspace_mutation")


def redact_fragment(value: object, max_len: int = 160) -> str:
    text = " ".join(str(value).split())
    text = SECRET_PATTERN.sub("[redacted]", text)
    if len(text) > max_len:
        return text[: max_len - 12] + "[truncated]"
    return text


def display_path(path: Path, root: Path | None = None) -> str:
    if root is not None:
        try:
            return str(path.relative_to(root)).replace("\\", "/")
        except ValueError:
            pass
    return path.name if len(str(path)) > 80 else str(path)


def build_read_confirmation_summary(path: Path) -> str:
    return f"Read outside workspace: {redact_fragment(path)}; reason: exceptional inspection"


def build_mutation_confirmation_summary(path: str, operation: str, baseline: str | None, workspace: str | None = None) -> str:
    classified = classify_path(path, workspace)
    base = baseline[:16] if baseline else "missing"
    return f"Mutate workspace file: {display_path(classified.resolved, classified.workspace_root)}; operation: {operation}; baseline: {base}"


def build_command_confirmation_summary(command: str, cwd: str | None = None) -> str:
    first_line = str(command).splitlines()[0] if str(command).splitlines() else ""
    return f"Run elevated command in workspace: {redact_fragment(first_line, 180)}"


def is_safe_exec_command(command: str) -> bool:
    text = str(command).strip()
    if not text:
        return False
    lowered = text.lower()
    if any(marker in lowered for marker in (";", "|", "&", "`", "$(", ">", "<", "\n", "\r")):
        return False
    try:
        first = shlex.split(text, posix=os.name != "nt")[0].lower()
    except Exception:
        first = lowered.split()[0]
    return first in SAFE_EXEC_COMMANDS


def classify_command_request(command: str, cwd: str | None = None, workspace: str | None = None) -> PermissionDecision:
    classified = classify_path(cwd or ".", workspace)
    if classified.scope != "workspace":
        return PermissionDecision(classified.scope, "denied", "denied", reason="outside_workspace_execution_denied")
    if is_safe_exec_command(command):
        return PermissionDecision("workspace", "read_only", "allowed", reason="safe_command")
    return PermissionDecision("workspace", "elevated", "confirmation_required", build_command_confirmation_summary(command), "elevated_command")


def prehook_path_policy(ctx: ToolCallContext, *, key: str = "path", operation: str) -> PreHookResult | None:
    path = str(ctx.args.get(key, ""))
    decision = permission_for_path(path, operation=operation)
    if decision.decision == "denied":
        return PreHookResult(error=decision.reason or "permission denied")
    return None


def ensure_all_workspace_paths(paths: Iterable[str], workspace: str | None = None) -> PermissionDecision | None:
    for path in paths:
        decision = permission_for_path(path, operation="mutate", workspace=workspace)
        if decision.decision == "denied":
            return decision
    return None
```

## Appendix A3: `src/business/agents/tools/file_tools.py`

```python
from __future__ import annotations

import hashlib
import json
import mimetypes
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.business.agents.tool_helpers import make_tool_schema
from src.business.agents.tools.builtin_contracts import (
    OUTCOME_REJECTED,
    OUTCOME_UNSUPPORTED,
    VerificationResult,
    error_envelope_json,
    success_envelope_json,
)
from src.business.agents.tools.builtin_permissions import classify_path, display_path, permission_for_path, redact_fragment
from src.data.unified_config import get_unified_config


READ_FILE_SCHEMA = make_tool_schema(
    name="read_file",
    description="Read a bounded, redacted text window from a file. Returns line metadata, continuation, baseline, unsupported binary/media outcome, and repeat-read metadata.",
    properties={
        "path": {"type": "string", "description": "Workspace-relative or absolute path."},
        "startLine": {"type": "integer", "description": "One-based first line. Default 1."},
        "maxLines": {"type": "integer", "description": "Maximum lines to return. Capped by configuration."},
        "encoding": {"type": "string", "description": "Text encoding. Default utf-8."},
        "includeLineNumbers": {"type": "boolean", "description": "Include numbered rows. Default true."},
    },
    required=["path"],
)

WRITE_FILE_SCHEMA = make_tool_schema(
    name="write_file",
    description="Create a new text file or replace an existing workspace file. Existing files require a current baseline from read_file.",
    properties={
        "path": {"type": "string"},
        "content": {"type": "string"},
        "expectedBaselineId": {"type": "string"},
        "expectedSha256": {"type": "string"},
        "encoding": {"type": "string"},
    },
    required=["path", "content"],
)

EDIT_FILE_SCHEMA = make_tool_schema(
    name="edit_file",
    description="Apply baseline-checked targeted replacements to an existing workspace text file.",
    properties={
        "path": {"type": "string"},
        "expectedBaselineId": {"type": "string"},
        "expectedSha256": {"type": "string"},
        "replacements": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "oldText": {"type": "string"},
                    "newText": {"type": "string"},
                    "replaceAll": {"type": "boolean"},
                },
                "required": ["oldText", "newText"],
            },
        },
    },
    required=["path", "expectedBaselineId", "replacements"],
)

APPLY_PATCH_SCHEMA = make_tool_schema(
    name="apply_patch",
    description="Validate and apply an all-or-reject multi-file add, update, or delete patch inside the workspace. Update and delete require current baselines.",
    properties={"operations": {"type": "array"}},
    required=["operations"],
)

_BINARY_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".zip", ".mp4", ".mov", ".exe", ".dll"}
_read_seen: dict[str, int] = {}
_mutation_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


@dataclass(frozen=True)
class Baseline:
    baselineId: str
    sha256: str
    sizeBytes: int
    modifiedAt: float | None

    def to_payload(self) -> dict[str, Any]:
        return {
            "baselineId": self.baselineId,
            "sha256": self.sha256,
            "sizeBytes": self.sizeBytes,
            "modifiedAt": self.modifiedAt,
        }


def _config_int(name: str, default: int) -> int:
    cfg = get_unified_config()
    getter = getattr(cfg, name, None)
    if getter is None:
        return default
    try:
        return int(getter())
    except Exception:
        return default


def _baseline(path: Path) -> Baseline:
    raw = path.read_bytes()
    stat = path.stat()
    digest = hashlib.sha256(raw).hexdigest()
    return Baseline(f"base_{digest[:20]}_{stat.st_size}", digest, stat.st_size, stat.st_mtime)


def _binary_kind(path: Path, raw: bytes) -> str | None:
    suffix = path.suffix.lower()
    if suffix in _BINARY_EXTENSIONS:
        return "media" if suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".mp4", ".mov"} else "binary"
    if b"\x00" in raw[:4096]:
        return "binary"
    return None


def _decode(raw: bytes, encoding: str) -> tuple[str | None, str]:
    try:
        return raw.decode(encoding), encoding
    except UnicodeDecodeError:
        try:
            return raw.decode("utf-8-sig"), "utf-8-sig"
        except UnicodeDecodeError:
            return None, encoding


def _redact(text: str) -> tuple[str, list[dict[str, Any]]]:
    redacted = text
    categories = []
    before = redacted
    redacted = __import__("re").sub(r"(?i)(sk-[A-Za-z0-9_-]+|api[_-]?key\s*=\s*\S+|token\s*=\s*\S+|password\s*=\s*\S+|secret\s*=\s*\S+)", "[redacted]", redacted)
    if redacted != before:
        categories.append({"category": "secret_like", "count": before.count("=")})
    return redacted, categories


def _lock_for(path: Path) -> threading.Lock:
    key = str(path)
    with _locks_guard:
        lock = _mutation_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _mutation_locks[key] = lock
        return lock


def _check_existing_baseline(path: Path, expectedBaselineId: str | None, expectedSha256: str | None) -> tuple[bool, str | None, Baseline | None]:
    current = _baseline(path)
    if not expectedBaselineId and not expectedSha256:
        return False, "baseline_required", current
    if expectedBaselineId and expectedBaselineId != current.baselineId:
        return False, "baseline_stale", current
    if expectedSha256 and expectedSha256 != current.sha256:
        return False, "baseline_stale", current
    return True, None, current


def _line_window(text: str, start: int, max_lines: int, max_chars: int) -> tuple[str, int, int, int, bool, bool]:
    lines = text.splitlines()
    total = len(lines)
    start = max(1, start)
    end = min(total, start + max_lines - 1)
    selected = lines[start - 1 : end]
    content = "\n".join(selected)
    if len(content) > max_chars:
        content = content[:max_chars]
    return content, start, end, total, start > 1, end < total


def read_file_handler(path: str, startLine: int = 1, maxLines: int | None = None, encoding: str = "utf-8", includeLineNumbers: bool = True) -> str:
    tool = "read_file"
    classified = classify_path(path)
    p = classified.resolved
    if not p.exists():
        return error_envelope_json(tool, "path_not_found", "File does not exist.", outcome=OUTCOME_REJECTED)
    if not p.is_file():
        return error_envelope_json(tool, "path_not_file", "Path is not a file.", outcome=OUTCOME_REJECTED)
    max_decode = _config_int("get_agent_tools_file_max_decode_bytes", 1048576)
    raw = p.read_bytes()
    kind = _binary_kind(p, raw)
    if kind is not None:
        return error_envelope_json(
            tool,
            "unsupported_binary",
            "Binary or media files are not rendered as text.",
            outcome=OUTCOME_UNSUPPORTED,
            payload={"path": display_path(p, classified.workspace_root), "fileType": kind, "sizeBytes": len(raw), "contentType": mimetypes.guess_type(str(p))[0]},
        )
    limited_raw = raw[:max_decode]
    decoded, used_encoding = _decode(limited_raw, encoding or "utf-8")
    if decoded is None:
        return error_envelope_json(tool, "decode_failed", "Could not decode file as text.", outcome=OUTCOME_UNSUPPORTED)
    max_lines = min(int(maxLines or _config_int("get_agent_tools_file_default_max_lines", 200)), 1000)
    max_chars = _config_int("get_agent_tools_file_max_window_chars", 50000)
    content, line_start, line_end, total, before, after = _line_window(decoded, int(startLine or 1), max_lines, max_chars)
    content, redactions = _redact(content)
    base = _baseline(p)
    window_key = hashlib.sha256(f"{p}:{line_start}:{line_end}:{base.sha256}".encode("utf-8")).hexdigest()
    _read_seen[window_key] = _read_seen.get(window_key, 0) + 1
    numbered = [
        {"line": line_start + index, "text": line}
        for index, line in enumerate(content.splitlines())
    ] if includeLineNumbers else None
    payload = {
        "path": display_path(p, classified.workspace_root),
        "fileType": "text",
        "encoding": used_encoding,
        "lineStart": line_start,
        "lineEnd": line_end,
        "totalLines": total,
        "hasMoreBefore": before,
        "hasMoreAfter": after,
        "content": content,
        "lineNumbers": numbered,
        "baseline": base.to_payload(),
        "redactions": redactions,
        "repeatRead": {"windowKey": window_key, "seenCount": _read_seen[window_key]},
    }
    return success_envelope_json(tool, payload, limits={"truncated": after or len(raw) > len(limited_raw), "lineStart": line_start, "lineEnd": line_end, "hasMore": after})


def write_file_handler(path: str, content: str, expectedBaselineId: str | None = None, expectedSha256: str | None = None, encoding: str = "utf-8") -> str:
    tool = "write_file"
    decision = permission_for_path(path, operation="mutate")
    if decision.decision == "denied":
        return error_envelope_json(tool, "path_outside_workspace", "Writes outside the workspace are denied.", outcome=OUTCOME_REJECTED, permission=decision)
    classified = classify_path(path)
    p = classified.resolved
    with _lock_for(p):
        old = _baseline(p) if p.exists() and p.is_file() else None
        if p.exists():
            ok, code, current = _check_existing_baseline(p, expectedBaselineId, expectedSha256)
            if not ok:
                return error_envelope_json(tool, code or "baseline_required", "Existing file mutation requires a current baseline.", outcome=OUTCOME_REJECTED, payload={"currentBaseline": current.to_payload() if current else None})
        p.parent.mkdir(parents=True, exist_ok=True)
        raw = str(content).encode(encoding or "utf-8")
        p.write_bytes(raw)
        new = _baseline(p)
    payload = {"path": display_path(p, classified.workspace_root), "bytesWritten": len(raw), "created": old is None, "changeSummary": {"operation": "create" if old is None else "replace"}}
    return success_envelope_json(tool, payload, verification=VerificationResult("verified", old.baselineId if old else None, new.baselineId, "Readback hash matched."))


def _plan_replacements(text: str, replacements: list[dict[str, Any]]) -> tuple[list[tuple[int, int, str]], str | None]:
    spans: list[tuple[int, int, str]] = []
    for item in replacements:
        old = str(item.get("oldText", ""))
        new = str(item.get("newText", ""))
        replace_all = bool(item.get("replaceAll", False))
        if old == "":
            return [], "edit_target_not_found"
        starts = []
        pos = text.find(old)
        while pos >= 0:
            starts.append(pos)
            pos = text.find(old, pos + len(old))
        if not starts:
            return [], "edit_target_not_found"
        if len(starts) > 1 and not replace_all:
            return [], "edit_target_not_unique"
        for start in starts:
            spans.append((start, start + len(old), new))
    spans.sort(key=lambda entry: entry[0])
    for previous, current in zip(spans, spans[1:]):
        if current[0] < previous[1]:
            return [], "patch_validation_failed"
    return spans, None


def edit_file_handler(path: str, expectedBaselineId: str, replacements: list[dict[str, Any]], expectedSha256: str | None = None) -> str:
    tool = "edit_file"
    decision = permission_for_path(path, operation="mutate")
    if decision.decision == "denied":
        return error_envelope_json(tool, "path_outside_workspace", "Edits outside the workspace are denied.", outcome=OUTCOME_REJECTED, permission=decision)
    classified = classify_path(path)
    p = classified.resolved
    if not p.exists():
        return error_envelope_json(tool, "path_not_found", "File does not exist.", outcome=OUTCOME_REJECTED)
    with _lock_for(p):
        ok, code, old_base = _check_existing_baseline(p, expectedBaselineId, expectedSha256)
        if not ok:
            return error_envelope_json(tool, code or "baseline_required", "Edit requires a current baseline.", outcome=OUTCOME_REJECTED)
        raw = p.read_bytes()
        text, used_encoding = _decode(raw, "utf-8")
        if text is None:
            return error_envelope_json(tool, "decode_failed", "Could not decode file as text.", outcome=OUTCOME_UNSUPPORTED)
        spans, error_code = _plan_replacements(text, replacements or [])
        if error_code:
            return error_envelope_json(tool, error_code, "Replacement targets could not be applied.", outcome=OUTCOME_REJECTED)
        parts = []
        cursor = 0
        for start, end, new in spans:
            parts.append(text[cursor:start])
            parts.append(new)
            cursor = end
        parts.append(text[cursor:])
        new_text = "".join(parts)
        p.write_bytes(new_text.encode(used_encoding))
        new_base = _baseline(p)
    payload = {"path": display_path(p, classified.workspace_root), "changeSummary": {"operation": "edit", "replacementCount": len(spans)}}
    return success_envelope_json(tool, payload, verification=VerificationResult("verified", old_base.baselineId if old_base else None, new_base.baselineId, "Post-edit hash recorded."))


def apply_patch_handler(operations: list[dict[str, Any]]) -> str:
    tool = "apply_patch"
    if not isinstance(operations, list) or not operations:
        return error_envelope_json(tool, "patch_validation_failed", "Patch operations must be a non-empty list.", outcome=OUTCOME_REJECTED)
    unsafe = []
    for op in operations:
        decision = permission_for_path(str(op.get("path", "")), operation="mutate")
        if decision.decision == "denied":
            unsafe.append({"operationId": op.get("operationId"), "code": "path_outside_workspace"})
    if unsafe:
        return error_envelope_json(tool, "patch_validation_failed", "Patch rejected before mutation because at least one target is unsafe.", outcome=OUTCOME_REJECTED, payload={"rejected": unsafe})
    summaries = []
    for op in operations:
        typ = str(op.get("type"))
        path = str(op.get("path"))
        if typ == "add":
            result = json.loads(write_file_handler(path, str(op.get("content", ""))))
        elif typ == "update":
            if "replacements" in op:
                result = json.loads(edit_file_handler(path, str(op.get("expectedBaselineId", "")), list(op.get("replacements") or []), op.get("expectedSha256")))
            else:
                result = json.loads(write_file_handler(path, str(op.get("content", "")), op.get("expectedBaselineId"), op.get("expectedSha256")))
        elif typ == "delete":
            classified = classify_path(path)
            p = classified.resolved
            ok, code, old_base = _check_existing_baseline(p, op.get("expectedBaselineId"), op.get("expectedSha256")) if p.exists() else (False, "path_not_found", None)
            if not ok:
                result = json.loads(error_envelope_json(tool, code or "baseline_required", "Delete requires a current baseline.", outcome=OUTCOME_REJECTED))
            else:
                p.unlink()
                result = {"outcome": "success", "verification": {"oldBaseline": old_base.baselineId if old_base else None, "status": "verified"}}
        else:
            result = json.loads(error_envelope_json(tool, "patch_validation_failed", "Unknown patch operation.", outcome=OUTCOME_REJECTED))
        if result.get("outcome") != "success":
            return error_envelope_json(tool, "patch_validation_failed", "Patch rejected during validation or mutation.", outcome=OUTCOME_REJECTED, payload={"failedOperation": op.get("operationId"), "result": result})
        summaries.append({"operationId": op.get("operationId"), "type": typ, "path": path})
    return success_envelope_json(tool, {"affectedFiles": len(summaries), "changedFiles": summaries})
```

## Appendix A4: `src/business/agents/tools/search_tools.py`

```python
from __future__ import annotations

import base64
import fnmatch
import json
import re
import time
from pathlib import Path

from src.business.agents.tool_helpers import make_tool_schema
from src.business.agents.tools.builtin_contracts import OUTCOME_REJECTED, error_envelope_json, success_envelope_json
from src.business.agents.tools.builtin_permissions import classify_path, redact_fragment
from src.data.unified_config import get_unified_config


SEARCH_FILES_SCHEMA = make_tool_schema(
    name="search_files",
    description="Search file names with deterministic sorted bounded results, default ignore rules, and continuation metadata.",
    properties={"root": {"type": "string"}, "pattern": {"type": "string"}, "pageSize": {"type": "integer"}, "pageToken": {"type": "string"}, "includeHidden": {"type": "boolean"}},
    required=["pattern"],
)

SEARCH_CONTENT_SCHEMA = make_tool_schema(
    name="search_content",
    description="Search text content with literal or regex modes, grouped line matches, bounded context, redaction, and continuation metadata.",
    properties={"root": {"type": "string"}, "pattern": {"type": "string"}, "mode": {"type": "string"}, "includeGlobs": {"type": "array"}, "contextLines": {"type": "integer"}, "pageSize": {"type": "integer"}, "pageToken": {"type": "string"}},
    required=["pattern"],
)

IGNORED_DIRS = frozenset({".git", "node_modules", "__pycache__", "dist", "build", ".venv", "venv"})


def _cfg(name: str, default: int) -> int:
    getter = getattr(get_unified_config(), name, None)
    try:
        return int(getter()) if getter else default
    except Exception:
        return default


def _token(offset: int) -> str:
    return base64.urlsafe_b64encode(json.dumps({"offset": offset}).encode()).decode()


def _offset(token: str | None) -> int:
    if not token:
        return 0
    try:
        data = json.loads(base64.urlsafe_b64decode(token.encode()).decode())
        return max(0, int(data.get("offset", 0)))
    except Exception:
        return 0


def _iter_files(root: Path, include_hidden: bool, max_files: int):
    count = 0
    for path in root.rglob("*"):
        rel_parts = path.relative_to(root).parts
        if any(part in IGNORED_DIRS for part in rel_parts):
            continue
        if not include_hidden and any(part.startswith(".") for part in rel_parts):
            continue
        if path.is_file():
            count += 1
            if count > max_files:
                break
            yield path


def search_files_handler(root: str = ".", pattern: str = "*", pageSize: int | None = None, pageToken: str | None = None, includeHidden: bool = False) -> str:
    tool = "search_files"
    classified = classify_path(root)
    if classified.scope != "workspace":
        return error_envelope_json(tool, "path_outside_workspace", "Search root must stay inside the workspace.", outcome=OUTCOME_REJECTED)
    if not classified.resolved.is_dir():
        return error_envelope_json(tool, "path_not_directory", "Search root is not a directory.", outcome=OUTCOME_REJECTED)
    page_size = min(int(pageSize or _cfg("get_agent_tools_search_default_page_size", 100)), 500)
    offset = _offset(pageToken)
    files = sorted(_iter_files(classified.resolved, bool(includeHidden), _cfg("get_agent_tools_search_max_files_scanned", 50000)))
    matches = [p for p in files if fnmatch.fnmatch(p.name, pattern)]
    page = matches[offset : offset + page_size]
    payload = {"matches": [{"path": str(p.relative_to(classified.workspace_root)).replace("\\", "/"), "type": "file", "sizeBytes": p.stat().st_size} for p in page], "count": len(page), "hasMore": offset + page_size < len(matches), "nextPageToken": _token(offset + page_size) if offset + page_size < len(matches) else None, "ignoredDefaults": sorted(IGNORED_DIRS)}
    return success_envelope_json(tool, payload, limits={"pageSize": page_size, "hasMore": payload["hasMore"], "nextPageToken": payload["nextPageToken"]})


def _compile_pattern(pattern: str, mode: str):
    if mode == "regex":
        return re.compile(pattern)
    if mode == "literal":
        return re.compile(re.escape(pattern))
    raise ValueError("invalid search mode")


def search_content_handler(root: str = ".", pattern: str = "", mode: str = "literal", includeGlobs: list[str] | None = None, contextLines: int = 0, pageSize: int | None = None, pageToken: str | None = None) -> str:
    tool = "search_content"
    classified = classify_path(root)
    if classified.scope != "workspace":
        return error_envelope_json(tool, "path_outside_workspace", "Search root must stay inside the workspace.", outcome=OUTCOME_REJECTED)
    try:
        regex = _compile_pattern(pattern, mode)
    except re.error as exc:
        return error_envelope_json(tool, "search_pattern_invalid", f"Invalid regex: {exc}", outcome=OUTCOME_REJECTED)
    except ValueError:
        return error_envelope_json(tool, "search_pattern_invalid", "Search mode must be literal or regex.", outcome=OUTCOME_REJECTED)
    page_size = min(int(pageSize or _cfg("get_agent_tools_search_default_page_size", 100)), 500)
    offset = _offset(pageToken)
    max_bytes = _cfg("get_agent_tools_search_max_bytes_per_file", 1048576)
    deadline = time.monotonic() + (_cfg("get_agent_tools_search_max_elapsed_ms", 30000) / 1000)
    all_matches = []
    globs = includeGlobs or ["*"]
    for file_path in sorted(_iter_files(classified.resolved, False, _cfg("get_agent_tools_search_max_files_scanned", 50000))):
        if time.monotonic() > deadline:
            break
        rel = str(file_path.relative_to(classified.workspace_root)).replace("\\", "/")
        if not any(fnmatch.fnmatch(file_path.name, glob) or fnmatch.fnmatch(rel, glob) for glob in globs):
            continue
        raw = file_path.read_bytes()[:max_bytes]
        if b"\x00" in raw:
            continue
        text = raw.decode("utf-8", errors="replace")
        lines = text.splitlines()
        hits = []
        for index, line in enumerate(lines, start=1):
            if regex.search(line):
                before = [redact_fragment(v, 240) for v in lines[max(0, index - 1 - contextLines) : index - 1]]
                after = [redact_fragment(v, 240) for v in lines[index : index + contextLines]]
                hits.append({"line": index, "text": redact_fragment(line, 240), "before": before, "after": after})
        if hits:
            all_matches.append({"path": rel, "matches": hits})
    page = all_matches[offset : offset + page_size]
    has_more = offset + page_size < len(all_matches)
    payload = {"files": page, "matchCount": sum(len(file["matches"]) for file in page), "hasMore": has_more, "nextPageToken": _token(offset + page_size) if has_more else None}
    return success_envelope_json(tool, payload, limits={"pageSize": page_size, "hasMore": has_more, "nextPageToken": payload["nextPageToken"]})
```

## Appendix A5: `src/execution/command_runner.py`

```python
from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CommandResult:
    status: str
    exitCode: int | None
    stdout: str
    stderr: str
    durationMs: int
    timedOut: bool = False


def run_sync_command(command: str, cwd: Path, timeout_ms: int, stdout_cap: int = 12000, stderr_cap: int = 12000) -> CommandResult:
    start = time.monotonic()
    process = subprocess.Popen(
        command,
        shell=True,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        stdout, stderr = process.communicate(timeout=max(0.001, timeout_ms / 1000))
        status = "completed" if process.returncode == 0 else "failed"
        return CommandResult(status, process.returncode, stdout[:stdout_cap], stderr[:stderr_cap], int((time.monotonic() - start) * 1000))
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate()
        return CommandResult("timed_out", None, stdout[:stdout_cap], stderr[:stderr_cap], int((time.monotonic() - start) * 1000), True)
```

## Appendix A6: `src/execution/process_manager.py`

```python
from __future__ import annotations

import subprocess
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path


SESSION_EPOCH = uuid.uuid4().hex[:12]


@dataclass
class ProcessRecord:
    processId: str
    command: str
    commandSummary: str
    cwd: str
    process: subprocess.Popen
    duplicateKey: str
    stdinEnabled: bool = False
    status: str = "running"
    startedAt: float = field(default_factory=time.time)
    finishedAt: float | None = None
    exitCode: int | None = None
    stdout: deque[str] = field(default_factory=lambda: deque(maxlen=400))
    stderr: deque[str] = field(default_factory=lambda: deque(maxlen=400))

    def update_status(self) -> None:
        if self.status not in {"running"}:
            return
        code = self.process.poll()
        if code is not None:
            self.exitCode = code
            self.status = "completed" if code == 0 else "failed"
            self.finishedAt = time.time()


class ProcessManager:
    def __init__(self, max_processes: int = 16) -> None:
        self._records: dict[str, ProcessRecord] = {}
        self._lock = threading.RLock()
        self._max_processes = max_processes

    def _drain(self, record: ProcessRecord, stream_name: str) -> None:
        stream = getattr(record.process, stream_name)
        target = getattr(record, stream_name)
        if stream is None:
            return
        for line in iter(stream.readline, ""):
            target.append(line.rstrip("\n"))
        stream.close()

    def _duplicate_key(self, command: str, cwd: Path, session_id: str) -> str:
        return f"{session_id}:{cwd.resolve()}:{' '.join(command.split())}"

    def start(self, command: str, cwd: Path, session_id: str, stdin_enabled: bool = False) -> ProcessRecord:
        key = self._duplicate_key(command, cwd, session_id)
        with self._lock:
            for record in self._records.values():
                record.update_status()
                if record.duplicateKey == key and record.status == "running":
                    return record
            running = [record for record in self._records.values() if record.status == "running"]
            if len(running) >= self._max_processes:
                raise RuntimeError("maximum background process count reached")
            process_id = f"proc_{SESSION_EPOCH}_{uuid.uuid4().hex[:12]}"
            process = subprocess.Popen(
                command,
                shell=True,
                cwd=str(cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE if stdin_enabled else subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            record = ProcessRecord(process_id, command, command.splitlines()[0][:180], str(cwd), process, key, stdin_enabled)
            self._records[process_id] = record
            threading.Thread(target=self._drain, args=(record, "stdout"), daemon=True).start()
            threading.Thread(target=self._drain, args=(record, "stderr"), daemon=True).start()
            return record

    def get(self, process_id: str) -> ProcessRecord | None:
        if not process_id.startswith(f"proc_{SESSION_EPOCH}_"):
            return None
        with self._lock:
            record = self._records.get(process_id)
            if record is not None:
                record.update_status()
            return record

    def list(self, status: str | None = None) -> list[ProcessRecord]:
        with self._lock:
            records = list(self._records.values())
            for record in records:
                record.update_status()
            return [record for record in records if status is None or record.status == status]

    def logs(self, process_id: str, stream: str = "combined", tail_chars: int = 4000) -> str | None:
        record = self.get(process_id)
        if record is None:
            return None
        if stream == "stdout":
            text = "\n".join(record.stdout)
        elif stream == "stderr":
            text = "\n".join(record.stderr)
        else:
            text = "\n".join([*record.stdout, *record.stderr])
        return text[-tail_chars:]

    def wait(self, process_id: str, timeout_ms: int) -> ProcessRecord | None:
        record = self.get(process_id)
        if record is None:
            return None
        try:
            record.process.wait(timeout=max(0.001, timeout_ms / 1000))
        except subprocess.TimeoutExpired:
            pass
        record.update_status()
        return record

    def stop(self, process_id: str, force: bool = False) -> ProcessRecord | None:
        record = self.get(process_id)
        if record is None:
            return None
        if record.status == "running":
            if force:
                record.process.kill()
            else:
                record.process.terminate()
            try:
                record.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                record.process.kill()
            record.status = "terminated"
            record.finishedAt = time.time()
            record.exitCode = record.process.returncode
        return record

    def send_input(self, process_id: str, text: str) -> ProcessRecord | None:
        record = self.get(process_id)
        if record is None or not record.stdinEnabled or record.process.stdin is None:
            return None
        record.process.stdin.write(text[:4000])
        record.process.stdin.flush()
        return record

    def close(self, process_id: str) -> ProcessRecord | None:
        record = self.get(process_id)
        if record is None:
            return None
        record.update_status()
        if record.status == "running":
            return None
        record.status = "closed"
        return record


GLOBAL_PROCESS_MANAGER = ProcessManager()
```

## Appendix A7: `src/business/agents/tools/command_tools.py`

```python
from __future__ import annotations

import json

from src.business.agents.tool_helpers import make_tool_schema
from src.business.agents.tools.builtin_contracts import OUTCOME_REJECTED, OUTCOME_TIMEOUT, error_envelope_json, success_envelope_json
from src.business.agents.tools.builtin_permissions import classify_command_request, classify_path
from src.data.unified_config import get_unified_config
from src.execution.command_runner import run_sync_command
from src.execution.process_manager import GLOBAL_PROCESS_MANAGER, ProcessRecord


EXEC_SCHEMA = make_tool_schema("exec", "Run a workspace command with bounded output or start a managed background process.", {"command": {"type": "string"}, "cwd": {"type": "string"}, "timeoutMs": {"type": "integer"}, "mode": {"type": "string"}, "stdinEnabled": {"type": "boolean"}}, ["command"])
PROCESS_LIST_SCHEMA = make_tool_schema("process_list", "List current-session managed processes.", {"status": {"type": "string"}}, [])
PROCESS_POLL_SCHEMA = make_tool_schema("process_poll", "Poll a current-session managed process.", {"processId": {"type": "string"}}, ["processId"])
PROCESS_LOGS_SCHEMA = make_tool_schema("process_logs", "Read bounded recent process logs.", {"processId": {"type": "string"}, "stream": {"type": "string"}, "tailChars": {"type": "integer"}}, ["processId"])
PROCESS_WAIT_SCHEMA = make_tool_schema("process_wait", "Wait briefly for a managed process.", {"processId": {"type": "string"}, "timeoutMs": {"type": "integer"}}, ["processId"])
PROCESS_STOP_SCHEMA = make_tool_schema("process_stop", "Stop a managed process.", {"processId": {"type": "string"}, "force": {"type": "boolean"}}, ["processId"])
PROCESS_SEND_INPUT_SCHEMA = make_tool_schema("process_send_input", "Send bounded stdin to a process that enabled input.", {"processId": {"type": "string"}, "text": {"type": "string"}}, ["processId", "text"])
PROCESS_CLOSE_SCHEMA = make_tool_schema("process_close", "Close a completed or terminated process record.", {"processId": {"type": "string"}}, ["processId"])


def _cfg(name: str, default: int) -> int:
    getter = getattr(get_unified_config(), name, None)
    try:
        return int(getter()) if getter else default
    except Exception:
        return default


def _record_payload(record: ProcessRecord) -> dict:
    return {"processId": record.processId, "status": record.status, "commandSummary": record.commandSummary, "cwd": record.cwd, "exitCode": record.exitCode}


def exec_handler(command: str, cwd: str = ".", timeoutMs: int | None = None, mode: str = "sync", stdinEnabled: bool = False) -> str:
    tool = "exec"
    decision = classify_command_request(command, cwd)
    if decision.decision == "denied":
        return error_envelope_json(tool, "path_outside_workspace", "Command cwd must stay inside workspace.", outcome=OUTCOME_REJECTED, permission=decision)
    classified = classify_path(cwd or ".")
    timeout_ms = min(int(timeoutMs or _cfg("get_agent_tools_process_default_timeout_ms", 30000)), _cfg("get_agent_tools_process_max_timeout_ms", 600000))
    if mode == "background":
        try:
            record = GLOBAL_PROCESS_MANAGER.start(command, classified.resolved, "default", bool(stdinEnabled))
        except Exception as exc:
            return error_envelope_json(tool, "command_rejected", str(exc), outcome=OUTCOME_REJECTED)
        return success_envelope_json(tool, _record_payload(record), outcome="background_started", permission=decision)
    result = run_sync_command(command, classified.resolved, timeout_ms, _cfg("get_agent_tools_output_visible_char_cap", 12000), _cfg("get_agent_tools_output_visible_char_cap", 12000))
    payload = {"status": result.status, "exitCode": result.exitCode, "stdout": result.stdout, "stderr": result.stderr, "durationMs": result.durationMs}
    if result.timedOut:
        return error_envelope_json(tool, "command_timeout", "Command timed out.", outcome=OUTCOME_TIMEOUT, payload=payload, permission=decision)
    return success_envelope_json(tool, payload, permission=decision, limits={"truncated": False})


def process_list_handler(status: str | None = None) -> str:
    return success_envelope_json("process_list", {"processes": [_record_payload(r) for r in GLOBAL_PROCESS_MANAGER.list(status)]})


def process_poll_handler(processId: str) -> str:
    record = GLOBAL_PROCESS_MANAGER.get(processId)
    if record is None:
        return error_envelope_json("process_poll", "process_unavailable_after_restart", "Process record is unavailable in this sidecar session.", outcome=OUTCOME_REJECTED)
    return success_envelope_json("process_poll", _record_payload(record))


def process_logs_handler(processId: str, stream: str = "combined", tailChars: int | None = None) -> str:
    text = GLOBAL_PROCESS_MANAGER.logs(processId, stream, int(tailChars or _cfg("get_agent_tools_process_log_tail_chars", 4000)))
    if text is None:
        return error_envelope_json("process_logs", "process_not_found", "Process record was not found.", outcome=OUTCOME_REJECTED)
    return success_envelope_json("process_logs", {"processId": processId, "stream": stream, "logTail": text})


def process_wait_handler(processId: str, timeoutMs: int = 30000) -> str:
    record = GLOBAL_PROCESS_MANAGER.wait(processId, timeoutMs)
    if record is None:
        return error_envelope_json("process_wait", "process_not_found", "Process record was not found.", outcome=OUTCOME_REJECTED)
    return success_envelope_json("process_wait", _record_payload(record))


def process_stop_handler(processId: str, force: bool = False) -> str:
    record = GLOBAL_PROCESS_MANAGER.stop(processId, bool(force))
    if record is None:
        return error_envelope_json("process_stop", "process_not_found", "Process record was not found.", outcome=OUTCOME_REJECTED)
    return success_envelope_json("process_stop", _record_payload(record))


def process_send_input_handler(processId: str, text: str) -> str:
    record = GLOBAL_PROCESS_MANAGER.send_input(processId, text)
    if record is None:
        return error_envelope_json("process_send_input", "permission_denied", "Process input is unavailable.", outcome=OUTCOME_REJECTED)
    return success_envelope_json("process_send_input", _record_payload(record))


def process_close_handler(processId: str) -> str:
    record = GLOBAL_PROCESS_MANAGER.close(processId)
    if record is None:
        return error_envelope_json("process_close", "process_not_found", "Process record was not found or still running.", outcome=OUTCOME_REJECTED)
    return success_envelope_json("process_close", _record_payload(record))
```

## Appendix A8: `src/business/agents/tools/output_governance.py`

```python
from __future__ import annotations

import json
from dataclasses import dataclass

from src.business.agents.tool_helpers import make_tool_schema
from src.business.agents.tools.builtin_contracts import ToolOutputReference, error_envelope_json, is_envelope_json, standardized_error_to_envelope, success_envelope_json
from src.business.agents.tools.builtin_permissions import redact_fragment


LOAD_TOOL_OUTPUT_SCHEMA = make_tool_schema("load_tool_output", "Load a bounded redacted window from an authorized raw-output reference.", {"referenceId": {"type": "string"}, "offset": {"type": "integer"}, "maxBytes": {"type": "integer"}, "renderAs": {"type": "string"}}, ["referenceId"])


@dataclass
class OutputHealth:
    compacted: int = 0
    fallback: int = 0
    raw_reference_failures: int = 0
    raw_reference_load_failures: int = 0


HEALTH = OutputHealth()


def _visible_cap(config) -> int:
    getter = getattr(config, "get_agent_tools_output_visible_char_cap", None)
    return int(getter()) if getter else 12000


def _threshold(config) -> int:
    getter = getattr(config, "get_agent_tools_output_raw_reference_threshold_chars", None)
    return int(getter()) if getter else 20000


def _safe_json(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def govern_tool_result(tool_name: str, tool_call_id: str, session_id: str, content: str, config) -> str:
    if is_envelope_json(content):
        data = json.loads(content)
    else:
        return standardized_error_to_envelope(tool_name, content)
    rendered = _safe_json(data)
    if len(rendered) <= _visible_cap(config):
        return rendered
    try:
        from src.data.repos.tool_output_repository import ToolOutputRepository

        repo = ToolOutputRepository()
        reference = repo.create(
            session_id=session_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            kind="tool_payload",
            content=rendered.encode("utf-8"),
            content_type="application/json",
        )
        HEALTH.compacted += 1
        data["payload"] = {"summary": redact_fragment(rendered, _visible_cap(config))}
        data["references"] = [
            {
                "referenceId": reference.reference_id,
                "kind": reference.kind,
                "sizeBytes": reference.size_bytes,
                "contentType": reference.content_type,
                "sha256": reference.sha256,
                "expiresAt": reference.expires_at.isoformat() if reference.expires_at else None,
            }
        ]
        data["warnings"] = list(data.get("warnings") or []) + ["visible result compacted; use load_tool_output for authorized raw output"]
        return _safe_json(data)
    except Exception:
        HEALTH.fallback += 1
        HEALTH.raw_reference_failures += 1
        return error_envelope_json(tool_name, "compaction_failed_fallback", "Result was oversized and raw-reference creation failed.", payload={"visible": redact_fragment(rendered, _visible_cap(config))})


def load_tool_output_handler(referenceId: str, offset: int = 0, maxBytes: int = 64000, renderAs: str = "text") -> str:
    tool = "load_tool_output"
    try:
        from src.data.repos.tool_output_repository import ToolOutputRepository

        repo = ToolOutputRepository()
        record = repo.get_authorized(referenceId, session_id=None)
        if record is None:
            HEALTH.raw_reference_load_failures += 1
            return error_envelope_json(tool, "output_reference_not_found", "Output reference was not found.")
        if record.status != "active":
            HEALTH.raw_reference_load_failures += 1
            return error_envelope_json(tool, "output_reference_expired", "Output reference is no longer active.")
        data = repo.read_bytes(record)
    except Exception:
        HEALTH.raw_reference_load_failures += 1
        return error_envelope_json(tool, "output_reference_not_found", "Output reference could not be loaded.")
    start = max(0, int(offset or 0))
    limit = max(1, min(int(maxBytes or 64000), 64000))
    window = data[start : start + limit]
    if renderAs != "text":
        return error_envelope_json(tool, "unsupported_binary", "Only bounded text rendering is supported for raw-output references.")
    text = window.decode("utf-8", errors="replace")
    payload = {"referenceId": referenceId, "offset": start, "bytesReturned": len(window), "hasMore": start + len(window) < len(data), "content": redact_fragment(text, limit)}
    return success_envelope_json(tool, payload, limits={"hasMore": payload["hasMore"]})


def cleanup_expired_outputs() -> dict:
    from src.data.repos.tool_output_repository import ToolOutputRepository

    return ToolOutputRepository().cleanup_expired()
```

## Appendix A9: `src/data/repos/tool_output_repository.py`

```python
from __future__ import annotations

import hashlib
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.data.models_sqlite import ToolOutputReferenceRecord
from src.data.repos.base_repository import BaseRepository
from src.utils.helpers import get_default_data_dir


@dataclass(frozen=True)
class ToolOutputReferenceRow:
    reference_id: str
    kind: str
    tool_name: str
    session_id: str
    tool_call_id: str | None
    storage_key: str
    size_bytes: int
    content_type: str
    sha256: str
    status: str
    expires_at: datetime | None


class ToolOutputRepository(BaseRepository):
    def _root(self) -> Path:
        root = get_default_data_dir() / "tool_outputs"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _row(self, model: ToolOutputReferenceRecord) -> ToolOutputReferenceRow:
        return ToolOutputReferenceRow(model.reference_id, model.kind, model.tool_name, model.session_id, model.tool_call_id, model.storage_key, model.size_bytes, model.content_type, model.sha256, model.status, model.expires_at)

    def create(self, *, session_id: str, tool_call_id: str | None, tool_name: str, kind: str, content: bytes, content_type: str = "text/plain", retention_days: int = 14) -> ToolOutputReferenceRow:
        digest = hashlib.sha256(content).hexdigest()
        reference_id = f"out_{uuid.uuid4().hex}"
        storage_key = f"{reference_id}.blob"
        temp_path = self._root() / f"{reference_id}.tmp"
        final_path = self._root() / storage_key
        temp_path.write_bytes(content)
        os.replace(temp_path, final_path)
        model = ToolOutputReferenceRecord(
            reference_id=reference_id,
            kind=kind,
            tool_name=tool_name,
            session_id=session_id,
            tool_call_id=tool_call_id,
            storage_key=storage_key,
            storage_root_kind="tool_outputs",
            size_bytes=len(content),
            content_type=content_type,
            sha256=digest,
            owner_workspace_hash=hashlib.sha256(str(Path.cwd().resolve()).encode("utf-8")).hexdigest(),
            redaction_profile="standard",
            status="active",
            expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=retention_days),
        )
        self.session.add(model)
        self.session.commit()
        self.session.refresh(model)
        return self._row(model)

    def get_authorized(self, reference_id: str, session_id: str | None = None) -> ToolOutputReferenceRow | None:
        model = self.session.get(ToolOutputReferenceRecord, reference_id)
        if model is None:
            return None
        if session_id is not None and model.session_id != session_id:
            return None
        return self._row(model)

    def read_bytes(self, row: ToolOutputReferenceRow) -> bytes:
        path = self._root() / row.storage_key
        if not path.exists():
            raise FileNotFoundError("tool output blob missing")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != row.sha256:
            raise ValueError("tool output blob hash mismatch")
        return data

    def mark_expired(self, reference_id: str) -> bool:
        model = self.session.get(ToolOutputReferenceRecord, reference_id)
        if model is None:
            return False
        model.status = "expired"
        self.session.commit()
        return True

    def mark_deleted(self, reference_id: str) -> bool:
        model = self.session.get(ToolOutputReferenceRecord, reference_id)
        if model is None:
            return False
        model.status = "deleted"
        model.deleted_at = datetime.now(timezone.utc).replace(tzinfo=None)
        path = self._root() / model.storage_key
        if path.exists():
            path.unlink()
        self.session.commit()
        return True

    def cleanup_expired(self) -> dict:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        expired = self.session.query(ToolOutputReferenceRecord).filter(ToolOutputReferenceRecord.status == "active", ToolOutputReferenceRecord.expires_at.isnot(None), ToolOutputReferenceRecord.expires_at <= now).all()
        removed_blobs = 0
        for model in expired:
            model.status = "expired"
            path = self._root() / model.storage_key
            if path.exists():
                path.unlink()
                removed_blobs += 1
        self.session.commit()
        return {"expiredMetadata": len(expired), "removedBlobs": removed_blobs}
```

## Appendix B: Test Content

Use these files as complete starting points and expand only when new edge cases are found during implementation.

### Appendix B1: `tests/business/agents/test_builtin_file_tools.py`

```python
import json

from src.business.agents.tools.file_tools import apply_patch_handler, edit_file_handler, read_file_handler, write_file_handler


def _load(result: str) -> dict:
    return json.loads(result)


def test_read_file_returns_window_baseline_and_repeat_metadata(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "sample.txt"
    path.write_text("\n".join(f"line {i}" for i in range(1, 260)), encoding="utf-8")

    first = _load(read_file_handler("sample.txt", startLine=1, maxLines=10))
    second = _load(read_file_handler("sample.txt", startLine=1, maxLines=10))

    assert first["schemaVersion"] == 1
    assert first["outcome"] == "success"
    assert first["payload"]["lineStart"] == 1
    assert first["payload"]["lineEnd"] == 10
    assert first["payload"]["hasMoreAfter"] is True
    assert first["payload"]["baseline"]["baselineId"].startswith("base_")
    assert second["payload"]["repeatRead"]["seenCount"] >= 2


def test_read_file_refuses_binary_and_redacts_secret(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "image.png").write_bytes(b"\x89PNG\x00binary")
    secret = tmp_path / "secret.txt"
    secret.write_text("api_key=real-looking-value\nkeep=this", encoding="utf-8")

    binary = _load(read_file_handler("image.png"))
    text = _load(read_file_handler("secret.txt"))

    assert binary["outcome"] == "unsupported"
    assert "binary" not in json.dumps(binary).lower()
    assert "[redacted]" in text["payload"]["content"]
    assert "real-looking-value" not in text["payload"]["content"]


def test_write_file_requires_current_baseline_for_existing_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "doc.txt"
    target.write_text("old", encoding="utf-8")
    read = _load(read_file_handler("doc.txt"))
    baseline = read["payload"]["baseline"]["baselineId"]

    missing = _load(write_file_handler("doc.txt", "new"))
    ok = _load(write_file_handler("doc.txt", "new", expectedBaselineId=baseline))
    stale = _load(write_file_handler("doc.txt", "again", expectedBaselineId=baseline))

    assert missing["error"]["code"] == "baseline_required"
    assert ok["outcome"] == "success"
    assert stale["error"]["code"] == "baseline_stale"
    assert target.read_text(encoding="utf-8") == "new"


def test_edit_file_replacements_and_ambiguity(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    target = tmp_path / "edit.txt"
    target.write_text("alpha\nbeta\n", encoding="utf-8")
    baseline = _load(read_file_handler("edit.txt"))["payload"]["baseline"]["baselineId"]

    ok = _load(edit_file_handler("edit.txt", baseline, [{"oldText": "beta", "newText": "gamma"}]))
    new_baseline = ok["verification"]["newBaseline"]
    target.write_text("same\nsame\n", encoding="utf-8")
    ambiguous = _load(edit_file_handler("edit.txt", new_baseline, [{"oldText": "same", "newText": "once"}]))

    assert ok["outcome"] == "success"
    assert target.read_text(encoding="utf-8") == "same\nsame\n"
    assert ambiguous["error"]["code"] in {"baseline_stale", "edit_target_not_unique"}


def test_apply_patch_all_or_rejects_unsafe_targets(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = _load(apply_patch_handler([{"operationId": "op1", "type": "add", "path": "../outside.txt", "content": "bad"}]))

    assert result["outcome"] == "error" or result["outcome"] == "rejected"
    assert not (tmp_path.parent / "outside.txt").exists()
```

### Appendix B2: `tests/business/agents/test_builtin_search_tools.py`

```python
import json

from src.business.agents.tools.search_tools import search_content_handler, search_files_handler


def _load(result: str) -> dict:
    return json.loads(result)


def test_search_files_is_sorted_bounded_and_ignores_defaults(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "ignored.py").write_text("x", encoding="utf-8")
    (tmp_path / "b.py").write_text("x", encoding="utf-8")
    (tmp_path / "a.py").write_text("x", encoding="utf-8")

    result = _load(search_files_handler(".", "*.py", pageSize=1))

    assert result["payload"]["count"] == 1
    assert result["payload"]["matches"][0]["path"] == "a.py"
    assert result["payload"]["hasMore"] is True


def test_search_content_groups_matches_and_redacts(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "a.txt").write_text("token=secret\nneedle line\n", encoding="utf-8")

    result = _load(search_content_handler(".", "needle", mode="literal", includeGlobs=["*.txt"], contextLines=1))

    assert result["outcome"] == "success"
    assert result["payload"]["files"][0]["path"] == "a.txt"
    assert result["payload"]["files"][0]["matches"][0]["line"] == 2
    assert "secret" not in json.dumps(result)
```

### Appendix B3: `tests/business/agents/test_builtin_command_tools.py`

```python
import json
import sys

from src.business.agents.tools.command_tools import exec_handler


def _load(result: str) -> dict:
    return json.loads(result)


def test_exec_success_and_timeout(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ok = _load(exec_handler(f"{sys.executable} --version", cwd=".", timeoutMs=10000))
    timeout = _load(exec_handler(f"{sys.executable} -c \"import time; time.sleep(2)\"", cwd=".", timeoutMs=100))

    assert ok["payload"]["status"] in {"completed", "failed"}
    assert timeout["error"]["code"] == "command_timeout"
```

### Appendix B4: `tests/business/agents/test_builtin_output_governance.py`

```python
import json

from src.business.agents.tools.builtin_contracts import success_envelope_json
from src.business.agents.tools.output_governance import govern_tool_result


class SmallConfig:
    def get_agent_tools_output_visible_char_cap(self):
        return 100

    def get_agent_tools_output_raw_reference_threshold_chars(self):
        return 120


def test_governance_preserves_small_envelope():
    content = success_envelope_json("read_file", {"content": "small"})
    result = json.loads(govern_tool_result("read_file", "call", "session", content, SmallConfig()))

    assert result["schemaVersion"] == 1
    assert result["payload"]["content"] == "small"


def test_governance_fallback_is_single_safe_envelope(monkeypatch):
    content = success_envelope_json("exec", {"stdout": "x" * 1000})
    result = json.loads(govern_tool_result("exec", "call", "session", content, SmallConfig()))

    assert result["schemaVersion"] == 1
    assert "x" * 500 not in json.dumps(result)
```

### Appendix B5: `tests/data/test_tool_output_repository.py`

```python
from src.data.repos.tool_output_repository import ToolOutputRepository
from src.data.unified_config import UnifiedConfigManager


def test_tool_output_repository_create_authorize_read_and_delete(in_memory_db, tmp_path, monkeypatch):
    monkeypatch.setenv("EXEMPLAR_DATA_DIR", str(tmp_path))
    repo = ToolOutputRepository()

    row = repo.create(session_id="s1", tool_call_id="c1", tool_name="exec", kind="stdout", content=b"hello")

    assert row.reference_id.startswith("out_")
    assert repo.get_authorized(row.reference_id, "s1") is not None
    assert repo.get_authorized(row.reference_id, "other") is None
    assert repo.read_bytes(row) == b"hello"
    assert repo.mark_deleted(row.reference_id) is True


def test_unified_config_agent_tool_defaults(mock_config):
    assert UnifiedConfigManager.get_agent_tools_file_default_max_lines
    assert UnifiedConfigManager.get_agent_tools_output_visible_char_cap
    assert UnifiedConfigManager.get_agent_tools_search_default_page_size
    assert UnifiedConfigManager.get_agent_tools_process_default_timeout_ms
```

### Appendix B6: `tests/integration/test_agent_builtin_tool_contracts.py`

```python
import json

from src.business.agents.agent_loop import AgentLoop
from src.business.agents.config import AgentConfig, AgentType, ResultType, ToolDefinition
from src.business.ai.llm_client import LLMResponse, ToolCallInfo
from tests.conftest import MockLLMClient


def _schema(name: str) -> dict:
    return {"type": "function", "function": {"name": name, "description": name, "parameters": {"type": "object", "properties": {}, "required": []}}}


def test_envelope_error_codes_are_stable():
    from src.business.agents.tools.builtin_contracts import ERROR_CODES

    assert {"baseline_required", "baseline_stale", "command_timeout", "output_reference_expired"}.issubset(ERROR_CODES)


def test_agent_loop_unknown_tool_gets_one_envelope_result(mock_config, in_memory_db):
    responses = [
        LLMResponse(content=None, tool_calls=[ToolCallInfo(id="c1", name="read_file", args={"path": "missing"})]),
        LLMResponse(content="done", tool_calls=[]),
    ]
    loop = AgentLoop(AgentConfig(AgentType.PM, "system", max_iterations=5), MockLLMClient(responses), mock_config)
    result = loop.run("builtin-contract-one", user_input="go", tools=[])

    assert result.result_type == ResultType.COMPLETED
    messages = loop._get_context_manager("builtin-contract-one")._msg_repo.get_context("builtin-contract-one")
    tool_results = [m for m in messages if m.role == "tool"]
    assert len(tool_results) == 1
    payload = json.loads(tool_results[0].content)
    assert payload["schemaVersion"] == 1
    assert payload["error"]["code"] == "unknown_tool"


def test_agent_loop_pre_hook_rejection_gets_one_result(mock_config, in_memory_db):
    tool = ToolDefinition(name="write_file", schema=_schema("write_file"), handler=lambda: "bad", pre_hook=lambda ctx: __import__("src.business.agents.hook_models", fromlist=["PreHookResult"]).PreHookResult(error="blocked"))
    responses = [
        LLMResponse(content=None, tool_calls=[ToolCallInfo(id="c1", name="write_file", args={})]),
        LLMResponse(content="done", tool_calls=[]),
    ]
    loop = AgentLoop(AgentConfig(AgentType.PM, "system", max_iterations=5), MockLLMClient(responses), mock_config)
    loop.run("builtin-contract-prehook", user_input="go", tools=[tool])
    messages = loop._get_context_manager("builtin-contract-prehook")._msg_repo.get_context("builtin-contract-prehook")
    tool_results = [m for m in messages if m.role == "tool"]
    assert len(tool_results) == 1
    assert json.loads(tool_results[0].content)["error"]["code"] == "pre_hook_rejected"
```

### Appendix B7: `tests/integration/test_agent_builtin_process_lifecycle.py`

```python
import json
import sys

from src.business.agents.tools.command_tools import exec_handler, process_close_handler, process_logs_handler, process_poll_handler, process_stop_handler


def _load(result: str) -> dict:
    return json.loads(result)


def test_background_process_lifecycle(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    started = _load(exec_handler(f"{sys.executable} -c \"import time; print('ready'); time.sleep(5)\"", cwd=".", mode="background"))
    process_id = started["payload"]["processId"]

    poll = _load(process_poll_handler(process_id))
    logs = _load(process_logs_handler(process_id))
    stopped = _load(process_stop_handler(process_id, force=True))
    closed = _load(process_close_handler(process_id))

    assert started["outcome"] == "background_started"
    assert poll["payload"]["processId"] == process_id
    assert logs["payload"]["processId"] == process_id
    assert stopped["payload"]["status"] in {"terminated", "completed", "failed"}
    assert closed["payload"]["status"] == "closed"
```

### Appendix B8: `tests/guardrails/test_agent_builtin_tool_boundaries.py`

```python
import inspect
import json

from src.business.agents.tools import builtin_general_tools
from src.business.agents.tools.builtin_permissions import build_command_confirmation_summary, build_mutation_confirmation_summary, classify_command_request, classify_path


def test_workspace_policy_denies_external_mutation(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    external = tmp_path / "external.txt"
    workspace.mkdir()
    monkeypatch.chdir(workspace)

    read = classify_path(str(external))
    command = classify_command_request("python -c 1", cwd=str(tmp_path))

    assert read.scope == "external"
    assert command.decision == "denied"


def test_confirmation_summaries_do_not_leak_content():
    write_summary = build_mutation_confirmation_summary("file.txt", "replace", "base_1234567890", str(__import__("pathlib").Path.cwd()))
    command_summary = build_command_confirmation_summary("python -c \"print('secret=abc')\"\nrm -rf x")

    assert "secret=abc" not in command_summary
    assert "\n" not in command_summary
    assert "base_1234567890"[:8] in write_summary


def test_builtin_general_tools_mount_upgraded_contracts():
    tools = {tool.name: tool for tool in builtin_general_tools.BUILTIN_GENERAL_TOOLS}

    for name in {"read_file", "write_file", "edit_file", "apply_patch", "search_files", "search_content", "exec", "load_tool_output"}:
        assert name in tools
        assert tools[name].schema["function"]["parameters"]["type"] == "object"


def test_no_legacy_builtin_contract_shapes_remain():
    source = inspect.getsource(builtin_general_tools)

    assert "old_text" not in source
    assert "max_bytes" not in source
    assert "returncode" not in source
```

## Checklist

- [ ] T001: Create shared built-in contract module skeleton in `src/business/agents/tools/builtin_contracts.py`
- [ ] T002: Create workspace permission module skeleton in `src/business/agents/tools/builtin_permissions.py`
- [ ] T003: Create focused built-in tool module skeletons
- [ ] T004: Create execution boundary module skeletons
- [ ] T005: Create focused test files
- [ ] T006: Add JSON-schema and stable error-code tests
- [ ] T007: Add unified configuration getter/default validation tests
- [ ] T008: Add workspace path classification and confirmation-summary safety tests
- [ ] T009: Add AgentLoop exactly-one-result tests
- [ ] T010: Implement common built-in contracts
- [ ] T011: Implement workspace resolution and policy
- [ ] T012: Add agent tool config dataclasses
- [ ] T013: Add typed getters and validation
- [ ] T014: Update config defaults
- [ ] T015: Implement AgentLoop governed persistence wrapper
- [ ] T016: Route save call sites through the wrapper
- [ ] T017: Update built-in general facade
- [ ] T018: Add layer and SQL boundary guards
- [ ] T019: Add read-file window tests
- [ ] T020: Add binary/media tests
- [ ] T021: Add outside-workspace read integration tests
- [ ] T022: Add read leak guard tests
- [ ] T023: Implement file baseline helpers
- [ ] T024: Implement bounded read rendering
- [ ] T025: Implement binary, decode, redaction, and repeat-read behavior
- [ ] T026: Apply workspace read policy
- [ ] T027: Replace `read_file` facade wiring
- [ ] T028: Update `read_file` description
- [ ] T029: Run US1 tests
- [ ] T030: Add write-file tests
- [ ] T031: Add edit-file tests
- [ ] T032: Add stale mutation pairing tests
- [ ] T033: Add write/edit summary leak tests
- [ ] T034: Implement baseline-aware `write_file`
- [ ] T035: Implement targeted `edit_file`
- [ ] T036: Add file mutation serialization
- [ ] T037: Apply mutation policy and summaries
- [ ] T038: Replace write/edit facade wiring
- [ ] T039: Update hook protocol tests
- [ ] T040: Run US2 tests
- [ ] T041: Add `search_files` tests
- [ ] T042: Add `search_content` tests
- [ ] T043: Add `apply_patch` tests
- [ ] T044: Add search/patch guard tests
- [ ] T045: Implement file traversal
- [ ] T046: Implement content search
- [ ] T047: Implement patch validation
- [ ] T048: Implement patch mutation
- [ ] T049: Apply search and patch policy
- [ ] T050: Register search and patch tools
- [ ] T051: Update search and patch descriptions
- [ ] T052: Run US3 tests
- [ ] T053: Add `exec` tests
- [ ] T054: Add process lifecycle tests
- [ ] T055: Add command/process guard tests
- [ ] T056: Implement command runner
- [ ] T057: Implement process registry
- [ ] T058: Implement duplicate process detection
- [ ] T059: Implement process stop, stdin, close, and restart behavior
- [ ] T060: Implement command/process handlers
- [ ] T061: Apply command policy and summaries
- [ ] T062: Register command/process tools
- [ ] T063: Update `exec` test assumptions
- [ ] T064: Run US4 tests
- [ ] T065: Add output governance tests
- [ ] T066: Add repository tests
- [ ] T067: Add oversized output and recovery tests
- [ ] T068: Add raw artifact leak tests
- [ ] T069: Add ORM model
- [ ] T070: Add v13 migration
- [ ] T071: Implement repository APIs
- [ ] T072: Implement blob storage and cleanup
- [ ] T073: Implement output governance
- [ ] T074: Extend AgentLoop wrapper for governance
- [ ] T075: Implement `load_tool_output`
- [ ] T076: Register `load_tool_output`
- [ ] T077: Add cleanup entrypoints and health counters
- [ ] T078: Run US5 tests
- [ ] T079: Update project constraints
- [ ] T080: Update architecture notes
- [ ] T081: Update root mirrored AI entry docs
- [ ] T082: Update backend mirrored AI entry docs
- [ ] T083: Remove legacy compatibility assumptions
- [ ] T084: Add no-legacy-contract guard
- [ ] T085: Run focused quickstart tests
- [ ] T086: Run broad regression and formatting
