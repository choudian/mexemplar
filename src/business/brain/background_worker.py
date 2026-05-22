"""
Brain Background Worker - daemon thread 处理 pending segments、崩溃恢复等周期任务
"""

import logging
import threading
from typing import Optional, Callable

from src.utils.events import connect

logger = logging.getLogger(__name__)

_brain_worker_running = False
_brain_worker_event: Optional[threading.Event] = None
_brain_worker_thread: Optional[threading.Thread] = None
_brain_worker_notify: Optional[Callable] = None


def register_brain_worker_notify(callback: Callable):
    """注册 worker 唤醒回调"""
    global _brain_worker_notify
    _brain_worker_notify = callback


def notify_brain_worker():
    """唤醒 worker 立即处理"""
    if _brain_worker_event is not None:
        _brain_worker_event.set()


class BrainBackgroundWorker:
    """大脑后台工作线程 - 处理 pending segments 的沉淀"""

    def __init__(
        self,
        config=None,
        distillation_service=None,
        prediction_service=None,
        llm_client=None,
        distillation_phase: str = "p4",
    ):
        self._config = config
        self._distillation_service = distillation_service
        self._prediction_service = prediction_service
        self._llm_client = llm_client
        self._distillation_phase = distillation_phase
        self._tick_event = threading.Event()
        self._running = False

    def _get_config(self):
        if self._config is None:
            from src.data.unified_config import get_unified_config

            self._config = get_unified_config()
        return self._config

    def _get_distillation_service(self):
        if self._distillation_service is None:
            from src.business.brain.distillation_service import DistillationService

            self._distillation_service = DistillationService()
        return self._distillation_service

    def _get_prediction_service(self):
        if self._prediction_service is None:
            from src.business.brain.prediction_service import PredictionService

            self._prediction_service = PredictionService()
        return self._prediction_service

    def _get_llm_client(self):
        if self._llm_client is not None:
            return self._llm_client
        try:
            from src.business.ai.llm_client import LangChainLLMClient

            config = self._get_config()
            self._llm_client = LangChainLLMClient(
                provider=config.get_ai_provider(),
                model=config.get_ai_model(),
                api_key=config.get_ai_api_key(),
                base_url=config.get_ai_base_url(),
                temperature=0.7,
                thinking_level=config.get_ai_thinking_level(),
                timeout=config.get_ai_request_timeout(),
            )
            return self._llm_client
        except Exception as exc:
            logger.warning("Brain worker LLM client is unavailable: %s", exc)
            return None

    def start(self):
        """启动后台工作线程"""
        global _brain_worker_running, _brain_worker_event, _brain_worker_thread
        if _brain_worker_running:
            return

        _brain_worker_running = True
        _brain_worker_event = self._tick_event

        # 监听 segment boundary 事件来唤醒
        connect("segment_boundary_triggered", self._on_segment_boundary, weak=False)

        _brain_worker_thread = threading.Thread(
            target=self._worker_loop,
            daemon=True,
            name="brain-worker",
        )
        _brain_worker_thread.start()
        logger.info("BrainBackgroundWorker started")

    def stop(self):
        """停止后台工作线程"""
        global _brain_worker_running
        _brain_worker_running = False
        self._tick_event.set()
        logger.info("BrainBackgroundWorker stopping")

    def _on_segment_boundary(self, sender, **kwargs):
        """Segment 边界事件唤醒 worker"""
        self._tick_event.set()

    def _worker_loop(self):
        """工作线程主循环"""
        config = self._get_config()
        tick_interval = config.get_brain_worker_tick_interval()

        while _brain_worker_running:
            try:
                self._process_pending_segments()
                self._recover_crashed_segments()
                self._run_decay_sweep()
                self._run_archive_layering()
                self._run_prediction_jobs()
                self._run_subconscious_distillation()
                self._run_invalidation_review()
                self._run_recruitment_scan()
            except Exception as e:
                logger.error("Brain worker tick failed: %s", e, exc_info=True)

            self._tick_event.wait(timeout=tick_interval)
            self._tick_event.clear()

    def _process_pending_segments(self):
        """处理所有 pending segments"""
        try:
            from src.data.repos.brain_repository import BrainRepository

            repo = BrainRepository()
        except ImportError:
            return

        distillation = self._get_distillation_service()
        pending = repo.get_pending_segments()
        llm_client = self._get_llm_client()
        if llm_client is None:
            if pending:
                logger.warning(
                    "Brain worker found %d pending segment(s), but no LLM client is available",
                    len(pending),
                )
            return

        for segment in pending:
            if not _brain_worker_running:
                break
            segment_id = getattr(segment, "segment_id", "")
            retry_count = getattr(segment, "retry_count", 0)
            max_retries = self._get_config().get_brain_segment_max_distillation_retries()

            if retry_count >= max_retries:
                logger.warning(
                    "Segment %s exceeded max retries (%d), marking failed",
                    segment_id,
                    max_retries,
                )
                repo.transition_segment(
                    segment_id,
                    from_status="pending",
                    to_status="failed",
                )
                continue

            try:
                distillation.distill_segment(
                    segment_id,
                    llm_client=llm_client,
                    phase=self._distillation_phase,
                )
            except Exception as e:
                logger.error("Failed to distill segment %s: %s", segment_id, e)

    def _recover_crashed_segments(self):
        """恢复崩溃时处于 distilling 状态的 segments"""
        try:
            from src.data.repos.brain_repository import BrainRepository

            repo = BrainRepository()
        except ImportError:
            return

        distilling = repo.get_distilling_segments()
        for segment in distilling:
            segment_id = getattr(segment, "segment_id", "")
            logger.info("Crash recovery: resetting segment %s to pending", segment_id)
            repo.transition_segment(
                segment_id,
                from_status="distilling",
                to_status="pending",
            )

    def _run_decay_sweep(self):
        """热区衰减扫描：将低 relevance 的 active 条目转为 fading"""
        try:
            from src.business.brain.decay_router import DecayRouter

            router = DecayRouter()
            stats = router.run_decay_sweep()
            if stats and (stats.get("faded_count", 0) > 0 or stats.get("routed_to_archive", 0) > 0):
                logger.info("Decay sweep: %s", stats)
        except ImportError:
            pass
        except Exception as e:
            logger.error("Decay sweep failed: %s", e)

    def _run_archive_layering(self):
        """归档分层：聚合 unit 条目为时间层级摘要"""
        try:
            from src.business.brain.archive_service import ArchiveService

            service = ArchiveService()
            stats = service.run_layering_job()
            if stats and stats.get("day_layers_created", 0) > 0:
                logger.info("Archive layering: %s", stats)
        except ImportError:
            pass
        except Exception as e:
            logger.error("Archive layering failed: %s", e)

    def _run_prediction_jobs(self):
        """运行猜测生成和验证周期任务"""
        try:
            llm_client = self._get_llm_client()
            if llm_client is None:
                return
            service = self._get_prediction_service()
            generated = service.generate_predictions(llm_client)
            verified = service.verify_predictions(llm_client)
            if generated or verified:
                logger.info(
                    "Prediction jobs: generated=%d verified=%d",
                    len(generated),
                    verified,
                )
        except ImportError:
            pass
        except Exception as e:
            logger.error("Prediction jobs failed: %s", e)

    def _run_subconscious_distillation(self):
        """运行潜意识深层沉淀周期任务。"""
        try:
            llm_client = self._get_llm_client()
            if llm_client is None:
                return
            count = self._get_distillation_service().run_subconscious_distillation(llm_client)
            if count:
                logger.info("Subconscious distillation produced %d entries", count)
        except ImportError:
            pass
        except Exception as e:
            logger.error("Subconscious distillation failed: %s", e)

    def _run_invalidation_review(self):
        """运行失效记忆复审周期任务。"""
        try:
            from src.data.repos.brain_repository import BrainRepository

            reviewed = BrainRepository().apply_invalidation_review_decay()
            if reviewed:
                logger.info("Invalidation review degraded %d entries", reviewed)
        except ImportError:
            pass
        except Exception as e:
            logger.error("Invalidation review failed: %s", e)

    def _run_recruitment_scan(self):
        """扫描持续委托模式并自动招募专员 (T103)"""
        try:
            from src.business.brain.specialist_service import SpecialistService

            service = SpecialistService()
            recruited = service.scan_and_recruit()
            for specialist in recruited:
                specialist_id = specialist.get("specialist_id", "")
                name = specialist.get("name", "")
                reason = specialist.get("reason", "")
                from src.utils.events import emit

                emit(
                    "brain_specialist_recruited",
                    specialist_id=specialist_id,
                    name=name,
                    reason=reason,
                )
                logger.info(
                    "Auto-recruited specialist: %s (%s)",
                    name,
                    specialist_id,
                )
        except ImportError:
            pass
        except Exception as e:
            logger.error("Recruitment scan failed: %s", e)
