"""
Brain Background Worker - daemon thread 处理 pending segments、崩溃恢复等周期任务
"""

import logging
import os
import threading
from typing import Optional, Callable

from src.business.debug.context import TraceContext
from src.utils.events import connect

logger = logging.getLogger(__name__)

_brain_worker_running = False
_brain_worker_event: Optional[threading.Event] = None
_brain_worker_thread: Optional[threading.Thread] = None
_brain_worker_notify: Optional[Callable] = None
_brain_worker_lock = threading.Lock()


def register_brain_worker_notify(callback: Callable):
    """注册 worker 唤醒回调"""
    global _brain_worker_notify
    _brain_worker_notify = callback


def notify_brain_worker():
    """唤醒 worker 立即处理"""
    with _brain_worker_lock:
        event = _brain_worker_event
    if event is not None:
        event.set()


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
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
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
            from src.data.credential_resolver import (
                get_real_tour_credential_resolver,
                is_real_tour_runtime,
            )

            config = self._get_config()
            if (
                is_real_tour_runtime()
                and os.environ.get("MEXEMPLAR_REAL_GRAND_TOUR_ENABLE_BACKGROUND") != "1"
            ):
                logger.info("Brain worker LLM disabled during real-tour runtime")
                return None
            resolver = get_real_tour_credential_resolver() if is_real_tour_runtime() else None
            api_key = resolver.get_ai_api_key() if resolver is not None else config.get_ai_api_key()
            self._llm_client = LangChainLLMClient(
                provider=config.get_ai_provider(),
                model=config.get_ai_model(),
                api_key=api_key,
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
        with _brain_worker_lock:
            if _brain_worker_thread is not None and _brain_worker_thread.is_alive():
                return
            self._stop_event.clear()
            self._tick_event.clear()
            _brain_worker_running = True
            _brain_worker_event = self._tick_event

            # 监听 segment boundary 事件来唤醒
            connect("segment_boundary_triggered", self._on_segment_boundary)

            self._thread = threading.Thread(
                target=self._worker_loop,
                daemon=True,
                name="brain-worker",
            )
            _brain_worker_thread = self._thread
            self._running = True
            self._thread.start()
            logger.info("BrainBackgroundWorker started")

    def stop(self):
        """停止后台工作线程"""
        with _brain_worker_lock:
            thread = self._thread
            self._stop_event.set()
        self._tick_event.set()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5)
            if thread.is_alive():
                logger.warning("BrainBackgroundWorker is still stopping; restart remains blocked")
        logger.info("BrainBackgroundWorker stopping")

    def _on_segment_boundary(self, sender, **kwargs):
        """Segment 边界事件唤醒 worker"""
        self._tick_event.set()

    def _worker_loop(self):
        """工作线程主循环"""
        global _brain_worker_running, _brain_worker_event, _brain_worker_thread
        config = self._get_config()
        tick_interval = config.get_brain_worker_tick_interval()

        try:
            while not self._stop_event.is_set():
                try:
                    self._process_pending_segments()
                    self._recover_crashed_segments()
                    self._run_decay_sweep()
                    self._run_archive_layering()
                    self._run_prediction_jobs()
                    self._run_subconscious_distillation()
                    self._run_invalidation_review()
                    self._run_recruitment_scan()
                except KeyboardInterrupt:
                    logger.info("Brain worker interrupted, shutting down")
                    break
                except Exception as e:
                    logger.error("Brain worker tick failed: %s", e, exc_info=True)
                    self._consecutive_tick_errors = getattr(self, "_consecutive_tick_errors", 0) + 1
                    if self._consecutive_tick_errors >= 10:
                        logger.critical(
                            "Brain worker has failed %d consecutive ticks, entering cooldown",
                            self._consecutive_tick_errors,
                        )
                        tick_interval = min(tick_interval * 2, 3600)
                else:
                    self._consecutive_tick_errors = 0

                self._tick_event.wait(timeout=tick_interval)
                self._tick_event.clear()
        finally:
            with _brain_worker_lock:
                if _brain_worker_thread is threading.current_thread():
                    _brain_worker_running = False
                    _brain_worker_event = None
                    _brain_worker_thread = None
                self._running = False

    def _process_pending_segments(self):
        """处理所有 pending segments"""
        try:
            from src.data.repos.brain_repository import BrainRepository

            repo = BrainRepository()
        except ImportError:
            return

        try:
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
                if self._stop_event.is_set():
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
                    with TraceContext(
                        source="brain_distillation",
                        agent_type="brain_worker",
                        work_unit_id=str(segment_id),
                    ):
                        distillation.distill_segment(
                            segment_id,
                            llm_client=llm_client,
                            phase=self._distillation_phase,
                        )
                except Exception as e:
                    logger.error("Failed to distill segment %s: %s", segment_id, e)
                    self._record_unhandled_distillation_failure(
                        repo,
                        segment,
                        initial_retry_count=retry_count,
                        max_retries=max_retries,
                    )
        finally:
            repo.close()

    @staticmethod
    def _record_unhandled_distillation_failure(
        repo,
        segment,
        *,
        initial_retry_count: int,
        max_retries: int,
    ) -> None:
        """Ensure a service exception consumes retry budget instead of spinning forever."""
        segment_id = getattr(segment, "segment_id", "")
        current = repo.get_segment(segment_id)
        if current is None:
            return
        status = getattr(current, "status", "")
        retry_count = int(getattr(current, "retry_count", 0) or 0)
        if status in {"completed", "failed"} or retry_count > initial_retry_count:
            return
        if retry_count + 1 >= max_retries:
            repo.transition_segment(segment_id, from_status=status, to_status="failed")
        elif status == "distilling":
            repo.retry_distilling_segment(segment_id)
        elif status == "pending":
            repo.increment_retry_count(segment_id)

    def _recover_crashed_segments(self):
        """恢复崩溃时处于 distilling 状态的 segments"""
        try:
            from src.data.repos.brain_repository import BrainRepository

            repo = BrainRepository()
        except ImportError:
            return

        try:
            distilling = repo.get_distilling_segments()
            for segment in distilling:
                segment_id = getattr(segment, "segment_id", "")
                logger.info("Crash recovery: resetting segment %s to pending", segment_id)
                repo.transition_segment(
                    segment_id,
                    from_status="distilling",
                    to_status="pending",
                )
        finally:
            repo.close()

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
            with TraceContext(source="brain_prediction", agent_type="brain_worker"):
                generated = service.generate_predictions(llm_client)
            with TraceContext(source="brain_prediction_verification", agent_type="brain_worker"):
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
            with TraceContext(source="brain_subconscious", agent_type="brain_worker"):
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

            with BrainRepository() as repo:
                reviewed = repo.apply_invalidation_review_decay()
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
