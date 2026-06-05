"""
Meeting Ingestion Service
Отвечает за:
- обнаружение новых папок встреч в inbox
- поиск медиафайлов (.webm, .mp4)
- валидацию структуры 
- создание MeetingMeta и регистрацию встречи
- перемещение исходных файлов в source/ подпапку
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import List, Optional, Tuple
from datetime import datetime

from .config import MeetingsConfig
from .models import MeetingMeta, MeetingStatus
from .storage import MeetingStorage

logger = logging.getLogger(__name__)


class MeetingIngestionService:
    """
    Сервис обнаружения и регистрации новых встреч из inbox папки.
    """

    def __init__(self, config: MeetingsConfig, storage: MeetingStorage) -> None:
        self.config = config
        self.storage = storage
        self._extensions = set(
            ext.lower() for ext in config.supported_extensions
        )

    # ─── Main entry point ────────────────────────────────────────────────────

    def scan_inbox(self) -> List[MeetingMeta]:
        """
        Сканировать inbox папку на предмет новых встреч.
        Поддерживает два формата:
          1. Файлы прямо в корне inbox/ → авто-создание папки по имени файла
          2. Папки с медиафайлами внутри (стандартный формат)
        Возвращает список только что зарегистрированных встреч.
        """
        inbox = Path(self.config.inbox_path)
        if not inbox.exists():
            logger.warning(f"[MEETING_INGEST] Inbox не существует: {inbox}")
            inbox.mkdir(parents=True, exist_ok=True)
            return []

        # ── Шаг 1: файлы прямо в корне inbox → авто-упаковка в папку ────────
        for item in sorted(inbox.iterdir()):
            if item.is_file() and item.suffix.lower() in self._extensions:
                self._promote_root_file(item)

        # ── Шаг 2: стандартное сканирование подпапок ─────────────────────────
        new_meetings = []
        for folder in sorted(inbox.iterdir()):
            if not folder.is_dir() or folder.name.startswith("."):
                continue

            # Пропустить уже зарегистрированные
            if self.storage.exists(folder.name):
                continue

            meeting = self._register_meeting(folder)
            if meeting:
                new_meetings.append(meeting)

        if new_meetings:
            logger.info(
                f"[MEETING_INGEST] Обнаружено новых встреч: {len(new_meetings)}"
            )
        return new_meetings

    def _promote_root_file(self, media_file: Path) -> None:
        """
        Файл в корне inbox → создать папку {имя_файла_без_расширения}/ и переместить туда.
        WelcomeN_2026-04-02T09_20.webm → WelcomeN_2026-04-02T09_20/WelcomeN_2026-04-02T09_20.webm
        """
        folder_name = media_file.stem  # имя без расширения
        target_dir = media_file.parent / folder_name
        target_dir.mkdir(exist_ok=True)
        dest = target_dir / media_file.name
        if not dest.exists():
            try:
                shutil.move(str(media_file), str(dest))
                logger.info(
                    f"[MEETING_INGEST] Авто-папка: {media_file.name} → {folder_name}/"
                )
            except Exception as exc:
                logger.warning(
                    f"[MEETING_INGEST] Не удалось создать папку для {media_file.name}: {exc}"
                )

    # ─── Registration ─────────────────────────────────────────────────────────

    def _register_meeting(self, folder: Path) -> Optional[MeetingMeta]:
        """
        Зарегистрировать папку как встречу.
        Создаёт структуру source/ + artifacts/, перемещает медиафайлы в source/.
        """
        media_files = self._find_media_files(folder)
        if not media_files:
            logger.debug(
                f"[MEETING_INGEST] Пропуск {folder.name}: нет медиафайлов"
            )
            return None

        logger.info(
            f"[MEETING_INGEST] Регистрируем встречу: {folder.name} "
            f"({len(media_files)} файлов)"
        )

        # Создаём структуру директорий
        self.storage.ensure_structure(folder.name)

        # Перемещаем медиафайлы в source/ если они лежат в корне папки
        source_dir = self.storage.get_source_dir(folder.name)
        final_sources: List[str] = []

        for mf in media_files:
            if mf.parent == source_dir:
                # Уже в source/
                final_sources.append(str(mf))
            else:
                # Переместить из корня папки в source/
                dest = source_dir / mf.name
                try:
                    shutil.move(str(mf), str(dest))
                    logger.info(f"[MEETING_INGEST] Перемещён: {mf.name} → source/")
                    final_sources.append(str(dest))
                except Exception as exc:
                    logger.warning(f"[MEETING_INGEST] Не удалось переместить {mf.name}: {exc}")
                    # Используем исходный путь
                    final_sources.append(str(mf))

        # Создаём MeetingMeta
        meta = MeetingMeta(
            folder_name=folder.name,
            folder_path=str(folder),
            status=MeetingStatus.QUEUED,
            source_files=[str(Path(f).name) for f in final_sources],
            title=self._title_from_folder(folder.name),
        )

        self.storage.save(meta)
        logger.info(
            f"[MEETING_INGEST] ✓ Зарегистрирована: {folder.name} [id={meta.id}]"
        )
        return meta

    # ─── Media discovery ──────────────────────────────────────────────────────

    def _find_media_files(self, folder: Path) -> List[Path]:
        """
        Найти медиафайлы в папке встречи (рекурсивно, но только 2 уровня).
        Проверяет корень и source/ подпапку.
        """
        found = []
        # Путь для поиска: корень + source/
        search_paths = [folder, folder / "source"]

        for search_path in search_paths:
            if not search_path.exists():
                continue
            for f in search_path.iterdir():
                if f.is_file() and f.suffix.lower() in self._extensions:
                    # Проверка на максимальный размер файла
                    size_mb = f.stat().st_size / (1024 * 1024)
                    if size_mb > self.config.max_file_size_mb:
                        logger.warning(
                            f"[MEETING_INGEST] Файл слишком большой ({size_mb:.0f}MB): {f.name}"
                        )
                        continue
                    found.append(f)

        return found

    # ─── Helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _title_from_folder(folder_name: str) -> str:
        """
        Генерация заголовка встречи из имени папки.
        2026-04-02_team_sync → Team Sync (2026-04-02)
        """
        parts = folder_name.replace("-", " ").replace("_", " ").split()
        # Определяем, начинается ли с даты (YYYY MM DD)
        if len(parts) >= 3 and parts[0].isdigit() and len(parts[0]) == 4:
            date_part = f"{parts[0]}-{parts[1]}-{parts[2]}"
            title_parts = parts[3:]
        else:
            date_part = None
            title_parts = parts

        title = " ".join(p.capitalize() for p in title_parts)
        if date_part:
            title = f"{title} ({date_part})" if title else date_part
        return title or folder_name
