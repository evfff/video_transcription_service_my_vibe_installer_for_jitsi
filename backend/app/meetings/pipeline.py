"""
Meeting Pipeline
Оркестрирует полный цикл обработки одной встречи.

Этапы:
  1. extracting_audio   → MediaProcessingService
  2. transcribing       → TranscriptionService
  3. diarizing          → DiarizationService (опционально)
  4. analyzing          → MeetingAnalysisService
  5. generating_documents → MeetingDocumentService
  6. exporting_to_obsidian → ObsidianExportService

Принципы надёжности:
- При падении одного этапа следующие продолжают работать (если возможно)
- Ошибки записываются в meta.stage_errors
- Итоговый статус: completed / partial_completed / failed
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Optional

from .config import MeetingsConfig
from .models import MeetingMeta, MeetingStatus
from .storage import MeetingStorage
from .media import MediaProcessingService
from .transcription import TranscriptionService
from .diarization import DiarizationService
from .analysis import MeetingAnalysisService
from .documents import MeetingDocumentService
from .obsidian import ObsidianExportService

logger = logging.getLogger(__name__)

_INVALID_PATH_CHARS = re.compile(r'[\\/:*?"<>|]')


def _make_obsidian_folder_name(meta: MeetingMeta) -> str:
    """Compose Obsidian folder name: '{title} {date}' sanitized for filesystem."""
    title = (meta.title or "").strip()
    # Extract date part from folder_name e.g. '2026-04-02'
    date_part = ""
    m = re.search(r'(\d{4}-\d{2}-\d{2})', meta.folder_name or "")
    if m:
        date_part = m.group(1)
    if title:
        raw = f"{title} {date_part}".strip() if date_part else title
    else:
        raw = meta.folder_name or date_part or "meeting"
    sanitized = _INVALID_PATH_CHARS.sub("", raw).strip()
    return sanitized or meta.folder_name


class MeetingPipeline:
    """
    Полный pipeline обработки встречи.
    """

    def __init__(
        self,
        config: MeetingsConfig,
        storage: MeetingStorage,
    ) -> None:
        self.config = config
        self.storage = storage
        self.media = MediaProcessingService(config)
        self.transcription = TranscriptionService(config)
        self.diarization = DiarizationService(config)
        self.analysis = MeetingAnalysisService(config)
        self.documents = MeetingDocumentService()
        self.obsidian = ObsidianExportService(config)

    def run(
        self,
        meta: MeetingMeta,
        from_stage: str = "start",
    ) -> MeetingMeta:
        """
        Запустить pipeline обработки встречи.
        
        Args:
            meta: Текущие метаданные встречи
            from_stage: С какого этапа начать (start|transcription|analysis|documents|obsidian)
        
        Returns:
            Обновлённый MeetingMeta после всех этапов.
        """
        logger.info(
            f"[PIPELINE] Начало обработки: {meta.folder_name} "
            f"[id={meta.id}, from_stage={from_stage}]"
        )

        meta.set_status(MeetingStatus.PROCESSING)
        from datetime import datetime
        meta.started_at = datetime.now().isoformat()
        meta.cancel_requested = False
        self._cleanup_artifacts_for_stage(meta, from_stage)
        self.storage.save(meta)

        try:
            return self._run_stages(meta, from_stage)
        except InterruptedError:
            logger.info(f"[PIPELINE] Отменено: {meta.folder_name}")
            meta.set_status(MeetingStatus.FAILED, "Отменено пользователем")
            meta.progress_pct = 0
            meta.progress_detail = None
            meta.finished_at = datetime.now().isoformat()
            self.storage.save(meta)
            return meta

    def _run_stages(self, meta: MeetingMeta, from_stage: str) -> MeetingMeta:
        """Внутренний метод: все стадии pipeline."""
        from datetime import datetime

        artifacts_dir = self.storage.get_artifacts_dir(meta.folder_name)
        source_dir = self.storage.get_source_dir(meta.folder_name)
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        # Полные пути к исходным файлам
        source_paths = [
            str(source_dir / f) for f in meta.source_files
            if (source_dir / f).exists()
        ]
        if not source_paths:
            # Файлы могут лежать не в source/, ищем по имени
            source_paths = meta.source_files

        # ── ЭТАП 1: Извлечение аудио ──────────────────────────────────────────
        transcript = None
        analysis = None
        audio_path: Optional[Path] = None

        if from_stage in ("start",):
            meta.progress_pct = 5
            meta.progress_detail = "Извлечение аудио…"
            self.storage.save(meta)
            audio_path = self._stage_extract_audio(meta, source_paths, artifacts_dir)
        else:
            # Ищем уже извлечённый файл
            candidate = artifacts_dir / "audio.wav"
            if candidate.exists():
                audio_path = candidate
                meta.audio_extracted = True

        # ── ЭТАП 2: Транскрибация (только Whisper) ───────────────────────────
        self._check_cancel(meta)
        if from_stage in ("start", "transcription") and audio_path:
            meta.progress_pct = 10
            meta.progress_detail = "Транскрипция аудио…"
            self.storage.save(meta)
            transcript = self._stage_transcribe(meta, audio_path, artifacts_dir)
        else:
            transcript = self._load_saved_transcript(artifacts_dir)

        # ── ЭТАП 3: Диаризация (всегда ДО анализа) ───────────────────────────
        self._check_cancel(meta)
        if from_stage in ("start", "transcription", "diarization") and audio_path and transcript:
            meta.progress_pct = 40
            meta.progress_detail = "Определение спикеров…"
            self.storage.save(meta)
            transcript = self._stage_diarize_only(meta, audio_path, transcript, artifacts_dir)
        elif (
            from_stage == "analysis"
            and audio_path
            and transcript
            and not transcript.has_speakers
            and self.diarization.is_available()
        ):
            # При запуске анализа: если спикеры ещё не определены — диаризуем сначала
            logger.info("[PIPELINE] Анализ: спикеры не определены — запускаем диаризацию перед LLM")
            meta.progress_pct = 40
            meta.progress_detail = "Определение спикеров…"
            self.storage.save(meta)
            transcript = self._stage_diarize_only(meta, audio_path, transcript, artifacts_dir)

        # ── ЭТАП 4: LLM Анализ ────────────────────────────────────────────────
        self._check_cancel(meta)
        if from_stage in ("start", "transcription", "diarization", "analysis") and transcript:
            meta.progress_pct = 55
            meta.progress_detail = "LLM анализ…"
            self.storage.save(meta)
            analysis = self._stage_analyze(meta, transcript, artifacts_dir)
        else:
            analysis = self._load_saved_analysis(artifacts_dir)

        # ── ЭТАП 5: Генерация документов ───────────────────────────────────────
        meeting_note_path: Optional[Path] = None
        if from_stage in ("start", "transcription", "diarization", "analysis", "documents"):
            meta.progress_pct = 90
            meta.progress_detail = "Генерация документов…"
            self.storage.save(meta)
            meeting_note_path = self._stage_generate_docs(
                meta, transcript, analysis, artifacts_dir
            )
        else:
            candidate = artifacts_dir / "meeting_note.md"
            if candidate.exists():
                meeting_note_path = candidate

        # ── ЭТАП 6: Экспорт в Obsidian ────────────────────────────────────────
        if from_stage in ("start", "transcription", "diarization", "analysis", "documents", "obsidian"):
            meta.progress_pct = 95
            meta.progress_detail = "Экспорт в Obsidian…"
            self.storage.save(meta)
            self._stage_export_obsidian(meta, meeting_note_path, transcript=transcript, analysis=analysis)

        # ── Финальный статус ──────────────────────────────────────────────────
        meta.progress_pct = 100
        meta.progress_detail = None
        meta.finished_at = datetime.now().isoformat()
        self._finalize_status(meta)
        self.storage.save(meta)

        self._fire_webhook(meta)

        logger.info(
            f"[PIPELINE] ✓ Обработка завершена: {meta.folder_name} → {meta.status}"
        )
        return meta

    def cancel(self, meta: MeetingMeta) -> None:
        """Установить флаг отмены. Pipeline остановится между стадиями."""
        meta.cancel_requested = True
        self.storage.save(meta)
        logger.info(f"[PIPELINE] Запрошена отмена: {meta.folder_name}")

    def _fire_webhook(self, meta: MeetingMeta) -> None:
        """Отправить POST-уведомление на webhook_url если настроен."""
        url = (self.config.webhook_url or "").strip()
        if not url:
            return
        allowed = [s.lower() for s in self.config.webhook_on_status]
        if meta.status.value.lower() not in allowed and "all" not in allowed:
            return
        try:
            import httpx as _httpx
            payload = {
                "event": "meeting.finished",
                "meeting_id": meta.id,
                "folder_name": meta.folder_name,
                "title": meta.title,
                "status": meta.status.value,
                "task_count": meta.task_count,
                "duration_sec": meta.duration_sec,
                "obsidian_folder": meta.obsidian_folder,
                "finished_at": meta.finished_at,
            }
            with _httpx.Client(timeout=10.0) as client:
                resp = client.post(url, json=payload)
                resp.raise_for_status()
            logger.info(f"[PIPELINE] Webhook отправлен → {url} (HTTP {resp.status_code})")
        except Exception as exc:
            logger.warning(f"[PIPELINE] Webhook не удался ({url}): {exc}")

    # ─── Stages ───────────────────────────────────────────────────────────────

    def _check_cancel(self, meta: MeetingMeta) -> None:
        """Поднять исключение если запрошена отмена. Перечитываем meta с диска."""
        fresh = self.storage.load_by_id(meta.id)
        if fresh and fresh.cancel_requested:
            meta.cancel_requested = True
            raise InterruptedError("Pipeline отменён пользователем")

    def _cleanup_artifacts_for_stage(self, meta: MeetingMeta, from_stage: str) -> None:
        """Удалить артефакты стадий, которые будут перезапущены, чтобы не оставлять устаревшие файлы."""
        import shutil as _shutil
        artifacts_dir = self.storage.get_artifacts_dir(meta.folder_name)
        if not artifacts_dir.exists():
            return

        # Маппинг: стадия → файлы которые она производит
        _stage_artifacts: dict = {
            "start":         ["audio.wav", "audio.mp3"],
            "transcription": ["transcript.json", "transcript.md"],
            "diarization":   [],  # перезаписывает transcript.json — не удаляем заранее
            "analysis":      ["analysis.json", "summary.md", "tasks.json"],
            "documents":     ["meeting_note.md"],
            "obsidian":      [],  # управляет отдельно через ObsidianExportService
        }

        stage_order = ["start", "transcription", "diarization", "analysis", "documents", "obsidian"]
        if from_stage not in stage_order:
            return
        idx = stage_order.index(from_stage)
        stages_to_clean = stage_order[idx:]

        cleaned: list[str] = []
        for stage in stages_to_clean:
            for fname in _stage_artifacts.get(stage, []):
                fpath = artifacts_dir / fname
                if fpath.exists():
                    try:
                        fpath.unlink()
                        cleaned.append(fname)
                    except Exception as exc:
                        logger.warning(f"[PIPELINE] Не удалось удалить артефакт {fname}: {exc}")

        if cleaned:
            logger.info(f"[PIPELINE] Очистка артефактов ({from_stage}→): {', '.join(cleaned)}")

    def _stage_extract_audio(
        self,
        meta: MeetingMeta,
        source_paths: list[str],
        artifacts_dir: Path,
    ) -> Optional[Path]:
        meta.set_status(MeetingStatus.EXTRACTING_AUDIO)
        self.storage.save(meta)

        try:
            audio_out = artifacts_dir / "audio"
            audio_path = self.media.extract_audio(source_paths, audio_out)
            if audio_path:
                meta.audio_extracted = True
                meta.audio_path = str(audio_path)
                meta.duration_sec = self.media.get_audio_duration(audio_path)
                logger.info(f"[PIPELINE] ✓ Аудио: {audio_path.name} ({meta.duration_sec:.0f}с)")
                return audio_path
            else:
                meta.stage_errors["audio"] = "ffmpeg вернул None"
                return None
        except Exception as exc:
            err = str(exc)
            logger.error(f"[PIPELINE] Ошибка извлечения аудио: {err}")
            meta.stage_errors["audio"] = err
            meta.audio_extracted = False
            return None

    def _stage_transcribe(
        self,
        meta: MeetingMeta,
        audio_path: Path,
        artifacts_dir: Path,
    ):
        meta.set_status(MeetingStatus.TRANSCRIBING)
        self.storage.save(meta)

        try:
            transcript = self.transcription.transcribe(audio_path)
            self.transcription.save_transcript(transcript, artifacts_dir)
            meta.transcript_status = "done"
            meta.transcript_path = str(artifacts_dir / "transcript.json")
            meta.language = transcript.language
            # Вычисляем временной интервал встречи из имени папки + длительностью (UTC+3 МСК)
            from .documents import _parse_folder_datetime, _MSK_OFFSET
            from datetime import timedelta
            start_dt = _parse_folder_datetime(meta.folder_name)
            if start_dt and transcript.duration_sec:
                start_msk = start_dt + _MSK_OFFSET
                end_msk = start_msk + timedelta(seconds=transcript.duration_sec)
                meta.meeting_start_at = start_msk.isoformat()
                meta.meeting_end_at = end_msk.isoformat()
                meta.duration_sec = transcript.duration_sec

            return transcript
        except Exception as exc:
            err = str(exc)
            logger.error(f"[PIPELINE] Ошибка транскрибации: {err}")
            meta.stage_errors["transcription"] = err
            meta.transcript_status = "failed"
            return None

    def _stage_analyze(
        self,
        meta: MeetingMeta,
        transcript,
        artifacts_dir: Path,
    ):
        meta.set_status(MeetingStatus.ANALYZING)
        self.storage.save(meta)

        def _progress(chunk_i: int, chunk_total: int) -> None:
            # 55% → 88% mapped across chunks
            pct = 55 + int(33 * chunk_i / max(chunk_total, 1))
            meta.progress_pct = pct
            meta.progress_detail = f"LLM анализ: чанк {chunk_i}/{chunk_total}"
            self.storage.save(meta)

        try:
            title = meta.title or meta.folder_name
            analysis = self.analysis.analyze(meta.id, title, transcript, progress_cb=_progress)
            self.analysis.save_analysis(analysis, artifacts_dir)
            meta.analysis_status = "done"
            meta.analysis_path = str(artifacts_dir / "analysis.json")
            meta.task_count = len(analysis.tasks)
            if analysis.title:
                meta.title = analysis.title
            return analysis
        except Exception as exc:
            err = str(exc)
            logger.error(f"[PIPELINE] Ошибка анализа: {err}")
            meta.stage_errors["analysis"] = err
            meta.analysis_status = "failed"
            return None

    def _stage_generate_docs(
        self,
        meta: MeetingMeta,
        transcript,
        analysis,
        artifacts_dir: Path,
    ) -> Optional[Path]:
        meta.set_status(MeetingStatus.GENERATING_DOCUMENTS)
        self.storage.save(meta)

        try:
            content = self.documents.build_meeting_note(meta, transcript, analysis)
            note_path = self.documents.save_meeting_note(content, artifacts_dir)
            meta.documents_status = "done"
            meta.meeting_note_path = str(note_path)
            return note_path
        except Exception as exc:
            err = str(exc)
            logger.error(f"[PIPELINE] Ошибка генерации документов: {err}")
            meta.stage_errors["documents"] = err
            meta.documents_status = "failed"
            return None

    def _stage_diarize_only(
        self,
        meta: MeetingMeta,
        audio_path: Path,
        transcript,
        artifacts_dir: Path,
    ):
        """Запустить диаризацию на уже существующем транскрипте (без повторного Whisper)."""
        if not self.diarization.is_available():
            logger.info("[PIPELINE] Диаризация недоступна — пропуск")
            meta.diarization_status = "skipped"
            return transcript

        meta.set_status(MeetingStatus.DIARIZING)
        self.storage.save(meta)

        try:
            enriched = self.diarization.diarize(audio_path, transcript)
            if not enriched.has_speakers:
                # diarize() вернул исходный транскрипт без спикеров — значит ошибка
                err = getattr(enriched, "_diarization_error", None) or "Диаризация вернула 0 спикеров (возможно, 403 на HuggingFace — нужно принять условия модели)"
                logger.error(f"[PIPELINE] Диаризация не дала результата: {err}")
                meta.diarization_status = "failed"
                meta.stage_errors["diarization"] = err
                return transcript
            meta.diarization_status = "done"
            meta.speaker_count = len(
                set(s.speaker for s in enriched.segments if s.speaker)
            )
            self.transcription.save_transcript(enriched, artifacts_dir)
            logger.info(
                f"[PIPELINE] ✓ Диаризация: {meta.speaker_count} спикеров"
            )
            return enriched
        except Exception as exc:
            err = str(exc)
            logger.error(f"[PIPELINE] Ошибка диаризации: {err}")
            meta.stage_errors["diarization"] = err
            meta.diarization_status = "failed"
            return transcript

    def _stage_export_obsidian(
        self,
        meta: MeetingMeta,
        meeting_note_path: Optional[Path],
        transcript=None,
        analysis=None,
    ) -> None:
        meta.set_status(MeetingStatus.EXPORTING_TO_OBSIDIAN)
        self.storage.save(meta)

        try:
            documents = {
                "резюме.md": self.documents.build_summary_md(meta, analysis),
                "транскрипт.md": self.documents.build_transcript_md(meta, transcript),
                "задачи.md": self.documents.build_tasks_md(meta, analysis),
                "заметки.md": self.documents.build_notes_md(meta, analysis),
            }
            obsidian_folder = _make_obsidian_folder_name(meta)
            old_obsidian_folder = meta.obsidian_folder or meta.folder_name
            meta.obsidian_folder = obsidian_folder
            success = self.obsidian.export_folder(
                obsidian_folder, documents, meta.id,
                old_folder_name=old_obsidian_folder if old_obsidian_folder != obsidian_folder else None,
            )
            meta.obsidian_status = "done" if success else "failed"
            if not success and self.config.obsidian_export_enabled:
                meta.stage_errors["obsidian"] = "Экспорт не удался"
        except Exception as exc:
            err = str(exc)
            logger.error(f"[PIPELINE] Ошибка экспорта в Obsidian: {err}")
            meta.stage_errors["obsidian"] = err
            meta.obsidian_status = "failed"

    # ─── Helpers ──────────────────────────────────────────────────────────────

    def _finalize_status(self, meta: MeetingMeta) -> None:
        """Определить итоговый статус на основе результатов этапов"""
        critical_failed = (
            not meta.audio_extracted
            and meta.transcript_status != "done"
        )
        if critical_failed:
            meta.status = MeetingStatus.FAILED
            return

        has_any_error = bool(meta.stage_errors)
        if meta.transcript_status == "done":
            if has_any_error:
                meta.status = MeetingStatus.PARTIAL_COMPLETED
            else:
                meta.status = MeetingStatus.COMPLETED
        else:
            meta.status = MeetingStatus.FAILED

    def _load_saved_transcript(self, artifacts_dir: Path):
        """Загрузить сохранённый транскрипт из artifacts/"""
        from .models import TranscriptResult
        json_path = artifacts_dir / "transcript.json"
        if not json_path.exists():
            return None
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return TranscriptResult(**data)
        except Exception as exc:
            logger.warning(f"[PIPELINE] Не удалось загрузить transcript.json: {exc}")
            return None

    def _load_saved_analysis(self, artifacts_dir: Path):
        """Загрузить сохранённый анализ из artifacts/"""
        from .models import AnalysisResult
        json_path = artifacts_dir / "analysis.json"
        if not json_path.exists():
            return None
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return AnalysisResult(**data)
        except Exception as exc:
            logger.warning(f"[PIPELINE] Не удалось загрузить analysis.json: {exc}")
            return None
