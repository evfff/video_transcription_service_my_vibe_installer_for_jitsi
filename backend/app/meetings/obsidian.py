"""
Obsidian Export Service
Экспорт итоговых заметок встречи в Obsidian Vault.

Использует файловую систему напрямую (запись .md файлов в vault).
"""
from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Optional

from .config import MeetingsConfig

logger = logging.getLogger(__name__)


class ObsidianExportService:
    """
    Сохраняет файлы встречи в Obsidian Vault.

    Vault path берётся:
      1. Переменная окружения OBSIDIAN_VAULT_PATH (Docker volume mount)
      2. config.yaml → obsidian.vault_path  (локальный запуск)
    """

    def __init__(self, config: MeetingsConfig) -> None:
        self.config = config
        self._vault_path: Optional[Path] = None

    def _get_vault_path(self) -> Optional[Path]:
        """Получить путь к Obsidian vault."""
        if self._vault_path:
            return self._vault_path

        # 1. Docker volume mount через env
        env_vault = os.environ.get("OBSIDIAN_VAULT_PATH", "").strip()
        if env_vault:
            self._vault_path = Path(env_vault)
            return self._vault_path

        # 2. Fallback: config.yaml → obsidian.vault_path
        try:
            import yaml
            import os as _os
            cfg_path = _os.environ.get("CONFIG_PATH", "")
            for candidate in [cfg_path, "/app/config.yaml", "config.yaml"]:
                if not candidate:
                    continue
                p = Path(candidate)
                if p.exists():
                    with open(p, "r", encoding="utf-8") as f:
                        raw = yaml.safe_load(f) or {}
                    vault_str = (
                        raw.get("obsidian", {}).get("vault_path", "")
                        or raw.get("tasks", {}).get("vault_path", "")
                    )
                    if vault_str:
                        self._vault_path = Path(vault_str)
                        return self._vault_path
                    break
        except Exception as exc:
            logger.warning(f"[OBSIDIAN] Не удалось прочитать vault_path из config.yaml: {exc}")

        return None

    def export_folder(
        self,
        folder_name: str,
        documents: dict,
        meeting_id: str,
        old_folder_name: Optional[str] = None,
    ) -> bool:
        """
        Создать папку встречи в Obsidian Vault с 4 файлами:
            резюме.md, транскрипт.md, задачи.md, заметки.md

        Папка: {vault}/{obsidian_meetings_dir}/{folder_name}/

        Args:
            documents: dict[filename → content_str]
            old_folder_name: прежнее имя папки (удалить если отличается от folder_name)

        Returns True при успехе, False при ошибке.
        """
        if not self.config.obsidian_export_enabled:
            logger.info("[OBSIDIAN] Экспорт отключён (obsidian_export_enabled=false)")
            return False

        vault = self._get_vault_path()
        if not vault:
            logger.warning("[OBSIDIAN] vault_path не настроен — экспорт пропущен")
            return False

        if not vault.exists():
            logger.warning(f"[OBSIDIAN] Vault не найден: {vault}")
            return False

        meetings_dir = vault / self.config.obsidian_meetings_dir
        meeting_dir = meetings_dir / folder_name
        meeting_dir.mkdir(parents=True, exist_ok=True)

        # Удалить старую папку если встреча была переименована
        if old_folder_name and old_folder_name != folder_name:
            old_dir = meetings_dir / old_folder_name
            if old_dir.exists() and old_dir != meeting_dir:
                try:
                    shutil.rmtree(old_dir)
                    logger.info(f"[OBSIDIAN] Удалена старая папка: {old_folder_name}")
                except Exception as exc:
                    logger.warning(f"[OBSIDIAN] Не удалось удалить старую папку {old_folder_name}: {exc}")

        # Удалить устаревшие английские файлы если пишем русские
        _legacy = {"summary.md", "transcript.md", "tasks.md", "notes.md"}
        for _fn in _legacy:
            _old = meeting_dir / _fn
            if _old.exists():
                _old.unlink()

        written: list = []
        try:
            for filename, content in documents.items():
                dest = meeting_dir / filename
                dest.write_text(content, encoding="utf-8")
                written.append(filename)
            logger.info(
                f"[OBSIDIAN] ✓ Папка создана: "
                f"{meeting_dir.relative_to(vault)} "
                f"({', '.join(written)})"
            )
            return True
        except Exception as exc:
            logger.error(f"[OBSIDIAN] Ошибка записи в vault: {exc}")
            return False

    def export(
        self,
        meeting_note_path: Path,
        folder_name: str,
        meeting_id: str,
    ) -> bool:
        """
        Скопировать meeting_note.md в Obsidian vault.
        Устаревший метод — используй export_folder() для новых встреч.
        """
        if not self.config.obsidian_export_enabled:
            logger.info("[OBSIDIAN] Экспорт отключён (obsidian_export_enabled=false)")
            return False

        vault = self._get_vault_path()
        if not vault:
            logger.warning("[OBSIDIAN] vault_path не настроен — экспорт пропущен")
            return False

        if not vault.exists():
            logger.warning(f"[OBSIDIAN] Vault не найден: {vault}")
            return False

        meetings_dir = vault / self.config.obsidian_meetings_dir
        meeting_dir = meetings_dir / folder_name
        meeting_dir.mkdir(parents=True, exist_ok=True)

        dest = meeting_dir / "meeting_note.md"
        try:
            shutil.copy2(str(meeting_note_path), str(dest))
            logger.info(f"[OBSIDIAN] ✓ Экспортировано: {dest.relative_to(vault)}")
            return True
        except Exception as exc:
            logger.error(f"[OBSIDIAN] Ошибка копирования: {exc}")
            return False
