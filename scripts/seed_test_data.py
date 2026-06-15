"""
种子脚本：向 mexemplar.db 插入系统测试数据，用于 UI 样式验证。

用法（在项目根目录执行）：
    uv run python scripts/seed_test_data.py
"""

import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

# 确保项目根在 sys.path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from src.data.sqlalchemy_manager import SQLAlchemyManager
from src.data.migrations import run_migrations
from src.data.models_sqlite import (
    Base,
    Session,
    Message,
    Tool,
    SkillComposition,
    SkillCompositionMember,
    TeachingFailureRecord,
    AppSettings,
    SchemaVersion,
)
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session as SA_Session, sessionmaker


def new_id(prefix: str = "") -> str:
    return prefix + uuid.uuid4().hex[:12]


def dt(hours_ago: float) -> datetime:
    return datetime.now() - timedelta(hours=hours_ago)


def seed():
    db_path = str(project_root / "data" / "mexemplar.db")
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})

    # 建表 + 迁移
    Base.metadata.create_all(engine)
    with engine.connect() as conn:
        conn.execute(
            text("INSERT INTO schema_version (version) SELECT 0 WHERE NOT EXISTS (SELECT 1 FROM schema_version)")
        )
        conn.commit()
    run_migrations(engine)

    SessionFactory = sessionmaker(bind=engine)
    session = SessionFactory()

    try:
        _seed_assistant_sessions(session)
        _seed_skills(session)
        _seed_compositions(session)
        _seed_teaching_failures(session)
        _seed_settings(session)
        session.commit()
        print("[OK] 种子数据插入完成")
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Assistant sessions + messages
# ---------------------------------------------------------------------------

def _seed_assistant_sessions(s: SA_Session):
    now = datetime.now()

    sessions_data = [
        ("sess_active_1", "帮我写一个 Excel 数据清洗脚本", "active", 1),
        ("sess_active_2", "分析上周销售报表中的异常数据", "active", 6),
        ("sess_completed_1", "自动生成周报并发送到企业微信", "completed", 48),
        ("sess_completed_2", "批量重命名 PDF 发票文件", "completed", 72),
        ("sess_failed_1", "抓取竞品网站价格对比", "failed", 120),
        ("sess_active_3", "如何设置自动备份文件夹", "active", 0.5),
    ]

    messages_data = {
        "sess_active_1": [
            ("user", "帮我写一个 Excel 数据清洗脚本，需要去除重复行、填充空值、统一日期格式。"),
            ("assistant", "好的，我来帮你编写一个 Excel 数据清洗脚本。\n\n主要功能包括：\n1. **去除重复行** — 基于 `订单号` 列去重\n2. **填充空值** — 数值列填 0，文本列填 \"未知\"\n3. **统一日期格式** — 自动识别多种日期格式并转为 `YYYY-MM-DD`\n\n需要我生成完整代码吗？"),
            ("user", "好的，请生成完整代码，使用 pandas 库。"),
            ("assistant", "```python\nimport pandas as pd\nfrom pathlib import Path\n\ndef clean_excel(input_path: str, output_path: str = None):\n    \"\"\"清洗 Excel 文件：去重、填充空值、统一日期格式\"\"\"\n    df = pd.read_excel(input_path)\n\n    # 1. 去除重复行\n    before = len(df)\n    df = df.drop_duplicates(subset=['订单号'], keep='first')\n    print(f'去除重复：{before} → {len(df)}')\n\n    # 2. 填充空值\n    for col in df.columns:\n        if df[col].dtype in ['float64', 'int64']:\n            df[col] = df[col].fillna(0)\n        else:\n            df[col] = df[col].fillna('未知')\n\n    # 3. 统一日期格式\n    date_cols = [c for c in df.columns if '日期' in c or 'date' in c.lower()]\n    for col in date_cols:\n        df[col] = pd.to_datetime(df[col], errors='coerce').dt.strftime('%Y-%m-%d')\n\n    out = output_path or input_path.replace('.xlsx', '_cleaned.xlsx')\n    df.to_excel(out, index=False)\n    print(f'已保存到：{out}')\n    return df\n\nif __name__ == '__main__':\n    clean_excel('data/sales_2024.xlsx')\n```\n\n这是一个基础的清洗脚本，你可以根据实际数据列名进行调整。需要我进一步优化吗？"),
        ],
        "sess_active_2": [
            ("user", "分析上周销售报表中的异常数据，找出销售额偏离均值超过 2 个标准差的产品。"),
            ("assistant", "我来帮你分析销售异常数据。\n\n分析步骤：\n1. 读取上周销售数据\n2. 按产品计算销售额均值和标准差\n3. 筛选偏离均值超过 2σ 的产品\n4. 生成异常报告\n\n请提供数据文件路径，或描述数据来源格式。"),
            ("user", "数据在 data/weekly_sales.csv 中，包含产品名、日期、销售额三列。"),
            ("assistant", "了解，让我基于这个数据结构进行分析。\n\n根据你的描述，CSV 格式为：\n```\n产品名,日期,销售额\n```\n\n我会生成以下输出：\n- 异常产品列表（含偏离幅度）\n- 异常分布图表\n- 建议关注点\n\n分析结果将保存为 `data/anomaly_report.html`，是否继续？"),
        ],
        "sess_completed_1": [
            ("user", "自动生成周报并发送到企业微信群"),
            ("assistant", "明白，这个任务涉及两个部分：\n1. **生成周报** — 从项目数据中汇总本周进度\n2. **发送到企业微信** — 通过 Webhook 推送消息\n\n我会创建一个工具来完成这个流程。请告诉我周报需要包含哪些内容？"),
            ("user", "包含本周完成的任务列表、阻塞事项、下周计划。数据从 Jira 导出。"),
            ("assistant", "工具已创建并验证通过 ✅\n\n**技能名称：** 生成并发送周报到企业微信\n**状态：** 已发布\n**使用方式：** 告诉我 \"发周报\" 即可触发。\n\n它会自动从 Jira 导出数据、汇总为周报、推送到你配置的企业微信群 Webhook。"),
        ],
        "sess_completed_2": [
            ("user", "批量重命名 PDF 发票文件，格式为 {日期}_{供应商}_{金额}.pdf"),
            ("assistant", "我来帮你创建批量重命名发票的工具。\n\n需要从 PDF 内容中提取日期、供应商和金额信息，然后按指定格式重命名。\n\n请确认：\n- PDF 文件存放目录？\n- 日期格式偏好（如 2024-01-15）？"),
            ("user", "目录是 D:\\发票\\2024，日期用 YYYYMMDD 格式。"),
            ("assistant", "工具已创建 ✅\n\n已处理 156 个 PDF 文件，全部按 `{日期}_{供应商}_{金额}.pdf` 格式重命名完成。有 3 个文件无法提取供应商信息，已保留原文件名并标记待处理。"),
        ],
        "sess_failed_1": [
            ("user", "帮我抓取竞品网站的产品价格做对比分析"),
            ("assistant", "⚠️ 抱歉，这个任务涉及爬取第三方网站数据，可能违反目标网站的使用条款。\n\n我无法执行此类操作，建议：\n1. 使用官方提供的 API 或数据源\n2. 手动收集公开价格信息\n3. 使用合法的市场调研工具\n\n如果你有其他需求，我很乐意帮忙。"),
        ],
        "sess_active_3": [
            ("user", "如何设置自动备份文件夹？"),
            ("assistant", "我可以帮你创建一个自动备份工具。请告诉我：\n\n1. **源文件夹** — 需要备份哪个目录？\n2. **备份目标** — 备份到哪里（本地/网盘/其他）？\n3. **备份频率** — 每天还是每周？\n4. **备份策略** — 全量备份还是增量备份？\n\n了解这些信息后我可以创建一个自动化的备份方案。"),
        ],
    }

    for sid, title, status, hours_ago in sessions_data:
        created = dt(hours_ago)
        session_model = Session(
            session_id=sid,
            workflow_id=None,
            agent_type="assistant",
            status=status,
            title=title,
            created_at=created,
            updated_at=created,
        )
        s.merge(session_model)

        msgs = messages_data.get(sid, [])
        for seq, (role, content) in enumerate(msgs, start=1):
            msg = Message(
                message_id=f"{sid}_msg_{seq}",
                session_id=sid,
                sequence=seq,
                role=role,
                content=content,
                message_type="normal",
                created_at=created + timedelta(minutes=seq * 2),
            )
            s.merge(msg)

    print(f"  助理会话：{len(sessions_data)} 个，消息：{sum(len(v) for v in messages_data.values())} 条")


# ---------------------------------------------------------------------------
# Skills (tools)
# ---------------------------------------------------------------------------

def _seed_skills(s: SA_Session):
    tools = [
        # published skills
        ("tool_pub_1", "Excel 数据清洗", "自动清洗 Excel 文件：去除重复行、填充空值、统一日期格式", "published", "intent", 3),
        ("tool_pub_2", "批量重命名文件", "按规则批量重命名指定目录下的文件，支持正则和模板", "published", "intent", 3),
        ("tool_pub_3", "PDF 内容提取", "从 PDF 文件中提取文本、表格和关键信息", "published", "intent", 3),
        ("tool_pub_4", "CSV 数据合并", "将多个 CSV 文件按指定键合并为一个文件", "published", "intent", 2),
        ("tool_pub_5", "发送企业微信通知", "通过 Webhook 向企业微信群发送格式化消息", "published", "intent", 3),

        # pending skills (source=intent → 视为 pending)
        ("tool_pend_1", "网页截图对比", "截取指定网页并与基准图进行像素级对比", "pending", "intent", 0),
        ("tool_pend_2", "邮件附件自动下载", "监控邮箱并将指定发件人的附件自动下载到本地", "pending", "intent", 1),
        ("tool_pend_3", "图片批量压缩", "批量压缩图片文件大小，保持可接受画质", "pending", "intent", 0),
        ("tool_pend_4", "JSON 数据转换", "将 JSON 数据转换为 Excel 或 CSV 格式", "pending", "intent", 0),
    ]

    for tid, name, desc, status, source, trial_ok in tools:
        hours = 200 if status == "published" else 5
        tool = Tool(
            tool_id=tid,
            tool_name=name,
            description=desc,
            parameters=[],
            steps=[],
            execution_code="print('hello')",
            code_language="python",
            source=source,
            status=status,
            trial_count=trial_ok,
            trial_success_count=trial_ok,
            workflow_id=new_id("wf_") if status == "pending" else new_id("wf_"),
            created_at=dt(hours),
            updated_at=dt(hours),
        )
        s.merge(tool)

    print(f"  技能：{len(tools)} 个（published 5, pending 4）")


# ---------------------------------------------------------------------------
# Skill compositions
# ---------------------------------------------------------------------------

def _seed_compositions(s: SA_Session):
    compositions = [
        ("comp_1", "数据处理流水线", "端到端数据处理：清洗 → 合并 → 转换 → 输出", "range", "published", True),
        ("comp_2", "报告自动化", "从数据提取到报告生成并通知", "ordered", "published", True),
        ("comp_3", "文件整理工具箱", "批量处理各类文件格式", "range", "draft", False),
        ("comp_4", "数据采集与分析", "从多源采集数据并生成分析报告", "ordered", "offline", False),
    ]

    member_map = {
        "comp_1": [("tool_pub_1", 1), ("tool_pub_4", 2), ("tool_pend_4", 3)],
        "comp_2": [("tool_pub_1", 1), ("tool_pub_5", 2)],
        "comp_3": [("tool_pub_2", 1), ("tool_pub_3", 2), ("tool_pend_3", 3)],
        "comp_4": [("tool_pub_3", 1), ("tool_pub_4", 2)],
    }

    for cid, name, desc, mode, status, assistant in compositions:
        hours = 150 if status == "published" else 10
        comp = SkillComposition(
            composition_id=cid,
            composition_name=name,
            description=desc,
            applicability=f"适用于{name}相关的办公自动化场景",
            mode=mode,
            status=status,
            assistant_enabled=assistant,
            recommend_order=(mode == "ordered"),
            needs_review=False,
            created_at=dt(hours),
            updated_at=dt(hours),
        )
        s.merge(comp)

        for tool_id, order in member_map.get(cid, []):
            member = SkillCompositionMember(
                member_id=f"{cid}_m_{order}",
                composition_id=cid,
                tool_id=tool_id,
                selected_order=order,
                execution_order=order if mode == "ordered" else None,
                created_at=dt(hours),
            )
            s.merge(member)

    print(f"  技能组合：{len(compositions)} 个")


# ---------------------------------------------------------------------------
# Teaching failures
# ---------------------------------------------------------------------------

def _seed_teaching_failures(s: SA_Session):
    failures = [
        ("fail_1", "wf_fail_001", "自动生成 PPT", "trial", "试用阶段执行超时，代码运行超过 30 秒未返回", "timeout"),
        ("fail_2", "wf_fail_002", "数据库查询优化", "programmer", "生成的 SQL 语法不正确，无法通过语法检查", "syntax_error"),
        ("fail_3", "wf_fail_003", "文档格式转换", "pm", "意图识别置信度过低（0.32），无法确认核心操作", "low_confidence"),
        ("fail_4", "wf_fail_004", "视频压缩工具", "trial", "试用结果与预期不符，输出文件损坏", "assertion_failed"),
    ]

    for rid, wid, name, stage, summary, etype in failures:
        hours = 24 * (failures.index((rid, wid, name, stage, summary, etype)) + 1)
        record = TeachingFailureRecord(
            record_id=rid,
            workflow_id=wid,
            tool_name=name,
            failed_stage=stage,
            error_summary=summary,
            error_type=etype,
            status="active",
            retry_count=1,
            created_at=dt(hours),
            updated_at=dt(hours),
        )
        s.merge(record)

    print(f"  教学失败记录：{len(failures)} 个")


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def _seed_settings(s: SA_Session):
    settings = [
        ("ai.model", "claude-sonnet-4-6", "string", "AI 模型"),
        ("ai.thinking_level", "medium", "string", "推理强度"),
        ("ai.timeout", "120", "int", "AI 超时时间（秒）"),
        ("ai.max_retries", "2", "int", "最大重试次数"),
        ("recording.mode", "desktop", "string", "录制模式"),
        ("data.auto_backup", "true", "bool", "自动备份"),
    ]
    for key, value, stype, desc in settings:
        setting = AppSettings(
            setting_key=key,
            setting_value=value,
            setting_type=stype,
            description=desc,
            created_at=dt(200),
            updated_at=dt(200),
        )
        s.merge(setting)

    print(f"  设置项：{len(settings)} 个")


if __name__ == "__main__":
    seed()
