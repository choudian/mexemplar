"""
通用录制数据访问工具

提供 5 个工具供所有 Agent（PM、程序员等）共用：
  1. describe_data      — 数据发现（渐进式：无参返回表概览，传表名返回字段详情）
  2. query_data         — agent 写 SQL 直接查询 DuckDB
  3. execute_code       — 临时 Python 代码执行（SQL 不够用时的补充）
  4. analyze_image      — 多模态模型分析截图
  5. read_field_chunk   — 分段读取大字段原始内容

所有工具都不接受 recording_id 参数——通过 create_recording_tools() 工厂函数
在注册时用闭包绑定，对 agent 透明。

使用方式：
    tools = create_recording_tools(recording_id="xxx")
    # tools 是 list[ToolDefinition]，直接传给 AgentLoop
"""

import base64
import builtins as _builtins_module
import duckdb
import functools
import io
import json
import logging
import threading
from datetime import timedelta
from typing import Any

from src.business.agents.config import ToolDefinition
from src.business.agents.tool_helpers import make_tool_schema
from src.business.ai.llm_client import LangChainLLMClient
from src.data.duckdb_manager import DuckDBManager
from src.data.unified_config import get_unified_config
from src.recording.filtering.filtered_conn import (
    DATA_ACCESS_RESTRICTED_MESSAGE,
    SQL_PARSE_FAILED_MESSAGE,
    DataAccessRestrictedError,
    FilteredDuckDBConnection,
)
from src.recording.filtering.sql_rewriter import SqlRewriteError, rewrite
from src.recording.filtering.query_projection_analyzer import (
    STABLE_LOCATOR_RULES,
    QueryProjectionAnalyzer,
    ProjectionBinding,
    find_stable_locator_in_row,
)
from src.utils.llm_helpers import sanitize_text_for_llm

logger = logging.getLogger(__name__)


# =============================================================================
# 常量
# =============================================================================

_EXECUTE_TIMEOUT = 30  # 代码执行超时（秒）
_MAX_ACTION_INDICES = 5  # 单次最多分析的 action 数量
_READABLE_TEXT_TYPES = frozenset({"TEXT", "VARCHAR", "JSON"})


# =============================================================================
# 元数据：表和字段的含义描述（硬编码，按录制模式分区）
# =============================================================================

# 通用字段描述（所有录制模式共用）
_COMMON_TABLES: dict[str, dict] = {
    "recording_sessions": {
        "description": "录制会话元数据（录制模式、起止时间等）",
        "fields": {
            "recording_id": ("VARCHAR", "录制会话唯一 ID（主键）", None),
            "status": ("VARCHAR", "录制状态：recording / stopped", None),
            "recording_mode": ("VARCHAR", "录制模式：browser / desktop", None),
            "browser_type": ("VARCHAR", "浏览器类型（browser 模式）", None),
            "start_time": ("DATETIME", "录制开始时间", None),
            "end_time": ("DATETIME", "录制结束时间", None),
            "metadata": ("JSON", "会话附加元数据", None),
            "created_at": ("DATETIME", "记录创建时间", None),
        },
    },
    "actions": {
        "description": "用户操作记录（点击、输入、导航等）",
        "fields": {
            "action_id": ("INTEGER", "操作 ID（主键）", None),
            "recording_id": ("VARCHAR", "所属录制会话 ID", None),
            "sequence_number": ("INTEGER", "操作序号，从 1 开始", None),
            "action_type": ("VARCHAR", "操作类型：click, fill, navigate, scroll, keydown, ...", None),
            "recording_mode": ("VARCHAR", "录制模式：browser / desktop", None),
            "url": ("VARCHAR", "操作发生时的页面 URL（browser 模式）", None),
            "app_name": ("VARCHAR", "应用名称（desktop 模式）", None),
            "process_name": ("VARCHAR", "进程名称（desktop 模式）", None),
            "window_title": ("TEXT", "窗口标题（desktop 模式）", None),
            "parameters": ("JSON", "操作参数（输入值、按键、坐标等）", None),
            "dom_element": ("JSON", "操作目标 DOM 元素信息，JSON 对象，常用键：tag_name、id、class、text、css_selector 等（⚠️ 这是 JSON 内部字段，不是 SQL 列，不能直接 SELECT tag_name）", None),
            "dom_tree_snapshot": (
                "JSON",
                "操作时的完整 DOM 树快照",
                "⚠️ 大字段，可能几十~几百 KB，按需查询",
            ),
            "visual_features": ("JSON", "视觉特征信息", None),
            "timestamp": ("DATETIME", "操作发生时间", None),
        },
    },
    "network_requests": {
        "description": "浏览器网络请求记录",
        "fields": {
            "request_id": ("INTEGER", "请求 ID（主键）", None),
            "action_id": ("INTEGER", "关联的操作 ID（可为空）", None),
            "recording_id": ("VARCHAR", "所属录制会话 ID", None),
            "url": ("TEXT", "请求 URL", None),
            "method": ("VARCHAR", "HTTP 方法：GET, POST, ...", None),
            "request_type": (
                "VARCHAR",
                "请求类型：main_frame, xmlhttprequest, fetch, script, image, ...",
                None,
            ),
            "request_headers": ("JSON", "请求头", None),
            "request_body": ("TEXT", "请求体", None),
            "response_status": ("INTEGER", "HTTP 响应状态码", None),
            "response_headers": ("JSON", "响应头", None),
            "response_body": (
                "TEXT",
                "响应体",
                "⚠️ 大字段，可能几 KB ~ 几百 KB，按需查询",
            ),
            "duration": ("FLOAT", "请求耗时（毫秒）", None),
            "timestamp": ("DATETIME", "请求发生时间", None),
        },
    },
    "sibling_snapshots": {
        "description": "操作目标元素的兄弟元素快照，用于识别列表类操作",
        "fields": {
            "snapshot_id": ("INTEGER", "快照 ID（主键）", None),
            "action_id": ("INTEGER", "关联的操作 ID", None),
            "recording_id": ("VARCHAR", "所属录制会话 ID", None),
            "container_selector": ("TEXT", "列表容器的 CSS 选择器", None),
            "item_selector": ("TEXT", "列表项的 CSS 选择器", None),
            "list_type": ("VARCHAR", "列表类型", None),
            "siblings": (
                "JSON",
                "兄弟元素列表（含 text_summary、has_link 等字段）",
                "⚠️ 大字段，列表项多时可能较大",
            ),
            "structure_similarity": ("FLOAT", "结构相似度（0~1）", None),
            "is_homogeneous": ("BOOLEAN", "是否为同构列表", None),
            "clicked_index": ("INTEGER", "被点击的元素序号", None),
            "total_count": ("INTEGER", "兄弟元素总数", None),
            "timestamp": ("DATETIME", "快照时间", None),
        },
    },
    "recording_screenshots": {
        "description": "浏览器截图时序数据（按时间窗与 action 关联）",
        "fields": {
            "screenshot_id": ("INTEGER", "截图记录 ID（主键）", None),
            "recording_id": ("VARCHAR", "所属录制会话 ID", None),
            "moment": ("VARCHAR", "截图时机：before / after", None),
            "timestamp": ("DATETIME", "截图实际完成时间（查询主键）", None),
            "capture_id": ("VARCHAR", "诊断用：同一次物理输入的 before/after 共享 ID", None),
            "source_trigger": ("VARCHAR", "诊断用：触发输入类型 mouse_left / enter", None),
            "input_started_at": ("DATETIME", "诊断用：输入开始时间", None),
            "input_completed_at": ("DATETIME", "诊断用：输入完成时间", None),
            "media_type": ("VARCHAR", "图片 MIME 类型 image/jpeg", None),
            "data": ("BLOB", "JPEG 图片二进制数据", None),
        },
    },
}

_ALL_TABLE_NAMES = list(_COMMON_TABLES.keys())
_ALL_TABLE_NAME_SET = set(_COMMON_TABLES.keys())


# =============================================================================
# 大字段占位替换
# =============================================================================


@functools.lru_cache(maxsize=1)
def _get_analyzer() -> QueryProjectionAnalyzer:
    return QueryProjectionAnalyzer()


def _build_large_field_placeholder(
    value: str,
    col_name: str,
    row: dict[str, Any],
    bindings: list[ProjectionBinding],
    bindings_map: dict[str, ProjectionBinding],
    preview_chars: int,
) -> dict[str, Any]:
    """为达到阈值的文本字段构建占位对象。"""
    binding = bindings_map.get(col_name)

    placeholder: dict[str, Any] = {
        "__large_field__": True,
        "field": col_name,
        "size_chars": len(value),
        "preview": None,
        "locator": None,
        "read_hint": "read_field_chunk",
    }

    def _blocked(reason: str, message: str, field: str = col_name) -> dict[str, Any]:
        placeholder["field"] = field
        placeholder["read_blocked_reason"] = reason
        placeholder["read_blocked_message"] = message
        return placeholder

    if binding is None or not binding.is_direct_column or not binding.source_table:
        logger.info("[large_field] blocked: computed_or_aggregated_column, col=%s", col_name)
        return _blocked(
            "computed_or_aggregated_column",
            f"结果列 '{col_name}' 为计算列或无法追溯到单条源记录，不支持继续读取。",
        )

    source_table = binding.source_table
    source_field = binding.source_field or col_name

    rule = STABLE_LOCATOR_RULES.get(source_table)
    if rule is None:
        logger.info("[large_field] blocked: unsupported_source_table, table=%s, field=%s", source_table, source_field)
        return _blocked(
            "unsupported_source_table",
            f"源表 '{source_table}' 未由内置定位规则覆盖，不支持继续读取。",
            field=source_field,
        )

    loc_binding = find_stable_locator_in_row(bindings, source_table, row)
    if loc_binding is None:
        logger.info(
            "[large_field] blocked: missing_locator_field, table=%s, field=%s, need=%s",
            source_table, source_field, rule.recommended_id_field,
        )
        return _blocked(
            "missing_locator_field",
            f"当前结果缺少继续读取所需的稳定定位字段 {rule.recommended_id_field}，请补查直接列。",
            field=source_field,
        )

    id_value = row.get(loc_binding.output_name)
    placeholder["preview"] = value[:preview_chars]
    placeholder["field"] = source_field
    placeholder["locator"] = {
        "table": source_table,
        "id_field": rule.recommended_id_field,
        "id_value": id_value,
    }
    return placeholder


# =============================================================================
# 工具 1：describe_data
# =============================================================================

def _describe_data(recording_id: str, tables: list[str] | None = None) -> str:
    """
    数据发现入口。渐进式返回：
    - 不传 tables：返回所有表的概览（表名 + 含义 + 行数）
    - 传 tables：返回指定表的字段详情
    """
    db = DuckDBManager()

    def _get_row_count(tn: str) -> int:
        try:
            if tn == "network_requests":
                row = db.fetchone(
                    "SELECT COUNT(*) FROM network_requests WHERE recording_id = ? AND filtered = FALSE",
                    (recording_id,),
                )
                return row[0] if row else 0
            row = db.fetchone(
                f"SELECT COUNT(*) FROM {tn} WHERE recording_id = ?",
                (recording_id,),
            )
            return row[0] if row else 0
        except Exception:
            return 0

    if tables is None:
        result = {"tables": []}
        for table_name, meta in _COMMON_TABLES.items():
            result["tables"].append(
                {
                    "name": table_name,
                    "description": meta["description"],
                    "row_count": _get_row_count(table_name),
                }
            )
        return json.dumps(result, ensure_ascii=False)

    # 第二级：字段详情
    unknown = [t for t in tables if t not in _ALL_TABLE_NAME_SET]
    if unknown:
        return json.dumps(
            {
                "error": f"未知表名: {unknown}",
                "available_tables": _ALL_TABLE_NAMES,
            },
            ensure_ascii=False,
        )

    table_details: dict[str, Any] = {}
    for table_name in tables:
        meta = _COMMON_TABLES[table_name]
        row_count = _get_row_count(table_name)

        fields = []
        locator_rule = STABLE_LOCATOR_RULES.get(table_name)
        for field_name, (field_type, description, warning) in meta["fields"].items():
            entry: dict[str, Any] = {
                "name": field_name,
                "type": field_type,
                "description": description,
            }
            if warning:
                entry["warning"] = warning
            if (
                locator_rule is not None
                and field_type.upper() in _READABLE_TEXT_TYPES
            ):
                entry["large_field"] = True
                entry["read_via"] = "read_field_chunk"
                entry["locator_fields"] = locator_rule.describe_locator_fields
            fields.append(entry)

        table_details[table_name] = {
            "description": meta["description"],
            "row_count": row_count,
            "fields": fields,
        }

    return json.dumps({"table_details": table_details}, ensure_ascii=False)


def _classify_error(exc: Exception) -> str | None:
    if isinstance(exc, DataAccessRestrictedError):
        return DATA_ACCESS_RESTRICTED_MESSAGE
    if isinstance(exc, SqlRewriteError):
        return SQL_PARSE_FAILED_MESSAGE
    return None


def _mask_recording_data_error(exc: Exception) -> str:
    masked = _classify_error(exc)
    if masked is not None:
        return masked
    if isinstance(exc, duckdb.Error):
        return f"SQL 执行失败: {exc}。可用表: {', '.join(_ALL_TABLE_NAMES)}。"
    return SQL_PARSE_FAILED_MESSAGE


DESCRIBE_DATA_SCHEMA: dict[str, Any] = make_tool_schema(
    name="describe_data",
    description=(
        "数据发现工具。了解本次录制有哪些数据可查。\n"
        "- 不传 tables：返回所有表的概览（表名、含义、数据量）。建议任务开始时先调用一次。\n"
        "- 传 tables：返回指定表的字段详情（字段名、类型、含义、注意事项）。"
        "拿到字段信息后再用 query_data 写 SQL 查询。"
    ),
    properties={
        "tables": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "要查看字段详情的表名列表，如 [\"actions\", \"network_requests\"]。"
                "不传此参数则返回所有表的概览。"
            ),
        },
    },
    required=[],
)


# =============================================================================
# 工具 2：query_data
# =============================================================================


def _query_data(recording_id: str, sql: str) -> str:
    """
    执行 SQL 查询。只允许 SELECT 语句。
    recording_id 通过闭包绑定，agent 写 SQL 时需自己在 WHERE 中加过滤条件。
    """
    db = DuckDBManager()
    try:
        rewritten_sql = rewrite(sql)
        col_names, rows = db.execute_and_fetchall(rewritten_sql)

        if not rows:
            return json.dumps({"rows": [], "row_count": 0}, ensure_ascii=False)

        config = get_unified_config().get_recording_large_field_config()
        threshold = config.threshold_chars
        preview_chars = config.preview_chars

        bindings: list[ProjectionBinding] | None = None
        bindings_map: dict[str, ProjectionBinding] = {}

        result_rows = []
        for row in rows:
            row_dict = dict(zip(col_names, row))
            record: dict[str, Any] = {}
            for col, val in row_dict.items():
                if isinstance(val, (bytes, bytearray)):
                    record[col] = "[截图（二进制）]"
                elif isinstance(val, str):
                    if len(val) >= threshold:
                        if bindings is None:
                            bindings = _get_analyzer().analyze(sql)
                            bindings_map = {b.output_name: b for b in bindings}
                        record[col] = _build_large_field_placeholder(
                            value=val,
                            col_name=col,
                            row=row_dict,
                            bindings=bindings,
                            bindings_map=bindings_map,
                            preview_chars=preview_chars,
                        )
                    else:
                        record[col] = sanitize_text_for_llm(val)
                else:
                    record[col] = val
            result_rows.append(record)

        return json.dumps(
            {"rows": result_rows, "row_count": len(result_rows)},
            ensure_ascii=False,
            default=str,
        )

    except Exception as e:
        logger.error("[query_data] SQL failed: %s", sql, exc_info=True)
        return json.dumps(
            {
                "error": _mask_recording_data_error(e),
            },
            ensure_ascii=False,
        )


QUERY_DATA_SCHEMA: dict[str, Any] = make_tool_schema(
    name="query_data",
    description=(
        "执行 SQL 查询录制数据（DuckDB SQL 语法）。只允许 SELECT 语句。\n"
        "⚠️ 注意上下文：非必要不要 SELECT *，按需查询字段；"
        "数据量大时使用 LIMIT 分页；大字段（dom_tree_snapshot、response_body 等）"
        "按需查询，避免撑满上下文窗口。\n"
        "不确定字段名时，先用 describe_data 查看表结构。"
    ),
    properties={
        "sql": {
            "type": "string",
            "description": (
                "SELECT 查询语句。示例：\n"
                "SELECT sequence_number, action_type, url FROM actions "
                "WHERE recording_id = 'xxx' ORDER BY sequence_number LIMIT 20"
            ),
        },
    },
    required=["sql"],
)


# =============================================================================
# 工具 3：execute_code
# =============================================================================

# execute_code 允许使用的内建函数白名单（数据探索够用，阻止 open/exec/eval/__import__ 等危险操作）
_SAFE_BUILTINS: dict[str, Any] = {
    name: getattr(_builtins_module, name, None)
    for name in (
        # 类型与转换
        "int", "float", "str", "bool", "bytes", "bytearray",
        "list", "tuple", "dict", "set", "frozenset",
        "type", "isinstance", "issubclass", "callable",
        # 数值
        "abs", "round", "min", "max", "sum", "pow", "divmod",
        # 容器操作
        "len", "range", "enumerate", "zip", "map", "filter", "sorted", "reversed",
        "any", "all", "iter", "next",
        # 字符串/repr
        "repr", "format", "chr", "ord", "hex", "oct", "bin", "ascii",
        # 其他安全操作（不含 getattr/setattr/hasattr/dir/vars——内省函数可绕过沙箱）
        "id", "hash",
        "slice", "object", "super", "property", "staticmethod", "classmethod",
        "True", "False", "None",
        "Exception", "ValueError", "TypeError", "KeyError", "IndexError",
        "RuntimeError", "StopIteration", "AttributeError",
    )
}
# 允许 import 指定的安全模块（json、math、re、collections 等数据处理常用库）
_ALLOWED_MODULES = frozenset({
    "json", "math", "re", "collections", "itertools", "functools",
    "datetime", "statistics", "textwrap", "string", "operator",
    "base64", "hashlib", "urllib",
})


def _safe_import(name: str, globals_=None, locals_=None, fromlist=(), level=0):
    """受限 __import__：只允许白名单中的模块。"""
    top_level = name.split(".")[0]
    if top_level not in _ALLOWED_MODULES:
        raise ImportError(
            f"不允许导入模块 '{name}'。允许的模块: {', '.join(sorted(_ALLOWED_MODULES))}"
        )
    return __import__(name, globals_, locals_, fromlist, level)


_SAFE_BUILTINS_WITH_IMPORT: dict[str, Any] = {**_SAFE_BUILTINS, "__import__": _safe_import}


def _execute_code(recording_id: str, code: str) -> str:
    """
    临时执行 Python 代码。用于 SQL 搞不定的复杂数据探索。
    预注入 conn（DuckDB 连接）和 recording_id。

    安全模型：代码由 agent 生成（非用户直接输入），但仍做沙箱限制——
    禁止文件 I/O、网络访问、os/sys/subprocess 等，只保留数据处理所需的能力。
    """
    db = DuckDBManager()
    stdout_buf = io.StringIO()

    # 预注入环境。用自定义 print 捕获输出，避免修改 sys.stdout（进程全局，线程不安全）。
    # 用字典合并强制覆盖 file=，防止用户代码显式传 file= 时出现 "多值关键字参数" TypeError。
    safe_builtins = _SAFE_BUILTINS_WITH_IMPORT
    exec_globals: dict[str, Any] = {
        "__builtins__": safe_builtins,
        "conn": FilteredDuckDBConnection(db.connect()),
        "recording_id": recording_id,
        "print": lambda *args, **kwargs: print(*args, **{**kwargs, "file": stdout_buf}),
    }

    result_holder: dict[str, Any] = {"output": None, "error": None}

    def _run():
        try:
            exec(code, exec_globals)  # noqa: S102
            result_holder["output"] = stdout_buf.getvalue()
        except Exception as e:
            logger.error("[execute_code] execution failed", exc_info=True)
            masked_error = _classify_error(e)
            result_holder["error"] = masked_error or f"{type(e).__name__}: {e}"

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout=_EXECUTE_TIMEOUT)

    if thread.is_alive():
        return json.dumps(
            {"error": f"代码执行超时（超过 {_EXECUTE_TIMEOUT} 秒）"},
            ensure_ascii=False,
        )

    if result_holder["error"]:
        return json.dumps({"error": result_holder["error"]}, ensure_ascii=False)

    return json.dumps(
        {"output": result_holder["output"] or "（无输出）"},
        ensure_ascii=False,
    )


EXECUTE_CODE_SCHEMA: dict[str, Any] = make_tool_schema(
    name="execute_code",
    description=(
        "临时执行 Python 代码，用于 SQL 不够用的复杂数据探索（如遍历 JSON 字段、统计计算等）。\n"
        "这是探索工具，代码跑完即丢，不会入库。与 submit_code（交付代码）完全不同。\n"
        "预注入变量：conn（DuckDB 连接）、recording_id（当前录制 ID）。\n"
        "示例（注意：tag_name 是 dom_element JSON 里的键，不是 SQL 列）：\n"
        "import json\n"
        "rows = conn.execute(\"SELECT dom_element FROM actions WHERE recording_id = ?\" , "
        "[recording_id]).fetchall()\n"
        "# json.loads 解析 JSON 字符串，tag_name 是 JSON 内部的 key，不是数据库列\n"
        "tags = [json.loads(r[0])['tag_name'] for r in rows if r[0]]\n"
        "print(set(tags))"
    ),
    properties={
        "code": {
            "type": "string",
            "description": "要执行的 Python 代码。用 print() 输出结果。",
        },
    },
    required=["code"],
)


# =============================================================================
# 工具 4：analyze_image
# =============================================================================

# 多模态 LLM 客户端懒加载单例（基于 LangChain，支持 Anthropic / OpenAI / 各家兼容接口）
_vision_llm_client: LangChainLLMClient | None = None
_vision_llm_lock = threading.Lock()


def _get_vision_llm_client() -> LangChainLLMClient:
    """获取多模态 LLM 客户端（线程安全懒加载）。"""
    global _vision_llm_client
    if _vision_llm_client is None:
        with _vision_llm_lock:
            if _vision_llm_client is None:
                config = get_unified_config()
                _vision_llm_client = LangChainLLMClient(
                    provider=config.get_ai_vision_provider(),
                    model=config.get_ai_vision_model(),
                    api_key=config.get_ai_vision_api_key(),
                    base_url=config.get_ai_vision_base_url(),
                    temperature=0.3,
                    max_tokens=1024,
                )
    return _vision_llm_client


def _detect_image_type(data: bytes) -> str:
    """根据文件头字节检测图片 MIME 类型，默认 image/png。"""
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"\x89PNG":
        return "image/png"
    if data[:4] == b"GIF8":
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"  # 默认


def _analyze_image(
    recording_id: str,
    action_index: int | list[int],
    question: str,
) -> str:
    """
    调多模态模型分析截图。
    从 DuckDB 读取 before/after 截图，按时间顺序传给多模态模型。
    图片不进 agent 主上下文，只返回文本分析结果。
    """
    if isinstance(action_index, int):
        indices = [action_index]
    else:
        indices = list(action_index)

    if len(indices) > _MAX_ACTION_INDICES:
        return json.dumps(
            {
                "error": f"单次最多分析 {_MAX_ACTION_INDICES} 个操作的截图，"
                f"当前传入 {len(indices)} 个，请缩小范围。"
            },
            ensure_ascii=False,
        )

    db = DuckDBManager()

    _WINDOW_SPECS = {
        "before": (1.0, 0.25),   # (backward_seconds, forward_seconds)
        "after":  (0.0, 1.5),    # (backward_seconds, forward_seconds)
    }

    _SCREENSHOT_SQL = """
        SELECT data, media_type FROM recording_screenshots
        WHERE recording_id = ?
          AND moment = ?
          AND timestamp BETWEEN ? AND ?
        ORDER BY abs(epoch(timestamp) - epoch(?))
        LIMIT 1
    """

    images: list[dict[str, str]] = []
    for idx in sorted(indices):
        row = db.fetchone(
            "SELECT timestamp FROM actions WHERE recording_id = ? AND sequence_number = ?",
            (recording_id, idx),
        )
        if not row or row[0] is None:
            continue
        t = row[0]

        for moment, (back, fwd) in _WINDOW_SPECS.items():
            match = db.fetchone(
                _SCREENSHOT_SQL,
                (recording_id, moment, t - timedelta(seconds=back), t + timedelta(seconds=fwd), t),
            )
            if match:
                label = f"操作{idx}{'前' if moment == 'before' else '后'}"
                images.append({
                    "label": label,
                    "data": base64.standard_b64encode(match[0]).decode(),
                    "media_type": match[1] or _detect_image_type(match[0]),
                })

    if not images:
        return json.dumps(
            {"error": f"未找到操作 {indices} 的截图数据（可能该录制模式不保存截图）"},
            ensure_ascii=False,
        )

    # 构建 LangChain 多模态消息（OpenAI 格式，LangChain 会自动适配各家 API）
    content: list[dict[str, Any]] = []
    for img in images:
        content.append({"type": "text", "text": f"[{img['label']}]"})
        content.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{img['media_type']};base64,{img['data']}",
                },
            }
        )
    content.append({"type": "text", "text": question})

    try:
        vision_client = _get_vision_llm_client()
        from langchain_core.messages import HumanMessage

        response = vision_client.llm.invoke([HumanMessage(content=content)])
        answer = response.content
        if not answer:
            return json.dumps({"error": "多模态模型返回空响应"}, ensure_ascii=False)
        return json.dumps({"analysis": answer}, ensure_ascii=False)

    except Exception as e:
        logger.error("[analyze_image] 调用多模态模型失败: %s", e, exc_info=True)
        return json.dumps({"error": f"多模态模型调用失败: {e}"}, ensure_ascii=False)


ANALYZE_IMAGE_SCHEMA: dict[str, Any] = make_tool_schema(
    name="analyze_image",
    description=(
        "⚠️ 最后手段工具。仅当文本数据（URL、parameters、dom_element、css_selector 等）"
        "完全不足以回答问题时才使用。调用多模态模型成本高、耗时长。\n"
        "绝大多数情况下，查询文本字段已足够，不要把截图分析当作常规步骤。\n"
        "适用场景举例：需要识别截图中的验证码、图片内容、无法从 DOM 推断的视觉布局。\n"
        f"单次最多传入 {_MAX_ACTION_INDICES} 个操作序号（每个操作有操作前/后两张截图）。\n"
        "图片不会进入对话上下文，只返回模型的文字分析结果。"
    ),
    properties={
        "action_index": {
            "oneOf": [
                {"type": "integer"},
                {"type": "array", "items": {"type": "integer"}},
            ],
            "description": (
                "操作序号（从 1 开始）。单个：3；多个：[2, 3, 4]。"
                f"最多 {_MAX_ACTION_INDICES} 个。"
            ),
        },
        "question": {
            "type": "string",
            "description": "想了解什么，如：页面上有哪些表单元素、这几步操作页面发生了什么变化",
        },
    },
    required=["action_index", "question"],
)


# =============================================================================
# 工具 5：read_field_chunk
# =============================================================================


def _make_chunk_response(
    *,
    content: str = "",
    field: str = "",
    locator: dict[str, Any] | None = None,
    offset: int = 0,
    returned_length: int = 0,
    total_length: int | None = None,
    has_more: bool = False,
    next_offset: int | None = None,
    error: dict[str, str] | None = None,
) -> dict[str, Any]:
    """构造统一的 ChunkReadResponse。"""
    return {
        "content": content,
        "field": field,
        "locator": locator,
        "offset": offset,
        "returned_length": returned_length,
        "total_length": total_length,
        "has_more": has_more,
        "next_offset": next_offset,
        "error": error,
    }


def _make_chunk_error(
    code: str, message: str, *, field: str = "", locator: Any = None,
    offset: int = 0, total_length: int | None = None,
) -> dict[str, Any]:
    return _make_chunk_response(
        field=field,
        locator=locator,
        offset=offset,
        total_length=total_length,
        error={"code": code, "message": message},
    )


def _read_field_chunk(
    recording_id: str,
    locator: dict[str, Any],
    field: str,
    offset: int,
    length: int | None = None,
) -> str:
    """
    分段读取大字段原始内容。按 locator 定位源记录，Python str 切片返回。
    network_requests 走 filtered SQL rewrite path。
    """
    config = get_unified_config().get_recording_large_field_config()
    max_chunk = config.max_chunk_chars

    def _err(code: str, msg: str, *, _locator=locator, _offset=offset, **kw) -> str:
        return json.dumps(
            _make_chunk_error(code, msg, field=field, locator=_locator, offset=_offset, **kw),
            ensure_ascii=False,
        )

    # 参数校验
    if offset < 0:
        return _err("invalid_offset", f"offset 不能为负数: {offset}")

    if length is not None and length <= 0:
        return _err("invalid_length", f"length 必须为正数: {length}")

    effective_length = min(length or max_chunk, max_chunk)

    # 定位器校验
    table = locator.get("table", "")
    id_field = locator.get("id_field", "")
    id_value = locator.get("id_value")

    if table not in _ALL_TABLE_NAME_SET:
        return _err("unknown_table", f"表 '{table}' 不存在", _locator=None)

    rule = STABLE_LOCATOR_RULES.get(table)
    if rule is None:
        return _err("unsupported_continuation", f"表 '{table}' 未由内置定位规则覆盖，不支持分段读取")

    if id_field != rule.recommended_id_field:
        logger.info(
            "[read_field_chunk] unknown_id_field: table=%s, id_field=%s, expected=%s",
            table, id_field, rule.recommended_id_field,
        )
        return _err(
            "unknown_id_field",
            f"定位字段 '{id_field}' 不是表 '{table}' 的稳定定位字段（期望: {rule.recommended_id_field}）",
        )

    table_meta = _COMMON_TABLES[table]
    field_meta = table_meta["fields"].get(field)
    if field_meta is None:
        return _err("field_not_found", f"字段 '{field}' 不存在于表 '{table}'")
    field_type = field_meta[0].upper()
    if field_type not in _READABLE_TEXT_TYPES:
        return _err("non_text_field", f"字段 '{field}' 类型为 {field_type}，不是文本字段")

    # 数据读取
    db = DuckDBManager()
    try:
        raw_sql = (
            f"SELECT {field} FROM {table} "
            f"WHERE {id_field} = ? AND recording_id = ?"
        )
        effective_sql = rewrite(raw_sql) if rule.requires_filter_rewrite else raw_sql
        row = db.fetchone(effective_sql, (id_value, recording_id))
        raw_value = row[0] if row is not None else None

        if raw_value is None:
            logger.info(
                "[read_field_chunk] record_unavailable: table=%s, %s=%s",
                table, id_field, id_value,
            )
            return _err("record_unavailable", f"{table} 记录 {id_field}={id_value} 未找到或已被过滤。")

        if not isinstance(raw_value, str):
            return _err("non_text_field", f"字段 '{field}' 的值不是文本类型")

        total_length = len(raw_value)

        if offset >= total_length:
            return json.dumps(
                _make_chunk_response(
                    content="",
                    field=field,
                    locator=locator,
                    offset=offset,
                    total_length=total_length,
                ),
                ensure_ascii=False,
            )

        end = min(offset + effective_length, total_length)
        content = raw_value[offset:end]
        returned_length = len(content)
        has_more = end < total_length
        next_offset = offset + returned_length if has_more else None

        return json.dumps(
            _make_chunk_response(
                content=content,
                field=field,
                locator=locator,
                offset=offset,
                returned_length=returned_length,
                total_length=total_length,
                has_more=has_more,
                next_offset=next_offset,
            ),
            ensure_ascii=False,
        )

    except Exception as e:
        logger.error(
            "[read_field_chunk] internal_error: table=%s, field=%s, %s=%s",
            table, field, id_field, id_value,
            exc_info=True,
        )
        return _err("internal_error", "内部错误，请稍后重试。")


READ_FIELD_CHUNK_SCHEMA: dict[str, Any] = make_tool_schema(
    name="read_field_chunk",
    description=(
        "分段读取大字段原始内容。当 query_data 返回带 __large_field__ 标记的占位对象时，"
        "使用本工具按 locator + offset + length 分段读取原文。\n"
        "使用方法：\n"
        "1. 从占位对象的 locator 字段获取定位信息\n"
        "2. 使用 field（字段名）、offset（起始偏移，默认0）、length（读取长度，可选）调用\n"
        "3. 根据 has_more 和 next_offset 继续读取剩余内容\n"
        "4. 返回 content=\"\" 且 has_more=false 表示已到末尾"
    ),
    properties={
        "locator": {
            "type": "object",
            "description": "从占位对象获取的定位信息，包含 table、id_field、id_value",
            "properties": {
                "table": {"type": "string", "description": "源表名"},
                "id_field": {"type": "string", "description": "稳定定位字段名"},
                "id_value": {"description": "定位字段值（整数或字符串）"},
            },
            "required": ["table", "id_field", "id_value"],
        },
        "field": {
            "type": "string",
            "description": "要读取的字段名（如 response_body、dom_tree_snapshot）",
        },
        "offset": {
            "type": "integer",
            "description": "起始字符偏移（从0开始），默认 0",
        },
        "length": {
            "type": "integer",
            "description": "本次读取的字符长度。不传则使用默认值（1000字符）。",
        },
    },
    required=["locator", "field", "offset"],
)


# =============================================================================
# 工厂函数：创建绑定了 recording_id 的工具列表
# =============================================================================

def create_recording_tools(recording_id: str) -> list[ToolDefinition]:
    """
    创建录制数据访问工具列表，recording_id 通过闭包绑定，对 agent 透明。

    Args:
        recording_id: 当前录制会话 ID

    Returns:
        5 个 ToolDefinition，可直接传给 AgentLoop
    """
    return [
        ToolDefinition(
            name="describe_data",
            schema=DESCRIBE_DATA_SCHEMA,
            handler=lambda tables=None: _describe_data(recording_id, tables),
        ),
        ToolDefinition(
            name="query_data",
            schema=QUERY_DATA_SCHEMA,
            handler=lambda sql: _query_data(recording_id, sql),
        ),
        ToolDefinition(
            name="read_field_chunk",
            schema=READ_FIELD_CHUNK_SCHEMA,
            handler=lambda locator, field, offset, length=None: _read_field_chunk(
                recording_id, locator, field, offset, length
            ),
        ),
        ToolDefinition(
            name="execute_code",
            schema=EXECUTE_CODE_SCHEMA,
            handler=lambda code: _execute_code(recording_id, code),
        ),
        ToolDefinition(
            name="analyze_image",
            schema=ANALYZE_IMAGE_SCHEMA,
            handler=lambda action_index, question: _analyze_image(
                recording_id, action_index, question
            ),
        ),
    ]


__all__ = [
    "create_recording_tools",
    "DESCRIBE_DATA_SCHEMA",
    "QUERY_DATA_SCHEMA",
    "READ_FIELD_CHUNK_SCHEMA",
    "EXECUTE_CODE_SCHEMA",
    "ANALYZE_IMAGE_SCHEMA",
]
