"""
Конфигурация сервиса транскрибации.
Читает секцию `meetings:` из config.yaml (путь: /app/config.yaml в Docker
или CONFIG_PATH env-переменная).
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class MeetingsConfig:
    """Конфигурация pipeline обработки встреч"""

    # Пути
    inbox_path: str = "inbox"
    artifacts_base: str = "inbox"

    # Whisper / STT
    whisper_model: str = "medium"
    device: str = "cpu"
    compute_type: str = "int8"
    language: str = "ru"

    # Дополнительные подсистемы
    diarization_enabled: bool = False
    obsidian_export_enabled: bool = False
    obsidian_meetings_dir: str = "Встречи"

    # Polling
    polling_interval_sec: int = 30

    # LLM (OpenAI-compatible endpoint, напр. LM Studio)
    llm_url: str = "http://host.docker.internal:1234/v1/chat/completions"
    llm_model: str = ""
    llm_max_tokens: int = 2000
    llm_temperature: float = 0.2

    # Автоматическая загрузка LLM модели перед анализом (пустая = отключено)
    llm_analysis_model: str = ""

    # Файлы
    supported_extensions: List[str] = field(
        default_factory=lambda: [".webm", ".mp4", ".mkv", ".avi", ".mov"]
    )
    max_file_size_mb: int = 2000
    ffmpeg_path: str = "ffmpeg"

    # Webhook: POST уведомление по завершении обработки
    webhook_url: str = ""
    webhook_on_status: List[str] = field(
        default_factory=lambda: ["completed", "failed"]
    )


def load_config() -> MeetingsConfig:
    """
    Загрузить конфиг из файла.
    Порядок поиска:
      1. CONFIG_PATH env-переменная
      2. /app/config.yaml (Docker)
      3. config.yaml (локальный запуск)
    """
    config_path_candidates = [
        os.environ.get("CONFIG_PATH", ""),
        "/app/config.yaml",
        "config.yaml",
    ]

    raw: dict = {}
    for candidate in config_path_candidates:
        if not candidate:
            continue
        p = Path(candidate)
        if p.exists():
            try:
                import yaml
                with open(p, "r", encoding="utf-8") as f:
                    raw = yaml.safe_load(f) or {}
                logger.info(f"[CONFIG] Загружен конфиг: {p}")
                break
            except Exception as exc:
                logger.warning(f"[CONFIG] Ошибка чтения {p}: {exc}")

    meetings_raw = raw.get("meetings", {})
    cfg = MeetingsConfig()

    for attr in cfg.__dataclass_fields__:
        if attr in meetings_raw:
            setattr(cfg, attr, meetings_raw[attr])

    # Нормализация путей
    cfg.inbox_path = str(Path(cfg.inbox_path))
    cfg.artifacts_base = str(Path(cfg.artifacts_base))

    logger.info(
        f"[CONFIG] inbox={cfg.inbox_path}, model={cfg.whisper_model}, "
        f"device={cfg.device}, llm={cfg.llm_url}"
    )
    return cfg


# Алиас для обратной совместимости с кодом, который вызывает load_meetings_config
def load_meetings_config(config_yaml: Optional[dict] = None) -> MeetingsConfig:
    if config_yaml is not None:
        cfg = MeetingsConfig()
        raw = config_yaml.get("meetings", {})
        for attr in cfg.__dataclass_fields__:
            if attr in raw:
                setattr(cfg, attr, raw[attr])
        cfg.inbox_path = str(Path(cfg.inbox_path))
        cfg.artifacts_base = str(Path(cfg.artifacts_base))
        return cfg
    return load_config()
