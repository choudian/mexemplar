"""
通用录制数据访问工具

提供 4 个工具供所有 Agent（PM、程序员等）共用：
  1. describe_data   — 数据发现（渐进式：无参返回表概览，传表名返回字段详情）
  2. query_data      — agent 写 SQL 直接查询 DuckDB
  3. execute_code    — 临时 Python 代码执行（SQL 不够用时的补充）
  4. analyze_image   — 多模态模型分析截图

所有工具都不接受 recording_id 参数——通过 create_recording_tools() 工厂函数
在注册时用闭包绑定，对 agent 透明。

使用方式：
    tools = create_recording_tools(recording_id="xxx")
    # tools 是 list[ToolDefinition]，直接传给 AgentLoop
"""

import base64
import builtins as _builtins_module
import io
import json
import logging
import re
import threading
from datetime import timedelta
from typing import Any

from src.business.agents.config import ToolDefinition
from src.business.agents.tool_helpers import make_tool_schema
from src.business.ai.llm_client import LangChainLLMClient
from src.data.duckdb_manager import DuckDBManager
from src.data.unified_config import get_unified_config
from src.utils.llm_helpers import sanitize_text_for_llm

logger = logging.getLogger(__name__)


# =============================================================================
# 常量
# =============================================================================

_EXECUTE_TIMEOUT = 30  # 代码执行超时（秒）
_MAX_ACTION_INDICES = 5  # 单次最多分析的 action 数量
_MAX_QUERY_CELL_CHARS = 12_000  # query_data 单字段最大长度，避免超大上下文


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
            "filtered": ("BOOLEAN", "是否被过滤（True = 被过滤，不推荐用于分析）", None),
            "filter_reason": ("JSON", "过滤原因", None),
            "is_recommendation": ("BOOLEAN", "是否为推荐使用的请求", None),
            "importance_level": ("VARCHAR", "重要程度：high / medium / low", None),
            "filtered_at": ("DATETIME", "过滤时间", None),
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
    "filter_decisions": {
        "description": "网络请求过滤决策记录（系统标记哪些请求被过滤及原因）",
        "fields": {
            "decision_id": ("INTEGER", "决策 ID（主键）", None),
            "request_id": ("VARCHAR", "关联的请求 ID", None),
            "action_id": ("INTEGER", "关联的操作 ID（可为空）", None),
            "recording_id": ("VARCHAR", "所属录制会话 ID", None),
            "decision": ("VARCHAR", "决策结果：keep / filter", None),
            "source": ("VARCHAR", "决策来源：rule / llm", None),
            "confidence": ("FLOAT", "置信度（0~1）", None),
            "reason": ("TEXT", "过滤原因说明", None),
            "pattern_matched": ("VARCHAR", "匹配到的规则模式（如有）", None),
            "scores": ("JSON", "各维度评分", None),
            "request_timestamp": ("DATETIME", "关联请求的时间戳", None),
            "action_timestamp": ("DATETIME", "关联操作的时间戳", None),
            "timestamp": ("DATETIME", "决策时间", None),
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

_ALL_TABLE_NAMES = list(_COMMON_TABLES.keys())   # 保持插入顺序，用于展示
_ALL_TABLE_NAME_SET = set(_COMMON_TABLES.keys()) # 用于 O(1) 查找


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
        for field_name, (field_type, description, warning) in meta["fields"].items():
            entry: dict[str, Any] = {
                "name": field_name,
                "type": field_type,
                "description": description,
            }
            if warning:
                entry["warning"] = warning
            fields.append(entry)

        table_details[table_name] = {
            "description": meta["description"],
            "row_count": row_count,
            "fields": fields,
        }

    return json.dumps({"table_details": table_details}, ensure_ascii=False)


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

_SELECT_RE = re.compile(r"^\s*SELECT\b", re.IGNORECASE)


def _sanitize_query_value(value: Any) -> Any:
    """query_data 返回值清洗：去除控制字符，截断超长字符串。"""
    if not isinstance(value, str):
        return value
    return sanitize_text_for_llm(value, max_chars=_MAX_QUERY_CELL_CHARS)


def _query_data(recording_id: str, sql: str) -> str:
    """
    执行 SQL 查询。只允许 SELECT 语句。
    recording_id 通过闭包绑定，agent 写 SQL 时需自己在 WHERE 中加过滤条件。
    """
    if not _SELECT_RE.match(sql):
        return json.dumps(
            {
                "error": "只允许 SELECT 查询",
                "hint": f"你的 SQL 不是 SELECT 语句。当前 recording_id = {recording_id!r}",
            },
            ensure_ascii=False,
        )

    # 防止多语句注入（SELECT ...; DROP TABLE ...）
    if ";" in sql:
        return json.dumps(
            {
                "error": "SQL 中不允许包含分号（;），每次只能执行单条 SELECT 语句",
            },
            ensure_ascii=False,
        )

    # 防止注释注入（-- 和 /* */ 可截断后续安全检查）
    if "--" in sql or "/*" in sql:
        return json.dumps(
            {"error": "SQL 中不允许包含注释符号（-- 或 /* */）"},
            ensure_ascii=False,
        )

    # 防止 SELECT INTO（可创建新表）
    if re.search(r"\bSELECT\b.*\bINTO\b", sql, re.IGNORECASE):
        return json.dumps(
            {"error": "不允许 SELECT INTO 语句"},
            ensure_ascii=False,
        )

    db = DuckDBManager()
    try:
        col_names, rows = db.execute_and_fetchall(sql)

        if not rows:
            return json.dumps({"rows": [], "row_count": 0}, ensure_ascii=False)

        result_rows = []
        for row in rows:
            record: dict[str, Any] = {}
            for col, val in zip(col_names, row):
                # 二进制字段替换为占位提示
                if isinstance(val, (bytes, bytearray)):
                    record[col] = "[截图（二进制）]"
                else:
                    record[col] = _sanitize_query_value(val)
            result_rows.append(record)

        return json.dumps(
            {"rows": result_rows, "row_count": len(result_rows)},
            ensure_ascii=False,
            default=str,
        )

    except Exception as e:
        return json.dumps(
            {
                "error": str(e),
                "hint": (
                    f"SQL 执行失败。可用表: {', '.join(_ALL_TABLE_NAMES)}。"
                    "如不确定字段名，请先调用 describe_data 查看表结构。"
                ),
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
    safe_builtins = {**_SAFE_BUILTINS, "__import__": _safe_import}
    exec_globals: dict[str, Any] = {
        "__builtins__": safe_builtins,
        "conn": db.conn,
        "recording_id": recording_id,
        "print": lambda *args, **kwargs: print(*args, **{**kwargs, "file": stdout_buf}),
    }

    result_holder: dict[str, Any] = {"output": None, "error": None}

    def _run():
        try:
            exec(code, exec_globals)  # noqa: S102
            result_holder["output"] = stdout_buf.getvalue()
        except Exception as e:
            result_holder["error"] = f"{type(e).__name__}: {e}"

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
        logger.error(f"[analyze_image] 调用多模态模型失败: {e}", exc_info=True)
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
# 工厂函数：创建绑定了 recording_id 的工具列表
# =============================================================================

def create_recording_tools(recording_id: str) -> list[ToolDefinition]:
    """
    创建录制数据访问工具列表，recording_id 通过闭包绑定，对 agent 透明。

    Args:
        recording_id: 当前录制会话 ID

    Returns:
        4 个 ToolDefinition，可直接传给 AgentLoop
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
    "EXECUTE_CODE_SCHEMA",
    "ANALYZE_IMAGE_SCHEMA",
]
