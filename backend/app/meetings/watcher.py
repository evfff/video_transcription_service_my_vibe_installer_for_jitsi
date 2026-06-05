"""
Meeting Watcher
Фоновый процесс мониторинга inbox-папки встреч.

Режим работы: polling (проверка каждые N секунд).
Для каждой новой встречи запускает MeetingPipeline в отдельном потоке.
"""
from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from .config import MeetingsConfig, load_meetings_config
from .ingestion import MeetingIngestionService
from .models import MeetingStatus, TERMINAL_STATUSES
from .pipeline import MeetingPipeline
from .storage import MeetingStorage

logger = logging.getLogger(__name__)

# Максимум одновременно обрабатываемых встреч
MAX_CONCURRENT = 2


class MeetingWatcher:
    """
    Фоновый мониторинг inbox + автоматический запуск pipeline.
    Thread-safe singleton через _instance.
    """

    _instance: Optional["MeetingWatcher"] = None
    _lock = threading.Lock()

    def __init__(self, config: Optional[MeetingsConfig] = None) -> None:
        self.config = config or load_meetings_config()
        self.storage = MeetingStorage(self.config.inbox_path)
        self.ingestion = MeetingIngestionService(self.config, self.storage)
        self.pipeline = MeetingPipeline(self.config, self.storage)

        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._executor = ThreadPoolExecutor(
            max_workers=MAX_CONCURRENT,
            thread_name_prefix="meeting_pipeline"
        )
        self._processing: set = set()  # meeting IDs currently in pipeline

    @classmethod
    def get_instance(cls) -> "MeetingWatcher":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    # ─── Start / Stop ─────────────────────────────────────────────────────────

    def start(self) -> None:
        """Запустить фоновый поток мониторинга"""
        if self._running:
            logger.info("[WATCHER] Уже запущен")
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._watch_loop,
            name="meeting_watcher",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            f"[WATCHER] ✓ Запущен (интервал: {self.config.polling_interval_sec}с, "
            f"inbox: {self.config.inbox_path})"
        )

    def stop(self) -> None:
        """Остановить фоновый поток"""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        self._executor.shutdown(wait=False)
        logger.info("[WATCHER] Остановлен")

    def is_running(self) -> bool:
        return self._running and (
            self._thread is not None and self._thread.is_alive()
        )

    # ─── Manual operations ────────────────────────────────────────────────────

    def scan_now(self) -> list:
        """Немедленно сканировать inbox и запустить новые встречи"""
        logger.info("[WATCHER] Ручное сканирование inbox...")
        new_meetings = self.ingestion.scan_inbox()
        for meeting in new_meetings:
            self._schedule_pipeline(meeting)
        return new_meetings

    def reprocess(self, meeting_id: str, from_stage: str = "start") -> bool:
        """Перезапустить pipeline для конкретной встречи"""
        meta = self.storage.load_by_id(meeting_id)
        if not meta:
            logger.warning(f"[WATCHER] Встреча не найдена: {meeting_id}")
            return False

        if meeting_id in self._processing:
            logger.warning(f"[WATCHER] Встреча уже обрабатывается: {meeting_id}")
            return False

        logger.info(
            f"[WATCHER] Повторная обработка: {meta.folder_name} "
            f"[from_stage={from_stage}]"
        )
        # Сбросить ошибки при перезапуске
        meta.stage_errors = {}
        meta.last_error = None
        self.storage.save(meta)

        self._schedule_pipeline(meta, from_stage=from_stage)
        return True

    # ─── Watch loop ───────────────────────────────────────────────────────────

    def _watch_loop(self) -> None:
        """Основной цикл мониторинга"""
        # Первый прогон сразу
        self._tick()
        while self._running:
            time.sleep(self.config.polling_interval_sec)
            if self._running:
                self._tick()

    def _tick(self) -> None:
        """Один тик мониторинга: сканирование + запуск pipeline для новых"""
        try:
            # 1. Обнаружение новых папок
            new_meetings = self.ingestion.scan_inbox()
            for meeting in new_meetings:
                self._schedule_pipeline(meeting)

            # 2. Подбор встреч в статусе QUEUED (могли остаться из прошлых запусков)
            all_meetings = self.storage.list_all()
            for meta in all_meetings:
                if (
                    meta.status == MeetingStatus.QUEUED
                    and meta.id not in self._processing
                ):
                    logger.info(f"[WATCHER] Подобрана из очереди: {meta.folder_name}")
                    self._schedule_pipeline(meta)
        except Exception as exc:
            logger.error(f"[WATCHER] Ошибка в tick: {exc}")

    def _schedule_pipeline(
        self,
        meta,
        from_stage: str = "start",
    ) -> None:
        """Отправить встречу в пул обработки"""
        if meta.id in self._processing:
            return
        self._processing.add(meta.id)
        self._executor.submit(
            self._run_pipeline_safe, meta, from_stage
        )

    def _run_pipeline_safe(self, meta, from_stage: str) -> None:
        """Запустить pipeline с защитой от исключений"""
        try:
            logger.info(f"[WATCHER] → Pipeline: {meta.folder_name}")
            self.pipeline.run(meta, from_stage=from_stage)
        except Exception as exc:
            logger.error(
                f"[WATCHER] Uncaught exception в pipeline {meta.folder_name}: {exc}",
                exc_info=True,
            )
            # Пытаемся сохранить статус failed
            try:
                meta.set_status(MeetingStatus.FAILED, str(exc))
                self.storage.save(meta)
            except Exception:
                pass
        finally:
            self._processing.discard(meta.id)


def get_watcher() -> MeetingWatcher:
    """Глобальный accessor для watcher singleton"""
    return MeetingWatcher.get_instance()
