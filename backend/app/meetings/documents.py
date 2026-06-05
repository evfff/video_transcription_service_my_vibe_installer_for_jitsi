"""
Meeting Document Service
Сборка итоговых документов встречи:
- meeting_note.md  — итоговая заметка для Obsidian

Формат совместим с Obsidian Tasks и Meta Bind.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

from .models import AnalysisResult, MeetingMeta, TranscriptResult

logger = logging.getLogger(__name__)


_MSK_OFFSET = timedelta(hours=3)


def _parse_folder_datetime(folder_name: str) -> Optional[datetime]:
    """Парсим дату/время начала из имени папки вида ..._2026-04-02T09_20_59... (UTC)."""
    m = re.search(r'(\d{4})-(\d{2})-(\d{2})T(\d{2})_(\d{2})_(\d{2})', folder_name)
    if m:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                        int(m.group(4)), int(m.group(5)), int(m.group(6)))
    return None


def _fmt_meeting_range(meta: MeetingMeta) -> Optional[str]:
    """Форматировать временной интервал встречи в МСК (UTC+3): HH:MM DD.MM.YYYY — HH:MM DD.MM.YYYY"""
    start = _parse_folder_datetime(meta.folder_name)
    if start is None and meta.meeting_start_at:
        try:
            start = datetime.fromisoformat(meta.meeting_start_at)
        except Exception:
            pass
    if start is None:
        return None
    # Folder name / ISO strings are UTC — convert to Moscow time (UTC+3)
    start_msk = start + _MSK_OFFSET
    duration = meta.duration_sec or 0.0
    end_msk = start_msk + timedelta(seconds=duration)
    fmt = lambda dt: dt.strftime("%H:%M %d.%m.%Y")
    return f"{fmt(start_msk)} — {fmt(end_msk)}"


class MeetingDocumentService:
    """
    Генерирует итоговые документы встречи.
    """

    def build_meeting_note(
        self,
        meta: MeetingMeta,
        transcript: Optional[TranscriptResult],
        analysis: Optional[AnalysisResult],
    ) -> str:
        """
        Собрать итоговую заметку meeting_note.md для Obsidian.
        """
        now = datetime.now().strftime("%Y-%m-%d")
        title = (
            (analysis.title if analysis else None)
            or meta.title
            or meta.folder_name
        )
        summary = (analysis.summary if analysis else "") or ""
        language = meta.language or "ru"
        duration = meta.duration_sec or 0.0
        participants = (analysis.participants if analysis else []) or []
        source_files = meta.source_files or []

        lines: List[str] = []

        # ── YAML Frontmatter ──────────────────────────────────────────────────
        lines += [
            "---",
            "type: meeting",
            f"meeting_id: {meta.id}",
            f"title: \"{title}\"",
            f"date: {now}",
            f"status: {meta.status}",
            f"source_folder: {meta.folder_name}",
            "audio_source_files:",
        ]
        for sf in source_files:
            lines.append(f"  - {sf}")
        lines += [
            f"participants: [{', '.join(participants)}]",
            f"language: {language}",
            f"duration_sec: {duration:.0f}",
            "tags:",
            "  - meeting",
            "---",
            "",
        ]

        # ── Title ─────────────────────────────────────────────────────────────
        lines += [f"# {title}", ""]

        # ── Summary ───────────────────────────────────────────────────────────
        lines += ["## Summary", "", summary or "_Нет данных_", ""]

        # ── Key Points ────────────────────────────────────────────────────────
        if analysis and analysis.key_points:
            lines += ["## Ключевые тезисы", ""]
            for kp in analysis.key_points:
                lines.append(f"- {kp}")
            lines.append("")

        # ── Decisions ─────────────────────────────────────────────────────────
        if analysis and analysis.decisions:
            lines += ["## Принятые решения", ""]
            for d in analysis.decisions:
                lines.append(f"- {d}")
            lines.append("")

        # ── Open Questions ────────────────────────────────────────────────────
        if analysis and analysis.open_questions:
            lines += ["## Открытые вопросы", ""]
            for q in analysis.open_questions:
                lines.append(f"- {q}")
            lines.append("")

        # ── Tasks ─────────────────────────────────────────────────────────────
        lines += ["## Задачи", ""]
        if analysis and analysis.tasks:
            for t in analysis.tasks:
                due = f" 📅 {t.due_date}" if t.due_date else ""
                lines.append(f"- [ ] {t.title}{due}")
        else:
            lines.append("_Задачи не определены_")
        lines.append("")

        # ── Notes ─────────────────────────────────────────────────────────────
        if analysis and analysis.notes_markdown:
            lines += ["## Заметки", "", analysis.notes_markdown, ""]

        # ── Transcript ────────────────────────────────────────────────────────
        lines += ["## Транскрипт", ""]
        if transcript and transcript.segments:
            for seg in transcript.segments:
                speaker_label = (
                    seg.speaker if seg.speaker else "SPEAKER"
                )
                lines.append(f"### {seg.timecode} {speaker_label}")
                lines.append(seg.text)
                lines.append("")
        elif transcript and transcript.text:
            lines.append(transcript.text)
            lines.append("")
        else:
            lines.append("_Транскрипт недоступен_")
            lines.append("")

        return "\n".join(lines)

    def save_meeting_note(
        self,
        content: str,
        artifacts_dir: Path,
        filename: str = "meeting_note.md",
    ) -> Path:
        """Сохранить meeting_note.md в artifacts/"""
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        note_path = artifacts_dir / filename
        with open(note_path, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info(f"[DOCS] ✓ Сохранено: {note_path.name}")
        return note_path

    def list_artifacts(self, artifacts_dir: Path) -> List[str]:
        """Список файлов в artifacts/"""
        if not artifacts_dir.exists():
            return []
        return [
            f.name
            for f in sorted(artifacts_dir.iterdir())
            if f.is_file() and not f.name.startswith("_")
        ]

    # ─── Separate Obsidian files ──────────────────────────────────────────────

    def build_summary_md(
        self,
        meta: MeetingMeta,
        analysis: Optional[AnalysisResult],
    ) -> str:
        """резюме.md — краткое изложение, участники, ключевые тезисы, решения"""
        title = (analysis.title if analysis else None) or meta.title or meta.folder_name
        now = datetime.now().strftime("%Y-%m-%d")
        duration = meta.duration_sec or 0.0
        participants = (analysis.participants if analysis else []) or []
        time_range = _fmt_meeting_range(meta)

        lines: List[str] = [
            "---",
            "type: meeting-summary",
            f"meeting_id: {meta.id}",
            f'title: "{title}"',
            f"date: {now}",
        ]
        if time_range:
            lines.append(f'meeting_time: "{time_range}"')
        lines += [
            f"duration_sec: {duration:.0f}",
            f"participants: [{', '.join(participants)}]",
            "---",
            "",
            f"# {title}",
            "",
        ]
        if time_range:
            lines += [f"**Время:** {time_range}", ""]

        if analysis:
            lines += ["## Краткое изложение", "", analysis.summary or "_Нет данных_", ""]
            if participants:
                lines += ["## Участники", ""]
                for p in participants:
                    lines.append(f"- {p}")
                lines.append("")
            if analysis.key_points:
                lines += ["## Ключевые тезисы", ""]
                for kp in analysis.key_points:
                    lines.append(f"- {kp}")
                lines.append("")
            if analysis.decisions:
                lines += ["## Принятые решения", ""]
                for d in analysis.decisions:
                    lines.append(f"- {d}")
                lines.append("")
            if analysis.open_questions:
                lines += ["## Открытые вопросы", ""]
                for q in analysis.open_questions:
                    lines.append(f"- {q}")
                lines.append("")
        else:
            lines += ["_Анализ ещё не выполнен_", ""]

        return "\n".join(lines)

    def build_transcript_md(
        self,
        meta: MeetingMeta,
        transcript: Optional[TranscriptResult],
    ) -> str:
        """транскрипт.md — полный транскрипт с таймкодами и спикерами"""
        title = meta.title or meta.folder_name
        now = datetime.now().strftime("%Y-%m-%d")
        time_range = _fmt_meeting_range(meta)

        lines: List[str] = [
            "---",
            "type: meeting-transcript",
            f"meeting_id: {meta.id}",
            f'title: "{title}"',
            f"date: {now}",
        ]
        if time_range:
            lines.append(f'meeting_time: "{time_range}"')
        lines += [
            "---",
            "",
            f"# Транскрипт — {title}",
            "",
        ]
        if time_range:
            lines += [f"**Время:** {time_range}", ""]

        if transcript and transcript.segments:
            if transcript.has_speakers:
                # Группируем по спикерам: новый заголовок при смене спикера
                current_speaker = None
                for seg in transcript.segments:
                    speaker = seg.speaker or "Спикер ?"
                    if speaker != current_speaker:
                        if current_speaker is not None:
                            lines.append("")
                        lines.append(f"**[{seg.timecode}] {speaker}:**")
                        current_speaker = speaker
                    lines.append(seg.text)
            else:
                # Без диаризации — формат: [HH:MM:SS] текст
                for seg in transcript.segments:
                    lines.append(f"`[{seg.timecode}]` {seg.text}")
            lines.append("")
        elif transcript and transcript.text:
            lines += [transcript.text, ""]
        else:
            lines += ["_Транскрипт недоступен_", ""]

        return "\n".join(lines)

    def build_tasks_md(
        self,
        meta: MeetingMeta,
        analysis: Optional[AnalysisResult],
    ) -> str:
        """задачи.md — задачи в формате Obsidian Tasks"""
        title = meta.title or meta.folder_name
        now = datetime.now().strftime("%Y-%m-%d")
        time_range = _fmt_meeting_range(meta)

        lines: List[str] = [
            "---",
            "type: meeting-tasks",
            f"meeting_id: {meta.id}",
            f'title: "{title}"',
            f"date: {now}",
        ]
        if time_range:
            lines.append(f'meeting_time: "{time_range}"')
        lines += [
            "---",
            "",
            f"# Задачи — {title}",
            "",
        ]
        if time_range:
            lines += [f"**Время:** {time_range}", ""]

        if analysis and analysis.tasks:
            for t in analysis.tasks:
                due = f" 📅 {t.due_date}" if t.due_date else ""
                assignee = f" @{t.assignee}" if t.assignee else ""
                priority_icon = {"high": " ⏫", "medium": "", "low": " 🔽"}.get(
                    t.priority or "", ""
                )
                lines.append(f"- [ ] {t.title}{priority_icon}{assignee}{due}")
                if t.description:
                    lines.append(f"  > {t.description}")
        else:
            lines.append("_Задачи не определены_")
        lines.append("")

        return "\n".join(lines)

    def build_notes_md(
        self,
        meta: MeetingMeta,
        analysis: Optional[AnalysisResult],
    ) -> str:
        """заметки.md — развёрнутые заметки"""
        title = meta.title or meta.folder_name
        now = datetime.now().strftime("%Y-%m-%d")
        time_range = _fmt_meeting_range(meta)

        lines: List[str] = [
            "---",
            "type: meeting-notes",
            f"meeting_id: {meta.id}",
            f'title: "{title}"',
            f"date: {now}",
        ]
        if time_range:
            lines.append(f'meeting_time: "{time_range}"')
        lines += [
            "---",
            "",
            f"# Заметки — {title}",
            "",
        ]
        if time_range:
            lines += [f"**Время:** {time_range}", ""]

        if analysis and analysis.notes_markdown:
            lines += [analysis.notes_markdown, ""]
        else:
            lines += ["_Заметки отсутствуют_", ""]

        return "\n".join(lines)
