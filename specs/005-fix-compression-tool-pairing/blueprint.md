# Blueprint: 修复上下文压缩 tool_call/tool_result 配对断裂

**Branch**: `005-fix-compression-tool-pairing` | **Date**: 2026-04-27
**Mode**: `doc-only`
**Total Tasks**: 15 | **Files**: 4 new, 4 modified, 0 deleted

## Key Decisions

- 在 `CompressionHandler._split_messages()` 内先识别 `keep_msgs` 中已暴露的 `tool_call_id`，再从压缩区末尾反向定位唯一跨界 tool 组，整组前移到保留区，而不是依赖摘要后处理兜底修复配对关系 → T004, T005
- 边界调整后若压缩区为空，`compress()` 直接返回 `system + keep_msgs`，不创建 `compressed` 消息也不归档原消息，保持 `compress()` 返回结构兼容且持久化语义与规格一致 → T006, T008
- 孤立 `tool` 消息的清理放在 `assemble_context()` 压缩后、引用替换前；`get_pending_tool_calls()` 继续只负责未配对 `assistant(tool_calls)` 的恢复，不把两类问题混在同一条路径里 → T009, T010, T011
- 活文档只更新 `docs/ARCHITECTURE.md` 与 `CLAUDE.md`，同步当前运行时的压缩边界与恢复行为，不改 `constitution` 与 `PROJECT_CONSTRAINTS` → T012, T013

## Implementation Order

```text
T001 -> T002

T002 -> T003 -> T004 -> T005 -> T006 -> T007 -> T008

T002 -> T009 -> T010 -> T011

T006,T008,T011 -> T012,T013

T012,T013 -> T014 -> T015
```

---

## Phase 1: Setup

### T001: 创建测试目录 `tests/business/memory/` 并添加 `__init__.py`

**File**: `tests/business/memory/__init__.py` (new)

**Requirements**: FR-001, FR-002, FR-003, FR-004, FR-005

**Dependencies**: None

```python
"""business.memory 相关测试。"""
```

**Verification**: `pytest` 能发现 `tests/business/memory/` 包，且后续 fixture 与测试模块可以直接放在该目录下。

---

### T002: 在 `tests/business/memory/conftest.py` 中创建共享 fixture：mock Message 工厂函数和 mock MessageRepository

**File**: `tests/business/memory/conftest.py` (new)

**Requirements**: FR-001, FR-002, FR-003, FR-004, FR-005

**Dependencies**: T001

```python
import json
from unittest.mock import MagicMock

import pytest

from src.data.models_sqlite import Message
from src.data.repos.message_repository import MessageRepository


@pytest.fixture
def message_factory():
    def _make_message(
        *,
        sequence: int,
        role: str,
        content: str | None = "",
        session_id: str = "session-1",
        message_id: str | None = None,
        tool_call_id: str | None = None,
        tool_name: str | None = None,
        tool_calls: list[dict] | str | None = None,
        message_type: str = "normal",
        compressed_range: str | None = None,
        is_archived: bool = False,
    ) -> Message:
        serialized_tool_calls = (
            json.dumps(tool_calls, ensure_ascii=False)
            if isinstance(tool_calls, list)
            else tool_calls
        )
        return Message(
            message_id=message_id or f"msg-{sequence}",
            session_id=session_id,
            sequence=sequence,
            role=role,
            content=content,
            message_type=message_type,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            tool_calls=serialized_tool_calls,
            compressed_range=compressed_range,
            is_archived=is_archived,
        )

    return _make_message


@pytest.fixture
def message_repo_mock():
    repo = MagicMock(spec=MessageRepository)
    repo.get_context.return_value = []
    repo.get_next_sequence.return_value = 1
    repo.get_last.return_value = None
    repo.get_by_id.return_value = None
    repo.create.side_effect = lambda model: model
    repo.mark_archived.return_value = None
    return repo
```

**Verification**: 新测试文件可以直接复用 `message_factory` 构造 `Message`，并通过 `message_repo_mock` 控制 `get_context/create/mark_archived` 行为。

---

## Phase 2: User Story 1 - 长会话压缩后 Agent 不再崩溃

### T003: 在 `tests/business/memory/test_compression_tool_pairing.py` 编写边界调整测试：test_no_tool_groups_in_compress、test_tool_group_fully_in_compress、test_tool_group_straddles_boundary

**File**: `tests/business/memory/test_compression_tool_pairing.py` (new)

**Requirements**: FR-001, FR-002, FR-003

**Dependencies**: T002

```python
import pytest

from src.business.memory.compression_handler import CompressionHandler


def _tool_call(tool_id: str, name: str, args: dict | None = None) -> dict:
    return {"id": tool_id, "name": name, "args": args or {}}


def _sequences(messages) -> list[int]:
    return [msg.sequence for msg in messages]


@pytest.fixture
def handler(mock_config):
    mock_config.get_memory_compression_keep_recent.return_value = 2
    return CompressionHandler(mock_config)


def test_no_tool_groups_in_compress(handler, message_factory):
    messages = [
        message_factory(sequence=1, role="user", content="old-user"),
        message_factory(sequence=2, role="assistant", content="old-assistant"),
        message_factory(sequence=3, role="user", content="keep-user"),
        message_factory(sequence=4, role="assistant", content="keep-assistant"),
    ]

    system_msg, compress_msgs, keep_msgs = handler._split_messages(messages)

    assert system_msg is None
    assert _sequences(compress_msgs) == [1, 2]
    assert _sequences(keep_msgs) == [3, 4]


def test_tool_group_fully_in_compress(handler, message_factory):
    messages = [
        message_factory(
            sequence=1,
            role="assistant",
            content=None,
            tool_calls=[_tool_call("call-1", "read_file")],
        ),
        message_factory(
            sequence=2,
            role="tool",
            content="tool-result",
            tool_call_id="call-1",
            tool_name="read_file",
        ),
        message_factory(sequence=3, role="assistant", content="analysis"),
        message_factory(sequence=4, role="user", content="follow-up"),
        message_factory(sequence=5, role="assistant", content="keep-1"),
        message_factory(sequence=6, role="user", content="keep-2"),
    ]

    _, compress_msgs, keep_msgs = handler._split_messages(messages)

    assert _sequences(compress_msgs) == [1, 2, 3, 4]
    assert _sequences(keep_msgs) == [5, 6]


def test_tool_group_straddles_boundary(handler, message_factory):
    messages = [
        message_factory(sequence=1, role="user", content="very-old"),
        message_factory(
            sequence=2,
            role="assistant",
            content=None,
            tool_calls=[
                _tool_call("call-1", "query_data"),
                _tool_call("call-2", "read_file"),
            ],
        ),
        message_factory(
            sequence=3,
            role="tool",
            content="query-result",
            tool_call_id="call-1",
            tool_name="query_data",
        ),
        message_factory(
            sequence=4,
            role="tool",
            content="file-result",
            tool_call_id="call-2",
            tool_name="read_file",
        ),
        message_factory(sequence=5, role="assistant", content="latest"),
    ]

    _, compress_msgs, keep_msgs = handler._split_messages(messages)

    assert _sequences(compress_msgs) == [1]
    assert _sequences(keep_msgs) == [2, 3, 4, 5]
```

**Verification**: 运行该文件时，三个测试分别覆盖“无工具组”“完整位于压缩区”“跨越边界整组保留”三条基础路径。

---

### T004: 在 `src/business/memory/compression_handler.py` 新增 `_adjust_boundary_for_tool_pairs(self, compress_msgs: List[Message], keep_msgs: List[Message]) -> Tuple[List[Message], List[Message]]`

**File**: `src/business/memory/compression_handler.py` (modify)

**Requirements**: FR-001, FR-002

**Dependencies**: T003

**Before** (line 321):

```python
        compress_msgs = messages[start_idx:compress_start]
        keep_msgs = messages[compress_start:]

        return system_msg, compress_msgs, keep_msgs
```

**After**:

```python
        compress_msgs = messages[start_idx:compress_start]
        keep_msgs = messages[compress_start:]

        return system_msg, compress_msgs, keep_msgs

    def _adjust_boundary_for_tool_pairs(
        self,
        compress_msgs: List[Message],
        keep_msgs: List[Message],
    ) -> Tuple[List[Message], List[Message]]:
        """将跨越压缩/保留边界的 tool 组整体移入保留区。"""
        keep_tool_call_ids = {
            msg.tool_call_id
            for msg in keep_msgs
            if msg.role == "tool" and msg.tool_call_id
        }
        if not compress_msgs or not keep_tool_call_ids:
            return compress_msgs, keep_msgs

        boundary_idx = None
        for index in range(len(compress_msgs) - 1, -1, -1):
            msg = compress_msgs[index]
            if msg.role != "assistant" or not msg.tool_calls:
                continue

            try:
                tool_calls = json.loads(msg.tool_calls)
            except Exception:
                logger.warning("[压缩] 跳过损坏的 tool_calls: %s", msg.tool_calls)
                continue

            tool_ids = set()
            for tc in tool_calls:
                tool_id, _, _ = _parse_tool_call(tc)
                if tool_id:
                    tool_ids.add(tool_id)

            if tool_ids & keep_tool_call_ids:
                boundary_idx = index
                break

        if boundary_idx is None:
            return compress_msgs, keep_msgs

        moved_msgs = compress_msgs[boundary_idx:]
        logger.info(
            "[压缩] 保留跨边界 tool 组: assistant_seq=%s, moved=%s",
            compress_msgs[boundary_idx].sequence,
            len(moved_msgs),
        )
        return compress_msgs[:boundary_idx], moved_msgs + keep_msgs
```

**Verification**: 调用 `_adjust_boundary_for_tool_pairs()` 时，只有最后一个跨边界 tool 组会被前移到 `keep_msgs` 前部，且消息顺序保持不变。

---

### T005: 在 `src/business/memory/compression_handler.py` 的 `_split_messages` 方法中，在现有 compress_msgs/keep_msgs 划分后调用 `_adjust_boundary_for_tool_pairs`

**File**: `src/business/memory/compression_handler.py` (modify)

**Requirements**: FR-001, FR-002, FR-003

**Dependencies**: T004

**Before** (line 321):

```python
        compress_msgs = messages[start_idx:compress_start]
        keep_msgs = messages[compress_start:]

        return system_msg, compress_msgs, keep_msgs
```

**After**:

```python
        compress_msgs = messages[start_idx:compress_start]
        keep_msgs = messages[compress_start:]
        compress_msgs, keep_msgs = self._adjust_boundary_for_tool_pairs(
            compress_msgs,
            keep_msgs,
        )

        return system_msg, compress_msgs, keep_msgs
```

**Verification**: `test_tool_group_straddles_boundary` 通过后，`_split_messages()` 的返回值中不再出现“assistant(tool_calls) 在压缩区、对应 tool result 在保留区”的拆裂情况。

---

### T006: 在 `src/business/memory/compression_handler.py` 的 `compress` 方法中，增加边界调整后 compress_msgs 为空的处理

**File**: `src/business/memory/compression_handler.py` (modify)

**Requirements**: FR-004, CC-001, CC-002

**Dependencies**: T005

**Before** (line 227):

```python
        # 分离消息区域
        system_msg, compress_msgs, keep_msgs = self._split_messages(messages)

        # 压缩区为空，跳过
        if not compress_msgs:
            logger.debug("[压缩] 压缩区为空，跳过压缩")
            return messages
```

**After**:

```python
        # 分离消息区域
        system_msg, compress_msgs, keep_msgs = self._split_messages(messages)

        # 边界调整后压缩区为空，跳过压缩和持久化
        if not compress_msgs:
            logger.debug("[压缩] 边界调整后压缩区为空，跳过压缩")
            result = list(keep_msgs)
            if system_msg:
                result.insert(0, system_msg)
            return result
```

**Verification**: 当唯一可压缩消息正好是边界 tool 组时，`compress()` 不调用 LLM、不创建 `summary` 消息、不执行 `mark_archived()`，返回结构仍是 `List[Message]`。

---

### T007: 在 `tests/business/memory/test_compression_tool_pairing.py` 补充测试：assistant 在压缩区、全部 tool result 在保留区；多个 tool 组仅最后一个跨越边界

**File**: `tests/business/memory/test_compression_tool_pairing.py` (modify)

**Requirements**: FR-001, FR-002

**Dependencies**: T006

**Before** (line ~48):

```python
def test_tool_group_straddles_boundary(handler, message_factory):
    messages = [
        message_factory(sequence=1, role="user", content="very-old"),
        message_factory(
            sequence=2,
            role="assistant",
            content=None,
            tool_calls=[
                _tool_call("call-1", "query_data"),
                _tool_call("call-2", "read_file"),
            ],
        ),
        message_factory(
            sequence=3,
            role="tool",
            content="query-result",
            tool_call_id="call-1",
            tool_name="query_data",
        ),
        message_factory(
            sequence=4,
            role="tool",
            content="file-result",
            tool_call_id="call-2",
            tool_name="read_file",
        ),
        message_factory(sequence=5, role="assistant", content="latest"),
    ]

    _, compress_msgs, keep_msgs = handler._split_messages(messages)

    assert _sequences(compress_msgs) == [1]
    assert _sequences(keep_msgs) == [2, 3, 4, 5]
```

**After**:

```python
def test_tool_group_straddles_boundary(handler, message_factory):
    messages = [
        message_factory(sequence=1, role="user", content="very-old"),
        message_factory(
            sequence=2,
            role="assistant",
            content=None,
            tool_calls=[
                _tool_call("call-1", "query_data"),
                _tool_call("call-2", "read_file"),
            ],
        ),
        message_factory(
            sequence=3,
            role="tool",
            content="query-result",
            tool_call_id="call-1",
            tool_name="query_data",
        ),
        message_factory(
            sequence=4,
            role="tool",
            content="file-result",
            tool_call_id="call-2",
            tool_name="read_file",
        ),
        message_factory(sequence=5, role="assistant", content="latest"),
    ]

    _, compress_msgs, keep_msgs = handler._split_messages(messages)

    assert _sequences(compress_msgs) == [1]
    assert _sequences(keep_msgs) == [2, 3, 4, 5]


def test_tool_group_assistant_in_compress_all_results_in_keep(handler, message_factory):
    messages = [
        message_factory(sequence=1, role="user", content="older"),
        message_factory(
            sequence=2,
            role="assistant",
            content=None,
            tool_calls=[_tool_call("call-1", "memory_search")],
        ),
        message_factory(
            sequence=3,
            role="tool",
            content="tool-result",
            tool_call_id="call-1",
            tool_name="memory_search",
        ),
        message_factory(sequence=4, role="assistant", content="latest"),
    ]

    _, compress_msgs, keep_msgs = handler._split_messages(messages)

    assert _sequences(compress_msgs) == [1]
    assert _sequences(keep_msgs) == [2, 3, 4]


def test_multiple_tool_groups_only_last_straddles(handler, message_factory):
    messages = [
        message_factory(
            sequence=1,
            role="assistant",
            content=None,
            tool_calls=[_tool_call("call-a", "query_data")],
        ),
        message_factory(
            sequence=2,
            role="tool",
            content="result-a",
            tool_call_id="call-a",
            tool_name="query_data",
        ),
        message_factory(sequence=3, role="user", content="middle"),
        message_factory(
            sequence=4,
            role="assistant",
            content=None,
            tool_calls=[
                _tool_call("call-b1", "read_file"),
                _tool_call("call-b2", "execute_code"),
            ],
        ),
        message_factory(
            sequence=5,
            role="tool",
            content="result-b1",
            tool_call_id="call-b1",
            tool_name="read_file",
        ),
        message_factory(
            sequence=6,
            role="tool",
            content="result-b2",
            tool_call_id="call-b2",
            tool_name="execute_code",
        ),
        message_factory(sequence=7, role="assistant", content="latest"),
    ]

    _, compress_msgs, keep_msgs = handler._split_messages(messages)

    assert _sequences(compress_msgs) == [1, 2, 3]
    assert _sequences(keep_msgs) == [4, 5, 6, 7]
```

**Verification**: 新增两条测试分别锁定“assistant 在压缩区、全部结果在保留区”和“仅最后一个 tool 组跨边界”的细分场景。

---

## Phase 3: User Story 2 - 多次压缩不累积残留

### T008: 在 `tests/business/memory/test_compression_tool_pairing.py` 补充测试：二次压缩会吸收上一轮保留的边界 tool 组；边界调整后压缩区为空时跳过压缩

**File**: `tests/business/memory/test_compression_tool_pairing.py` (modify)

**Requirements**: FR-003, FR-004, CC-002, SC-002

**Dependencies**: T007

**Before** (line ~58):

```python
import pytest

from src.business.memory.compression_handler import CompressionHandler
```

**After**:

```python
from unittest.mock import MagicMock

import pytest

from src.business.memory.compression_handler import CompressionHandler
```

**Before** (line ~90):

```python
def test_multiple_tool_groups_only_last_straddles(handler, message_factory):
    messages = [
        message_factory(
            sequence=1,
            role="assistant",
            content=None,
            tool_calls=[_tool_call("call-a", "query_data")],
        ),
        message_factory(
            sequence=2,
            role="tool",
            content="result-a",
            tool_call_id="call-a",
            tool_name="query_data",
        ),
        message_factory(sequence=3, role="user", content="middle"),
        message_factory(
            sequence=4,
            role="assistant",
            content=None,
            tool_calls=[
                _tool_call("call-b1", "read_file"),
                _tool_call("call-b2", "execute_code"),
            ],
        ),
        message_factory(
            sequence=5,
            role="tool",
            content="result-b1",
            tool_call_id="call-b1",
            tool_name="read_file",
        ),
        message_factory(
            sequence=6,
            role="tool",
            content="result-b2",
            tool_call_id="call-b2",
            tool_name="execute_code",
        ),
        message_factory(sequence=7, role="assistant", content="latest"),
    ]

    _, compress_msgs, keep_msgs = handler._split_messages(messages)

    assert _sequences(compress_msgs) == [1, 2, 3]
    assert _sequences(keep_msgs) == [4, 5, 6, 7]
```

**After**:

```python
def test_multiple_tool_groups_only_last_straddles(handler, message_factory):
    messages = [
        message_factory(
            sequence=1,
            role="assistant",
            content=None,
            tool_calls=[_tool_call("call-a", "query_data")],
        ),
        message_factory(
            sequence=2,
            role="tool",
            content="result-a",
            tool_call_id="call-a",
            tool_name="query_data",
        ),
        message_factory(sequence=3, role="user", content="middle"),
        message_factory(
            sequence=4,
            role="assistant",
            content=None,
            tool_calls=[
                _tool_call("call-b1", "read_file"),
                _tool_call("call-b2", "execute_code"),
            ],
        ),
        message_factory(
            sequence=5,
            role="tool",
            content="result-b1",
            tool_call_id="call-b1",
            tool_name="read_file",
        ),
        message_factory(
            sequence=6,
            role="tool",
            content="result-b2",
            tool_call_id="call-b2",
            tool_name="execute_code",
        ),
        message_factory(sequence=7, role="assistant", content="latest"),
    ]

    _, compress_msgs, keep_msgs = handler._split_messages(messages)

    assert _sequences(compress_msgs) == [1, 2, 3]
    assert _sequences(keep_msgs) == [4, 5, 6, 7]


def test_re_compress_absorbs_previous_boundary_group(handler, message_factory):
    messages = [
        message_factory(sequence=1, role="user", content="older"),
        message_factory(
            sequence=2,
            role="assistant",
            content=None,
            tool_calls=[_tool_call("call-1", "query_data")],
        ),
        message_factory(
            sequence=3,
            role="tool",
            content="result-1",
            tool_call_id="call-1",
            tool_name="query_data",
        ),
        message_factory(sequence=4, role="assistant", content="follow-up"),
        message_factory(sequence=5, role="user", content="more-context"),
        message_factory(sequence=6, role="assistant", content="latest-a"),
        message_factory(sequence=7, role="user", content="latest-b"),
    ]

    _, compress_msgs, keep_msgs = handler._split_messages(messages)

    assert _sequences(compress_msgs) == [1, 2, 3, 4, 5]
    assert _sequences(keep_msgs) == [6, 7]


def test_empty_compress_after_adjustment(handler, message_factory, monkeypatch):
    repo = MagicMock()
    repo.create = MagicMock()
    repo.mark_archived = MagicMock()
    llm_client = MagicMock()
    monkeypatch.setattr(handler, "_get_llm_client", lambda: llm_client)

    messages = [
        message_factory(
            sequence=1,
            role="assistant",
            content=None,
            tool_calls=[_tool_call("call-1", "read_file")],
        ),
        message_factory(
            sequence=2,
            role="tool",
            content="tool-result",
            tool_call_id="call-1",
            tool_name="read_file",
        ),
        message_factory(sequence=3, role="assistant", content="latest"),
    ]

    result = handler.compress("session-1", messages, repo)

    assert _sequences(result) == [1, 2, 3]
    llm_client.chat.assert_not_called()
    repo.create.assert_not_called()
    repo.mark_archived.assert_not_called()
```

**Verification**: 两条新增测试确认边界保留不会在二次压缩中无限累积，且“压缩区清空”分支不会调用 LLM 或持久化。

---

## Phase 4: User Story 3 - 压缩后“继续”能正常恢复

### T009: 在 `tests/business/memory/test_context_orphan_cleanup.py` 编写上下文兼容性回归测试

**File**: `tests/business/memory/test_context_orphan_cleanup.py` (new)

**Requirements**: FR-005, CC-004, CC-005

**Dependencies**: T002

```python
import logging
from unittest.mock import MagicMock

from src.business.memory.context_manager import ContextManager


def _tool_call(tool_id: str, name: str, args: dict | None = None) -> dict:
    return {"id": tool_id, "name": name, "args": args or {}}


def _manager(mock_config, message_repo_mock) -> ContextManager:
    manager = ContextManager("session-1", mock_config)
    manager._msg_repo = message_repo_mock
    manager._session_repo = MagicMock()
    manager._compression_handler = MagicMock()
    manager._compression_handler.should_compress.return_value = False
    return manager


def test_no_orphans(mock_config, message_repo_mock, message_factory):
    messages = [
        message_factory(
            sequence=1,
            role="assistant",
            content=None,
            tool_calls=[_tool_call("call-1", "query_data")],
        ),
        message_factory(
            sequence=2,
            role="tool",
            content="result",
            tool_call_id="call-1",
            tool_name="query_data",
        ),
        message_factory(sequence=3, role="assistant", content="done"),
    ]

    manager = _manager(mock_config, message_repo_mock)
    cleaned = manager._cleanup_orphan_tool_results(messages)

    assert [msg.sequence for msg in cleaned] == [1, 2, 3]


def test_orphan_tool_result_removed(mock_config, message_repo_mock, message_factory):
    messages = [
        message_factory(sequence=1, role="user", content="continue"),
        message_factory(
            sequence=2,
            role="tool",
            content="orphan",
            tool_call_id="call-orphan",
            tool_name="query_data",
        ),
        message_factory(sequence=3, role="assistant", content="after"),
    ]

    manager = _manager(mock_config, message_repo_mock)
    cleaned = manager._cleanup_orphan_tool_results(messages)

    assert [msg.sequence for msg in cleaned] == [1, 3]


def test_mixed_valid_and_orphan(mock_config, message_repo_mock, message_factory):
    messages = [
        message_factory(
            sequence=1,
            role="assistant",
            content=None,
            tool_calls=[_tool_call("call-1", "execute_code")],
        ),
        message_factory(
            sequence=2,
            role="tool",
            content="valid",
            tool_call_id="call-1",
            tool_name="execute_code",
        ),
        message_factory(
            sequence=3,
            role="tool",
            content="orphan",
            tool_call_id="call-2",
            tool_name="execute_code",
        ),
        message_factory(sequence=4, role="assistant", content="next"),
    ]

    manager = _manager(mock_config, message_repo_mock)
    cleaned = manager._cleanup_orphan_tool_results(messages)

    assert [msg.sequence for msg in cleaned] == [1, 2, 4]


def test_warning_logged(caplog, mock_config, message_repo_mock, message_factory):
    caplog.set_level(logging.WARNING)
    messages = [
        message_factory(
            sequence=1,
            role="tool",
            content="orphan",
            tool_call_id="call-orphan",
            tool_name="memory_search",
        )
    ]

    manager = _manager(mock_config, message_repo_mock)
    cleaned = manager._cleanup_orphan_tool_results(messages)

    assert cleaned == []
    assert "call-orphan" in caplog.text


def test_reference_handler_still_applies_after_cleanup(
    mock_config, message_repo_mock, message_factory
):
    mock_config.get_memory_reference_steps_threshold.return_value = 2
    mock_config.get_memory_reference_size_threshold.return_value = 10
    messages = [
        message_factory(
            sequence=1,
            role="assistant",
            content=None,
            tool_calls=[_tool_call("call-1", "query_data")],
        ),
        message_factory(
            sequence=2,
            role="tool",
            content="0123456789abcdef",
            tool_call_id="call-1",
            tool_name="query_data",
        ),
        message_factory(
            sequence=3,
            role="tool",
            content="orphan",
            tool_call_id="call-orphan",
            tool_name="query_data",
        ),
        message_factory(sequence=4, role="assistant", content="analysis-1"),
        message_factory(sequence=5, role="assistant", content="analysis-2"),
    ]
    message_repo_mock.get_context.return_value = messages

    manager = _manager(mock_config, message_repo_mock)
    llm_messages = manager.assemble_context()

    assert len(llm_messages) == 4
    assert llm_messages[1]["tool_call_id"] == "call-1"
    assert llm_messages[1]["content"].startswith("[REF::msg-2]")
    assert all(msg.get("tool_call_id") != "call-orphan" for msg in llm_messages)


def test_pending_tool_calls_unchanged_after_orphan_cleanup(
    mock_config, message_repo_mock, message_factory
):
    expected_pending = [_tool_call("call-1", "execute_code", {"code": "print(1)"})]
    messages = [
        message_factory(
            sequence=1,
            role="assistant",
            content=None,
            tool_calls=expected_pending,
        ),
        message_factory(
            sequence=2,
            role="tool",
            content="orphan",
            tool_call_id="call-orphan",
            tool_name="memory_search",
        ),
    ]

    manager = _manager(mock_config, message_repo_mock)
    message_repo_mock.get_context.return_value = messages
    before_cleanup = manager.get_pending_tool_calls()

    cleaned = manager._cleanup_orphan_tool_results(messages)
    message_repo_mock.get_context.return_value = cleaned
    after_cleanup = manager.get_pending_tool_calls()

    assert before_cleanup == expected_pending
    assert after_cleanup == expected_pending
```

**Verification**: 该文件覆盖 helper 级别清理、warning 记录、`assemble_context()` 与 `ReferenceHandler` 的兼容性，以及 `get_pending_tool_calls()` 的行为保持不变。

---

### T010: 在 `src/business/memory/context_manager.py` 新增 `_cleanup_orphan_tool_results(self, messages: List[Message]) -> List[Message]`

**File**: `src/business/memory/context_manager.py` (modify)

**Requirements**: FR-005, CC-004, CC-005

**Dependencies**: T009

**Before** (line 75):

```python
        # 3. 应用引用替换
        llm_messages = self._reference_handler.apply_replacements(messages)

        logger.debug(f"[上下文] 已组装 {len(llm_messages)} 条消息")
        return llm_messages

    # --- 消息持久化 ---
```

**After**:

```python
        # 3. 应用引用替换
        llm_messages = self._reference_handler.apply_replacements(messages)

        logger.debug(f"[上下文] 已组装 {len(llm_messages)} 条消息")
        return llm_messages

    def _cleanup_orphan_tool_results(self, messages: List[Message]) -> List[Message]:
        """剔除没有对应 assistant(tool_calls) 的 tool result 消息。"""
        declared_tool_call_ids = set()
        for msg in messages:
            if msg.role != "assistant" or not msg.tool_calls:
                continue
            try:
                tool_calls = json.loads(msg.tool_calls)
            except Exception:
                logger.debug(f"[上下文] 解析 tool_calls 失败: {msg.tool_calls!r}")
                continue

            for tc in tool_calls:
                tc_id = tc.get("id", "")
                if tc_id:
                    declared_tool_call_ids.add(tc_id)

        cleaned_messages = []
        for msg in messages:
            if (
                msg.role == "tool"
                and msg.tool_call_id
                and msg.tool_call_id not in declared_tool_call_ids
            ):
                logger.warning(
                    "[上下文] 剔除孤立 tool result: session=%s message_id=%s tool_call_id=%s",
                    self.session_id,
                    msg.message_id,
                    msg.tool_call_id,
                )
                continue
            cleaned_messages.append(msg)

        return cleaned_messages

    # --- 消息持久化 ---
```

**Verification**: 新 helper 只剔除“带 `tool_call_id` 且找不到对应 assistant(tool_calls)”的 `tool` 消息，不改动其他角色和有效 tool 配对。

---

### T011: 在 `src/business/memory/context_manager.py` 的 `assemble_context` 方法中，在压缩后、引用替换前调用 `_cleanup_orphan_tool_results`

**File**: `src/business/memory/context_manager.py` (modify)

**Requirements**: FR-005, CC-004, CC-005

**Dependencies**: T010

**Before** (line 55):

```python
        流程：
        1. 从 DB 加载非 archived 消息（按 sequence 排序）
        2. 检查是否需要压缩 → 如需要，执行压缩，重新加载
        3. 对 tool result 消息应用引用替换
        4. 转换为 LLM API 格式

        Returns:
            LLM API 格式的消息列表
        """
        # 1. 加载消息
        messages = self._msg_repo.get_context(self.session_id)

        # 2. 检查是否需要压缩
        if messages:
            if self._compression_handler.should_compress(messages):
                logger.info(f"[上下文] 会话 {self.session_id} 触发压缩")
                self._compression_handler.compress(self.session_id, messages, self._msg_repo)
                # 重新加载消息
                messages = self._msg_repo.get_context(self.session_id)

        # 3. 应用引用替换
        llm_messages = self._reference_handler.apply_replacements(messages)
```

**After**:

```python
        流程：
        1. 从 DB 加载非 archived 消息（按 sequence 排序）
        2. 检查是否需要压缩 → 如需要，执行压缩，重新加载
        3. 剔除孤立 tool result，避免历史残留破坏 tool_call 配对
        4. 对 tool result 消息应用引用替换
        5. 转换为 LLM API 格式

        Returns:
            LLM API 格式的消息列表
        """
        # 1. 加载消息
        messages = self._msg_repo.get_context(self.session_id)

        # 2. 检查是否需要压缩
        if messages:
            if self._compression_handler.should_compress(messages):
                logger.info(f"[上下文] 会话 {self.session_id} 触发压缩")
                self._compression_handler.compress(self.session_id, messages, self._msg_repo)
                # 重新加载消息
                messages = self._msg_repo.get_context(self.session_id)

        # 3. 剔除孤立 tool result，避免后续 LLM 配对错误
        messages = self._cleanup_orphan_tool_results(messages)

        # 4. 应用引用替换
        llm_messages = self._reference_handler.apply_replacements(messages)
```

**Verification**: `assemble_context()` 返回给 LLM 的消息序列中不再包含孤立 `tool` 消息，且 `ReferenceHandler` 仍在清理后的原始消息上正常工作。

---

## Phase 5: Polish & Cross-Cutting Concerns

### T012: 更新 `docs/ARCHITECTURE.md` 中压缩流程描述，说明边界调整步骤和孤立校验

**File**: `docs/ARCHITECTURE.md` (modify)

**Requirements**: FR-001, FR-002, FR-004, FR-005

**Dependencies**: T006, T011

**Before** (line 316):

```markdown
- **触发时机**：固定步数（默认 3 步），可配置
- Agent 需要回看细节时，调用 `load_reference` 工具加载原始数据
- 不需要额外 LLM 调用生成摘要

### 会话级记忆：消息类型系统

对话历史存库，每条消息带**类型标签**。类型可扩展，初步识别：

- **普通消息（normal）** — Agent 回复、用户输入、系统提示、工具调用结果
- **压缩消息（compressed）** — 对第 X-Y 条消息的摘要，原始消息可归档

引用替换不体现为消息类型，而是运行时行为（见记忆机制设计）。
```

**After**:

```markdown
- **触发时机**：固定步数（默认 3 步），可配置
- Agent 需要回看细节时，调用 `load_reference` 工具加载原始数据
- `CompressionHandler` 在 `keep_recent` 切分后会把跨越压缩/保留边界的 tool 组整体留在保留区；若调整后压缩区为空，则跳过摘要生成与归档
- `ContextManager` 在压缩后、引用替换前会清理孤立的 tool result，避免残留历史触发后续 LLM 的配对错误
- 不需要额外 LLM 调用生成摘要

### 会话级记忆：消息类型系统

对话历史存库，每条消息带**类型标签**。类型可扩展，初步识别：

- **普通消息（normal）** — Agent 回复、用户输入、系统提示、工具调用结果
- **压缩消息（compressed）** — 对第 X-Y 条消息的摘要，原始消息可归档

引用替换不体现为消息类型，而是运行时行为（见记忆机制设计）。
```

**Verification**: 架构文档明确反映“跨界 tool 组整体保留”和“引用替换前孤立清理”两个运行时行为。

---

### T013: 更新 `CLAUDE.md` 中“当前代码现实”部分，补充压缩边界调整和孤立校验的描述

**File**: `CLAUDE.md` (modify)

**Requirements**: FR-001, FR-002, FR-004, FR-005

**Dependencies**: T006, T011

**Before** (line 33):

```markdown
- 记忆分两层：
  - `ContextManager` 负责会话内上下文组装、压缩、引用替换
  - `assistant_memory.py` 负责 assistant 的跨会话分层摘要和 `memory_search`
- 启动入口在 `src/main.py`：GUI 启动前会先跑 `get_unified_config()` 和 `RecordingRepository.ensure_startup_recovery()`
- 录制数据工具现为 **5 工具模型**：`describe_data`、`query_data`、`execute_code`、`read_recording`、`read_field_chunk`；大字段（≥1000 字符）自动占位替换，Agent 按需分段读取
- SQL 列血缘分析在 `src/recording/filtering/query_projection_analyzer.py`（用 sqlglot）；`recording_data_tools.py` 不直接 import sqlglot（guard test 约束）
- 大字段配置走 `recording.large_field.*`（`threshold_chars` / `preview_chars` / `max_chunk_chars`，默认均 1000）
- `AgentLoop.run()` 支持**多工具批次处理**：同一轮 LLM 响应的多个 tool_calls 按顺序执行并逐一保存结果；普通工具失败时停止后续真实执行并写入 `not_executed` 级联
- 中断型工具通过 `ToolDefinition.is_interrupting: bool` 声明式分类；与任何其他工具同轮出现时判定为 `invalid_model_output`，不执行任何 handler
- `is_interrupting` 与 handler 返回类型必须强一致（`True` → `ToolSignal`，`False` → `str`）；运行时不一致写入 `handler_contract_violation`
- 工具执行 Hook 系统：`ToolDefinition` 支持 `pre_hook`/`post_hook`；`AgentConfig` 支持 `global_pre_hooks`/`global_post_hooks`；hook 模型定义在 `hook_models.py`；`load_reference`/`talk_to_user` 不进入 hook 管线
- pre_hook 只做放行/拒绝/观测；post_hook 不形成流水线，每个 hook 看到同一个原始 handler 结果；详见 `docs/PROJECT_CONSTRAINTS.md` 和 `docs/ARCHITECTURE.md`
- 会话恢复走 `get_pending_tool_calls()`，只补齐最近 assistant 消息中未配对的调用，按原始顺序
```

**After**:

```markdown
- 记忆分两层：
  - `ContextManager` 负责会话内上下文组装、压缩、孤立 tool result 清理、引用替换
  - `CompressionHandler` 在 `keep_recent` 边界处保持 assistant(tool_calls) / tool_result 成组；若边界调整后压缩区为空则直接跳过摘要落库
  - `assistant_memory.py` 负责 assistant 的跨会话分层摘要和 `memory_search`
- 启动入口在 `src/main.py`：GUI 启动前会先跑 `get_unified_config()` 和 `RecordingRepository.ensure_startup_recovery()`
- 录制数据工具现为 **5 工具模型**：`describe_data`、`query_data`、`execute_code`、`read_recording`、`read_field_chunk`；大字段（≥1000 字符）自动占位替换，Agent 按需分段读取
- SQL 列血缘分析在 `src/recording/filtering/query_projection_analyzer.py`（用 sqlglot）；`recording_data_tools.py` 不直接 import sqlglot（guard test 约束）
- 大字段配置走 `recording.large_field.*`（`threshold_chars` / `preview_chars` / `max_chunk_chars`，默认均 1000）
- `AgentLoop.run()` 支持**多工具批次处理**：同一轮 LLM 响应的多个 tool_calls 按顺序执行并逐一保存结果；普通工具失败时停止后续真实执行并写入 `not_executed` 级联
- 中断型工具通过 `ToolDefinition.is_interrupting: bool` 声明式分类；与任何其他工具同轮出现时判定为 `invalid_model_output`，不执行任何 handler
- `is_interrupting` 与 handler 返回类型必须强一致（`True` → `ToolSignal`，`False` → `str`）；运行时不一致写入 `handler_contract_violation`
- 工具执行 Hook 系统：`ToolDefinition` 支持 `pre_hook`/`post_hook`；`AgentConfig` 支持 `global_pre_hooks`/`global_post_hooks`；hook 模型定义在 `hook_models.py`；`load_reference`/`talk_to_user` 不进入 hook 管线
- pre_hook 只做放行/拒绝/观测；post_hook 不形成流水线，每个 hook 看到同一个原始 handler 结果；详见 `docs/PROJECT_CONSTRAINTS.md` 和 `docs/ARCHITECTURE.md`
- `assemble_context()` 会在引用替换前剔除孤立 tool result；会话恢复的 `get_pending_tool_calls()` 仍只补齐最近 assistant 消息中未配对的调用，按原始顺序
```

**Verification**: `CLAUDE.md` 的“当前代码现实”与实现保持一致，不再遗漏压缩边界配对和恢复期孤立清理的现状。

---

### T014: 运行 `uv run pytest tests/business/memory/` 验证所有测试通过

**File**: `tests/business/memory/` (verify)

**Requirements**: FR-001, FR-002, FR-003, FR-004, FR-005

**Dependencies**: T001, T002, T003, T004, T005, T006, T007, T008, T009, T010, T011, T012, T013

```bash
uv run python -m pytest tests/business/memory/ -q
```

**Verification**: 新建的 memory 测试套件全部通过，且失败信息不再出现 `No tool call found for function call output` 一类配对错误。

---

### T015: 运行 `uv run black src/business/memory/ tests/business/memory/` 和 `uv run flake8 src/business/memory/ tests/business/memory/`

**File**: `src/business/memory/`, `tests/business/memory/` (verify)

**Requirements**: FR-001, FR-002, FR-003, FR-004, FR-005

**Dependencies**: T014

```bash
uv run black src/business/memory/ tests/business/memory/
uv run flake8 src/business/memory/ tests/business/memory/
```

**Verification**: memory 相关源文件与测试文件都通过格式化与静态检查，说明新增实现没有破坏仓库既有代码风格与基本规范。

---

## Checklist

- [ ] T001: 创建测试目录 `tests/business/memory/` 并添加 `__init__.py`
- [ ] T002: 在 `tests/business/memory/conftest.py` 中创建共享 fixture：mock Message 工厂函数和 mock MessageRepository
- [ ] T003: 在 `tests/business/memory/test_compression_tool_pairing.py` 编写边界调整测试：test_no_tool_groups_in_compress、test_tool_group_fully_in_compress、test_tool_group_straddles_boundary
- [ ] T004: 在 `src/business/memory/compression_handler.py` 新增 `_adjust_boundary_for_tool_pairs(self, compress_msgs: List[Message], keep_msgs: List[Message]) -> Tuple[List[Message], List[Message]]`
- [ ] T005: 在 `src/business/memory/compression_handler.py` 的 `_split_messages` 方法中，在现有 compress_msgs/keep_msgs 划分后调用 `_adjust_boundary_for_tool_pairs`
- [ ] T006: 在 `src/business/memory/compression_handler.py` 的 `compress` 方法中，增加边界调整后 compress_msgs 为空的处理
- [ ] T007: 在 `tests/business/memory/test_compression_tool_pairing.py` 补充测试：assistant 在压缩区、全部 tool result 在保留区；多个 tool 组仅最后一个跨越边界
- [ ] T008: 在 `tests/business/memory/test_compression_tool_pairing.py` 补充测试：二次压缩会吸收上一轮保留的边界 tool 组；边界调整后压缩区为空时跳过压缩
- [ ] T009: 在 `tests/business/memory/test_context_orphan_cleanup.py` 编写上下文兼容性回归测试
- [ ] T010: 在 `src/business/memory/context_manager.py` 新增 `_cleanup_orphan_tool_results(self, messages: List[Message]) -> List[Message]`
- [ ] T011: 在 `src/business/memory/context_manager.py` 的 `assemble_context` 方法中，在压缩后、引用替换前调用 `_cleanup_orphan_tool_results`
- [ ] T012: 更新 `docs/ARCHITECTURE.md` 中压缩流程描述，说明边界调整步骤和孤立校验
- [ ] T013: 更新 `CLAUDE.md` 中“当前代码现实”部分，补充压缩边界调整和孤立校验的描述
- [ ] T014: 运行 `uv run pytest tests/business/memory/` 验证所有测试通过
- [ ] T015: 运行 `uv run black src/business/memory/ tests/business/memory/` 和 `uv run flake8 src/business/memory/ tests/business/memory/`
