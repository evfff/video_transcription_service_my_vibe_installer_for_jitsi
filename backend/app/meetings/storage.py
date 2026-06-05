"""
Meeting Storage — CRUD для meta.json каждой встречи.
Работает с файловой системой; нет БД.

Структура папки встречи:
  {inbox_path}/{folder_name}/
    source/           ← исходные медиафайлы (или копируются из корня папки)
    artifacts/        ← артефакты pipeline
    meta.json         ← единственный источник истины о состоянии встречи
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional

from .models import (
    MeetingListItem,
    MeetingMeta,
    MeetingStatus,
    STATUS_LABELS,
)

logger = logging.getLogger(__name__)

META_FILE = "meta.json"
SOURCE_DIR = "source"
ARTIFACTS_DIR = "artifacts"


class MeetingStorage:
    """
    File-based хранилище метаданных встреч.
    Каждая встреча — отдельная папка с meta.json.
    """

    def __init__(self, inbox_path: str) -> None:
        self.inbox_path = Path(inbox_path)

    # ─── CRUD ─────────────────────────────────────────────────────────────────

    def load(self, folder_name: str) -> Optional[MeetingMeta]:
        """Загрузить meta.json встречи по имени папки"""
        meta_path = self.inbox_path / folder_name / META_FILE
        if not meta_path.exists():
            return None
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return MeetingMeta(**data)
        except Exception as exc:
            logger.error(f"[MEETING_STORAGE] Ошибка чтения {meta_path}: {exc}")
            return None

    def load_by_id(self, meeting_id: str) -> Optional[MeetingMeta]:
        """Найти встречу по id"""
        for folder in self._iter_meeting_folders():
            meta = self.load(folder.name)
            if meta and meta.id == meeting_id:
                return meta
        return None

    def save(self, meta: MeetingMeta) -> None:
        """Сохранить meta.json (атомарная запись через .tmp)"""
        meeting_dir = self.inbox_path / meta.folder_name
        meeting_dir.mkdir(parents=True, exist_ok=True)
        meta_path = meeting_dir / META_FILE
        tmp_path = meta_path.with_suffix(".tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(meta.model_dump(), f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, meta_path)
            logger.debug(f"[MEETING_STORAGE] Сохранено: {meta.folder_name} → {meta.status}")
        except Exception as exc:
            logger.error(f"[MEETING_STORAGE] Ошибка сохранения {meta_path}: {exc}")
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            raise

    def list_all(self) -> List[MeetingMeta]:
        """Список всех встреч, отсортированных по дате создания убыванию"""
        results = []
        for folder in self._iter_meeting_folders():
            meta = self.load(folder.name)
            if meta:
                results.append(meta)
        # сортировка: новее сначала
        results.sort(key=lambda m: m.created_at, reverse=True)
        return results

    def exists(self, folder_name: str) -> bool:
        """Проверить, зарегистрирована ли встреча"""
        return (self.inbox_path / folder_name / META_FILE).exists()

    def get_folder_path(self, folder_name: str) -> Path:
        return self.inbox_path / folder_name

    def get_source_dir(self, folder_name: str) -> Path:
        return self.inbox_path / folder_name / SOURCE_DIR

    def get_artifacts_dir(self, folder_name: str) -> Path:
        return self.inbox_path / folder_name / ARTIFACTS_DIR

    def ensure_structure(self, folder_name: str) -> None:
        """Создать структуру папок встречи"""
        (self.inbox_path / folder_name / SOURCE_DIR).mkdir(parents=True, exist_ok=True)
        (self.inbox_path / folder_name / ARTIFACTS_DIR).mkdir(parents=True, exist_ok=True)

    # ─── Helpers ──────────────────────────────────────────────────────────────

    def _iter_meeting_folders(self):
        """Итерация по папкам встреч (директориям в inbox)"""
        if not self.inbox_path.exists():
            return
        for entry in sorted(self.inbox_path.iterdir()):
            if entry.is_dir() and not entry.name.startswith("."):
                yield entry

    # ─── List Response ────────────────────────────────────────────────────────

    def to_list_item(self, meta: MeetingMeta) -> MeetingListItem:
        """Конвертация MeetingMeta → MeetingListItem для API"""
        return MeetingListItem(
            id=meta.id,
            folder_name=meta.folder_name,
            status=meta.status,
            status_label=STATUS_LABELS.get(meta.status, meta.status),
            created_at=meta.created_at,
            updated_at=meta.updated_at,
            title=meta.title,
            duration_sec=meta.duration_sec,
            source_files_count=len(meta.source_files),
            language=meta.language,
            speaker_count=meta.speaker_count,
            task_count=meta.task_count,
            has_transcript=meta.transcript_status == "done",
            has_analysis=meta.analysis_status == "done",
            has_obsidian=meta.obsidian_status == "done",
            last_error=meta.last_error,
        )
