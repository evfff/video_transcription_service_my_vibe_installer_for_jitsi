"""
Media Processing Service
Отвечает за:
- поиск .webm / .mp4 в папке встречи
- извлечение аудио через ffmpeg
- нормализацию аудио (16kHz, mono, wav) для Whisper
"""
from __future__ import annotations

import logging
import subprocess
import shutil
from pathlib import Path
from typing import Optional

from .config import MeetingsConfig

logger = logging.getLogger(__name__)


class MediaProcessingService:
    """
    Извлечение и нормализация аудио из видео/аудио файлов через ffmpeg.
    """

    def __init__(self, config: MeetingsConfig) -> None:
        self.config = config
        self._ffmpeg = config.ffmpeg_path

    def check_ffmpeg(self) -> bool:
        """Проверить доступность ffmpeg"""
        try:
            result = subprocess.run(
                [self._ffmpeg, "-version"],
                capture_output=True,
                timeout=5,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return False

    def extract_audio(
        self,
        source_files: list[str],
        output_path: Path,
    ) -> Optional[Path]:
        """
        Извлечь аудио из медиафайлов и сохранить как WAV 16kHz mono.

        Если несколько файлов — конкатенирует их в один WAV.
        Возвращает путь к WAV или None при ошибке.
        """
        logger.info(
            f"[MEDIA] Начало извлечения аудио: {len(source_files)} файлов → {output_path.name}"
        )

        if not self.check_ffmpeg():
            raise RuntimeError(
                f"[MEDIA] ffmpeg не найден. Установите ffmpeg и добавьте в PATH "
                f"(или укажите путь в config.yaml → meetings.ffmpeg_path)"
            )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        wav_output = output_path.with_suffix(".wav")

        if len(source_files) == 1:
            return self._extract_single(Path(source_files[0]), wav_output)
        else:
            return self._extract_multiple(
                [Path(f) for f in source_files], wav_output
            )

    def _extract_single(self, source: Path, output: Path) -> Optional[Path]:
        """Извлечь аудио из одного файла"""
        logger.info(f"[MEDIA] Конвертация: {source.name} → {output.name}")
        cmd = [
            self._ffmpeg,
            "-y",               # перезаписать без вопросов
            "-i", str(source),
            "-ac", "1",         # mono
            "-ar", "16000",     # 16kHz — оптимально для Whisper
            "-acodec", "pcm_s16le",  # PCM 16bit signed little-endian
            "-loglevel", "error",
            str(output),
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if result.returncode != 0:
                logger.error(f"[MEDIA] ffmpeg ошибка:\n{result.stderr}")
                return None
            logger.info(f"[MEDIA] ✓ Аудио извлечено: {output.name}")
            return output
        except subprocess.TimeoutExpired:
            logger.error("[MEDIA] Таймаут ffmpeg (600с)")
            return None
        except Exception as exc:
            logger.error(f"[MEDIA] Ошибка ffmpeg: {exc}")
            return None

    def _extract_multiple(self, sources: list[Path], output: Path) -> Optional[Path]:
        """
        Извлечь и конкатенировать аудио из нескольких файлов.
        Использует ffmpeg concat demuxer.
        """
        logger.info(f"[MEDIA] Конкатенация {len(sources)} файлов → {output.name}")
        concat_list = output.parent / "_concat_list.txt"
        try:
            # Создаём список файлов для concat
            with open(concat_list, "w", encoding="utf-8") as f:
                for s in sorted(sources):
                    f.write(f"file '{s}'\n")

            cmd = [
                self._ffmpeg,
                "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(concat_list),
                "-ac", "1",
                "-ar", "16000",
                "-acodec", "pcm_s16le",
                "-loglevel", "error",
                str(output),
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if result.returncode != 0:
                logger.error(f"[MEDIA] ffmpeg concat ошибка:\n{result.stderr}")
                return None

            logger.info(f"[MEDIA] ✓ Аудио конкатенировано: {output.name}")
            return output
        except Exception as exc:
            logger.error(f"[MEDIA] Ошибка конкатенации: {exc}")
            return None
        finally:
            concat_list.unlink(missing_ok=True)

    def get_audio_duration(self, audio_path: Path) -> float:
        """Получить длительность аудио в секундах через ffprobe"""
        try:
            cmd = [
                "ffprobe",
                "-v", "quiet",
                "-print_format", "json",
                "-show_streams",
                str(audio_path),
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                return 0.0
            import json
            data = json.loads(result.stdout)
            streams = data.get("streams", [])
            for stream in streams:
                duration = stream.get("duration")
                if duration:
                    return float(duration)
        except Exception:
            pass
        return 0.0
