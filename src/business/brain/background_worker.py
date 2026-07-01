"""
Brain Background Worker - daemon thread for pending Segment distillation, crash recovery,
hot-zone decay, archive layering, prediction jobs, subconscious distillation, invalidation
review, and specialist recruitment.
"""

import json
import logging
import os
import threading
from typing import Optional, Callable

from src.business.debug.context import TraceContext
from src.utils.events import connect, disconnect, emit

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
    """大脑后台工作线程，负责所有周期性 brain maintenance jobs。"""

    def __init__(
        self,
        config=None,
        distillation_service=None,
        prediction_service=None,
        llm_client=None,
        execution_review_service=None,
        execution_review_llm_client=None,
        distillation_phase: str = "p4",
    ):
        self._config = config
        self._distillation_service = distillation_service
        self._prediction_service = prediction_service
        self._llm_client = llm_client
        self._execution_review_service = execution_review_service
        self._execution_review_llm_client = execution_review_llm_client
        self._distillation_phase = distillation_phase
        self._tick_event = threading.Event()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._consecutive_tick_errors = 0
        self._llm_unavailable_logged_jobs: set[str] = set()

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
            from src.data.real_tour_audit import is_real_tour_runtime

            config = self._get_config()
            if (
                is_real_tour_runtime()
                and os.environ.get("MEXEMPLAR_REAL_GRAND_TOUR_ENABLE_BACKGROUND") != "1"
            ):
                logger.info("Brain worker LLM disabled during real-tour runtime")
                return None
            self._llm_client = LangChainLLMClient(
                provider=config.get_ai_provider(),
                model=config.get_ai_model(),
                api_key=config.get_ai_api_key(),
                base_url=config.get_ai_base_url(),
                temperature=0.7,
                max_tokens=config.get_ai_max_tokens(),
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
            self._consecutive_tick_errors = 0
            _brain_worker_running = True
            _brain_worker_event = self._tick_event

            # 监听 segment boundary 事件来唤醒；weak=False 防止 bound method 被 GC 回收
            connect("segment_boundary_triggered", self._on_segment_boundary, weak=False)

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
            disconnect("segment_boundary_triggered", self._on_segment_boundary)
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

        _JOBS = (
            "process_segments",
            "recover_crashes",
            "decay_sweep",
            "archive_layering",
            "prediction_jobs",
            "subconscious_distillation",
            "invalidation_review",
            "recruitment_scan",
            "execution_review",
        )
        _JOB_FNS = (
            self._process_pending_segments,
            self._recover_crashed_segments,
            self._run_decay_sweep,
            self._run_archive_layering,
            self._run_prediction_jobs,
            self._run_subconscious_distillation,
            self._run_invalidation_review,
            self._run_recruitment_scan,
            self._run_execution_review,
        )
        n_jobs = len(_JOBS)
        try:
            while not self._stop_event.is_set():
                tick_job_errors = 0
                for job_name, job_fn in zip(_JOBS, _JOB_FNS):
                    if self._stop_event.is_set():
                        break
                    try:
                        job_fn()
                    except KeyboardInterrupt:
                        logger.info("Brain worker interrupted, shutting down")
                        return
                    except Exception as e:
                        logger.error("Brain worker job %s failed: %s", job_name, e, exc_info=True)
                        tick_job_errors += 1

                if tick_job_errors >= n_jobs:
                    # 整个 tick 所有 job 均失败 → 累计连续失败计数，触发 cooldown
                    self._consecutive_tick_errors += 1
                    if self._consecutive_tick_errors >= 10:
                        logger.critical(
                            "Brain worker has failed %d consecutive ticks, entering cooldown",
                            self._consecutive_tick_errors,
                        )
                        tick_interval = min(tick_interval * 2, 3600)
                elif tick_job_errors > 0:
                    # 部分 job 失败 → worker 整体仍健康，重置计数，只记录警告
                    logger.warning(
                        "Brain worker tick: %d/%d jobs failed, worker remains healthy",
                        tick_job_errors,
                        n_jobs,
                    )
                    self._consecutive_tick_errors = 0
                    tick_interval = config.get_brain_worker_tick_interval()
                else:
                    self._consecutive_tick_errors = 0
                    tick_interval = config.get_brain_worker_tick_interval()

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
        except ImportError:
            return

        repo = BrainRepository()
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
        """恢复崩溃时卡在 distilling 状态超过阈值的 segments"""
        try:
            from src.business.brain.segment_service import SegmentService
        except ImportError:
            return
        threshold = self._get_config().get_brain_worker_tick_interval() * 3
        count = SegmentService().crash_reset_stale_segments(threshold_seconds=max(threshold, 60))
        if count:
            logger.info("Crash recovery: reset %d stale distilling segment(s) to pending", count)

    def _run_decay_sweep(self):
        """热区衰减扫描：将低 relevance 的 active 条目转为 fading"""
        try:
            from src.business.brain.decay_router import DecayRouter
        except ImportError:
            return
        router = DecayRouter()
        stats = router.run_decay_sweep()
        if stats and (stats.get("faded_count", 0) > 0 or stats.get("routed_to_archive", 0) > 0):
            logger.info("Decay sweep: %s", stats)

    def _run_archive_layering(self):
        """归档分层：聚合 unit 条目为时间层级摘要"""
        try:
            from src.business.brain.archive_service import ArchiveService
        except ImportError:
            return
        service = ArchiveService()
        stats = service.run_layering_job()
        if stats and stats.get("day_layers_created", 0) > 0:
            logger.info("Archive layering: %s", stats)

    def _run_prediction_jobs(self):
        """运行猜测生成和验证周期任务"""
        llm_client = self._get_llm_client()
        if llm_client is None:
            self._log_llm_skip_once("prediction jobs")
            return
        self._llm_unavailable_logged_jobs.discard("prediction jobs")
        service = self._get_prediction_service()
        generated = []
        verified = 0
        errors: list[Exception] = []
        try:
            with TraceContext(source="brain_prediction", agent_type="brain_worker"):
                generated = service.generate_predictions(llm_client)
        except Exception as exc:
            logger.error("Prediction generation failed: %s", exc, exc_info=True)
            errors.append(exc)
        if not errors:
            try:
                with TraceContext(
                    source="brain_prediction_verification", agent_type="brain_worker"
                ):
                    verified = service.verify_predictions(llm_client)
            except Exception as exc:
                logger.error("Prediction verification failed: %s", exc, exc_info=True)
                errors.append(exc)
        if generated or verified:
            logger.info(
                "Prediction jobs: generated=%d verified=%d",
                len(generated),
                verified,
            )
        if errors:
            detail = "; ".join(f"{type(error).__name__}: {error}" for error in errors)
            raise RuntimeError(f"prediction jobs failed: {detail}") from errors[0]

    def _run_subconscious_distillation(self):
        """运行潜意识深层沉淀周期任务。"""
        llm_client = self._get_llm_client()
        if llm_client is None:
            self._log_llm_skip_once("subconscious distillation")
            return
        self._llm_unavailable_logged_jobs.discard("subconscious distillation")
        with TraceContext(source="brain_subconscious", agent_type="brain_worker"):
            count = self._get_distillation_service().run_subconscious_distillation(llm_client)
        if count:
            logger.info("Subconscious distillation produced %d entries", count)

    def _run_invalidation_review(self):
        """运行失效记忆复审周期任务。"""
        try:
            from src.data.repos.brain_repository import BrainRepository
        except ImportError:
            return
        with BrainRepository() as repo:
            reviewed = repo.apply_invalidation_review_decay()
            if reviewed:
                logger.info("Invalidation review degraded %d entries", reviewed)

    def _log_llm_skip_once(self, job_name: str) -> None:
        if job_name in self._llm_unavailable_logged_jobs:
            return
        self._llm_unavailable_logged_jobs.add(job_name)
        logger.warning("Brain worker skipped %s because no LLM client is available", job_name)

    def _run_recruitment_scan(self):
        """扫描持续委托模式并自动招募专员。"""
        try:
            from src.business.brain.specialist_service import SpecialistService
        except ImportError:
            return

        service = SpecialistService()
        recruited = service.scan_and_recruit()
        for specialist in recruited:
            specialist_id = specialist.get("specialist_id", "")
            name = specialist.get("name", "")
            reason = specialist.get("reason", "")
            emit(
                "brain_specialist_recruited",
                specialist_id=specialist_id,
                name=name,
                reason=reason,
            )
            logger.info("Auto-recruited specialist: %s (%s)", name, specialist_id)

    def _get_execution_review_service(self):
        if self._execution_review_service is None:
            from src.business.self_improvement.execution_review_service import (
                ExecutionReviewService,
            )

            self._execution_review_service = ExecutionReviewService()
        return self._execution_review_service

    def _maybe_generate_proposals(self, review_id: str, findings: list) -> None:
        """旁路调用 ProposalService 从 worth_changing findings 生成提案。

        不改 A 的只读语义；生成失败不阻塞复盘写回。
        """
        try:
            config = self._get_config()
            if not config.get_self_improvement_proposals_enabled():
                return
            from src.business.self_improvement.proposal_service import ProposalService

            # findings 已是解析后的 list[dict]（来自 review report），原样传入；
            # 切勿 json.dumps 成 str——generate_from_review 会 enumerate 每个 finding
            # 调 .get，收到 str 会抛 AttributeError 被本 except 吞掉，提案永不生成。
            ProposalService().generate_from_review(review_id, findings)
        except Exception as exc:
            # 复盘已写回，提案生成失败不应阻塞它；但必须留 ERROR 级痕迹（带 review_id
            # 与 findings 数量），避免一次偶发异常静默吞掉一批提案却无任何可观测信号。
            logger.error(
                "Proposal generation failed for review %s (%d findings): %s",
                review_id,
                len(findings),
                exc,
                exc_info=True,
            )

    def _retry_missing_proposals_for_recent_reviews(self, *, limit: int = 20) -> None:
        """幂等重扫最近完成的复盘，补偿提案生成旁路的短暂失败。"""
        try:
            config = self._get_config()
            if not config.get_self_improvement_proposals_enabled():
                return
            from src.data.repos.execution_review_repository import ExecutionReviewRepository

            with ExecutionReviewRepository() as repo:
                reviews = repo.list_recent(limit)
            for review in reviews:
                try:
                    findings = json.loads(review.findings_json or "[]")
                except (TypeError, ValueError):
                    logger.warning(
                        "Cannot retry proposal generation for review %s: invalid findings JSON",
                        review.id,
                        exc_info=True,
                    )
                    continue
                if isinstance(findings, list):
                    self._maybe_generate_proposals(review.id, findings)
        except Exception:
            logger.error("Proposal generation retry scan failed", exc_info=True)

    def _get_execution_review_llm_client(self):
        if self._execution_review_llm_client is not None:
            return self._execution_review_llm_client
        try:
            from src.business.ai.llm_client import LangChainLLMClient
            from src.data.real_tour_audit import is_real_tour_runtime

            if (
                is_real_tour_runtime()
                and os.environ.get("MEXEMPLAR_REAL_GRAND_TOUR_ENABLE_BACKGROUND") != "1"
            ):
                logger.info("Execution review LLM disabled during real-tour runtime")
                return None

            config = self._get_config()
            model_config = config.get_self_improvement_execution_review_model()
            provider = model_config.get("provider") or config.get_ai_provider()
            model = model_config.get("model") or config.get_ai_model()
            api_key = model_config.get("api_key") or config.get_ai_api_key()
            base_url = model_config.get("base_url", config.get_ai_base_url())
            temperature = float(model_config.get("temperature", 0.2))
            max_tokens = int(model_config.get("max_tokens", min(config.get_ai_max_tokens(), 4000)))
            thinking_level = model_config.get("thinking_level") or config.get_ai_thinking_level()
            timeout = model_config.get("timeout", config.get_ai_request_timeout())
            self._execution_review_llm_client = LangChainLLMClient(
                provider=provider,
                model=model,
                api_key=api_key,
                base_url=base_url,
                temperature=temperature,
                max_tokens=max_tokens,
                thinking_level=thinking_level,
                timeout=timeout,
                audit_source="execution_review",
            )
            return self._execution_review_llm_client
        except Exception as exc:
            logger.warning("Execution review LLM client is unavailable: %s", exc)
            return None

    def _run_execution_review(self):
        """处理待复盘执行队列；单条失败不影响其它报告。"""
        config = self._get_config()
        if not config.get_self_improvement_execution_review_enabled():
            return

        self._retry_missing_proposals_for_recent_reviews()

        from src.business.self_improvement.execution_trace_builder import build_skeleton
        from src.data.repos.execution_review_repository import ExecutionReviewRepository
        from src.data.repos.message_repository import MessageRepository

        llm_client = self._get_execution_review_llm_client()
        if llm_client is None:
            self._log_llm_skip_once("execution review")
            return
        self._llm_unavailable_logged_jobs.discard("execution review")

        with ExecutionReviewRepository() as repo, MessageRepository() as message_repo:
            for review in repo.claim_pending(limit=3):
                try:
                    skeleton = build_skeleton(review.turn_session_id, message_repo)
                    report = self._get_execution_review_service().review(
                        skeleton,
                        llm_client=llm_client,
                    )
                    repo.save_result(
                        review.id,
                        verdict=str(report.get("verdict") or ""),
                        findings=list(report.get("findings") or []),
                        model_used=getattr(llm_client, "model", "")
                        or getattr(llm_client, "model_name", "")
                        or "",
                    )
                    # 旁路：从 worth_changing findings 生成改进提案。proposal 生成自带
                    # try/except,这里再防御一层确保零外抛——CC-004 要求 proposal 异常
                    # 不得进入 review except 把复盘标 failed 或把 str(exc) 写入 reviews。
                    try:
                        self._maybe_generate_proposals(
                            review.id, list(report.get("findings") or [])
                        )
                    except Exception:
                        logger.error(
                            "Proposal generation raised unexpectedly for review %s (swallowed)",
                            review.id,
                            exc_info=True,
                        )
                except Exception as exc:
                    logger.warning("Execution review failed for %s: %s", review.id, exc)
                    repo.mark_failed(review.id, str(exc))
