"""
Transcription Service
Отвечает за:
- запуск faster-whisper на аудиофайле
- получение сегментов с таймкодами
- сохранение transcript.json и transcript.md
- поддержка VAD-фильтрации
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import List, Optional

from .config import MeetingsConfig
from .models import TranscriptResult, TranscriptSegment

logger = logging.getLogger(__name__)


class TranscriptionService:
    """
    Транскрибация аудио через faster-whisper.
    Переиспользует WhisperEngine singleton из stt-модуля.
    """

    def __init__(self, config: MeetingsConfig) -> None:
        self.config = config
        self._engine = None

    def _get_engine(self):
        """Ленивая загрузка Whisper движка"""
        if self._engine is None:
            try:
                from stt.whisper_engine import whisper_engine
                self._engine = whisper_engine
                # Загружаем нужную модель (может отличаться от дефолтной small)
                self._engine.load_model(
                    model_name=self.config.whisper_model,
                    device=self.config.device,
                    compute_type=self.config.compute_type,
                )
            except Exception as exc:
                logger.error(f"[TRANSCRIBE] Ошибка инициализации Whisper: {exc}")
                raise
        return self._engine

    def transcribe(self, audio_path: Path) -> TranscriptResult:
        """
        Транскрибировать аудиофайл.
        Возвращает TranscriptResult с сегментами и полным текстом.
        """
        logger.info(f"[TRANSCRIBE] Начало транскрибации: {audio_path.name}")

        if not audio_path.exists():
            raise FileNotFoundError(f"[TRANSCRIBE] Аудиофайл не найден: {audio_path}")

        engine = self._get_engine()
        language = self.config.language if self.config.language != "auto" else None

        try:
            raw = engine.transcribe(
                audio_path=audio_path,
                language=language,
            )
        except Exception as exc:
            logger.error(f"[TRANSCRIBE] Ошибка транскрибации: {exc}")
            raise

        # Нормализуем сегменты
        segments: List[TranscriptSegment] = []
        for seg in raw.get("segments", []):
            segments.append(
                TranscriptSegment(
                    start=float(seg.get("start", 0)),
                    end=float(seg.get("end", 0)),
                    speaker=seg.get("speaker"),
                    text=seg.get("text", "").strip(),
                )
            )

        result = TranscriptResult(
            text=raw.get("text", "").strip(),
            language=raw.get("language", self.config.language),
            segments=segments,
            duration_sec=raw.get("duration_sec", 0.0),
            audio_duration_sec=raw.get("audio_duration_sec", 0.0),
            has_speakers=False,
        )

        logger.info(
            f"[TRANSCRIBE] ✓ Готово: {len(segments)} сегментов, "
            f"язык={result.language}, "
            f"длительность={result.audio_duration_sec:.1f}с"
        )
        return result

    def save_transcript(
        self,
        result: TranscriptResult,
        artifacts_dir: Path,
    ) -> dict:
        """
        Сохранить транскрипцию в artifacts/:
        - transcript.json   (полный результат)
        - transcript.md     (читаемый markdown)

        Возвращает dict с путями к файлам.
        """
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        # ── JSON ──────────────────────────────────────────────────────────────
        json_path = artifacts_dir / "transcript.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(result.model_dump(), f, ensure_ascii=False, indent=2)

        # ── Markdown ──────────────────────────────────────────────────────────
        md_path = artifacts_dir / "transcript.md"
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(self._build_transcript_md(result))

        logger.info(
            f"[TRANSCRIBE] ✓ Сохранено: transcript.json + transcript.md"
        )
        return {
            "transcript_json": str(json_path),
            "transcript_md": str(md_path),
        }

    # ─── Markdown builder ─────────────────────────────────────────────────────

    def _build_transcript_md(self, result: TranscriptResult) -> str:
        lines = [
            "# Транскрипт",
            "",
            f"**Язык:** {result.language}",
            f"**Длительность:** {_fmt_duration(result.audio_duration_sec)}",
            f"**Сегментов:** {len(result.segments)}",
            "",
            "---",
            "",
        ]

        if result.has_speakers:
            # Группируем по спикерам с таймкодами
            for seg in result.segments:
                speaker_label = seg.speaker or "SPEAKER"
                lines.append(f"## {seg.timecode} {speaker_label}")
                lines.append(seg.text)
                lines.append("")
        else:
            # Просто нумерованные сегменты с таймкодами
            for seg in result.segments:
                lines.append(f"## {seg.timecode}")
                lines.append(seg.text)
                lines.append("")

        return "\n".join(lines)


def _fmt_duration(sec: float) -> str:
    """Форматировать секунды в H:MM:SS"""
    total = int(sec)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"
