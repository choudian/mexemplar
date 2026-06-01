"""内置工具目录 — 对外公开的常量，供 specialist_service 和 skills_service 共用。"""

BUILTIN_TOOL_CATALOG: list[dict] = [
    {"tool_id": "web_search", "name": "web_search", "description": "搜索互联网获取信息"},
    {"tool_id": "web_fetch", "name": "web_fetch", "description": "获取指定 URL 的网页内容"},
    {"tool_id": "read_file", "name": "read_file", "description": "读取本地文件内容"},
    {"tool_id": "write_file", "name": "write_file", "description": "向本地文件写入内容"},
    {"tool_id": "edit_file", "name": "edit_file", "description": "编辑本地文件（精确替换）"},
    {"tool_id": "list_dir", "name": "list_dir", "description": "列出目录下的文件与子目录"},
    {"tool_id": "exec", "name": "exec", "description": "执行 shell 命令"},
    {
        "tool_id": "create_skill_methodology",
        "name": "create_skill_methodology",
        "description": "创建或更新方法论（新建 / supersede 两种模式）",
    },
    {
        "tool_id": "load_skill_methodology",
        "name": "load_skill_methodology",
        "description": "按需加载已装备方法论的完整正文",
    },
    {
        "tool_id": "retrieve_archive",
        "name": "retrieve_archive",
        "description": "检索 archive 分区的长期记忆",
    },
    {
        "tool_id": "retrieve_failure_zone",
        "name": "retrieve_failure_zone",
        "description": "检索 failure 分区的失败案例记忆",
    },
]
