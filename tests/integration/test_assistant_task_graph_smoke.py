from __future__ import annotations

from time import perf_counter

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.business.task_collaboration.service import TaskCollaborationService
from src.data.models_sqlite import Base
from src.data.repos import AssistantTaskAdjudicationRepository, AssistantTaskRepository


def test_200_node_graph_snapshot_returns_under_500ms() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        task_repo = AssistantTaskRepository(session)
        service = TaskCollaborationService(
            task_repo=task_repo,
            adjudication_repo=AssistantTaskAdjudicationRepository(session),
        )
        graph_id = service.create_root_graph(
            session_id="ast_perf",
            title="root",
            description="root performance graph",
            graph_id="tg_perf",
        )
        root = task_repo.list_graph_tasks(graph_id)[0]
        for index in range(1, 200):
            child = task_repo.create_task(
                graph_id=graph_id,
                session_id="ast_perf",
                parent_task_id=root.task_id,
                root_task_id=root.task_id,
                task_id=f"tsk_perf_{index:03d}",
                title=f"Task {index}",
                description=f"Task {index} description",
                assignee_type="specialist",
                assignee_id=f"spec_{index % 4}",
            )
            task_repo.add_edge(
                graph_id=graph_id,
                source_task_id=root.task_id,
                target_task_id=child.task_id,
                edge_type="delegation",
                propagation="blocking",
            )

        started = perf_counter()
        snapshot = service.get_graph_snapshot(session_id="ast_perf", graph_id=graph_id)
        payload = service.snapshot_to_dict(snapshot) if snapshot is not None else None
        elapsed = perf_counter() - started

        assert snapshot is not None
        assert payload is not None
        assert len(payload["tasks"]) == 200
        assert len(payload["edges"]) == 199
        assert elapsed < 0.5
    finally:
        session.close()
        engine.dispose()


def test_request_graph_is_scoped_per_user_message() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        task_repo = AssistantTaskRepository(session)
        service = TaskCollaborationService(
            task_repo=task_repo,
            adjudication_repo=AssistantTaskAdjudicationRepository(session),
        )

        # 同一条用户消息（seq=1）内多次委派 → 复用同一张图
        graph_a, root_a = service.get_or_create_request_graph_root(
            session_id="ast_req",
            user_message_sequence=1,
            title="请求1",
            description="整理报销",
        )
        graph_a2, root_a2 = service.get_or_create_request_graph_root(
            session_id="ast_req",
            user_message_sequence=1,
            title="请求1",
            description="整理报销",
        )
        assert (graph_a2, root_a2) == (graph_a, root_a)

        # 上一张图标记完成（模拟任务跑完或被中途放下）
        task_repo.update_status(root_a, status="done")

        # 新的用户消息（seq=2）→ 开新图，不会把新任务粘到旧图上
        graph_b, root_b = service.get_or_create_request_graph_root(
            session_id="ast_req",
            user_message_sequence=2,
            title="请求2",
            description="写周报",
        )
        assert graph_b != graph_a
        assert root_b != root_a
    finally:
        session.close()
        engine.dispose()


def test_graph_snapshot_redacts_secret_in_task_text() -> None:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        task_repo = AssistantTaskRepository(session)
        service = TaskCollaborationService(
            task_repo=task_repo,
            adjudication_repo=AssistantTaskAdjudicationRepository(session),
        )
        graph_id = service.create_root_graph(
            session_id="ast_secret",
            title="root",
            description="调用时请用 api_key=sk-live-MUST-NOT-LEAK 走鉴权",
            graph_id="tg_secret",
        )

        snapshot = service.get_graph_snapshot(session_id="ast_secret", graph_id=graph_id)

        # 任务描述含密钥模式时，REST 快照只能拿到占位符，不泄漏原文
        assert snapshot is not None
        root = snapshot.tasks[0]
        assert "sk-live" not in root.description_preview
        assert root.description_preview == "[内容已隐藏]"
    finally:
        session.close()
        engine.dispose()
