"""
Domain models для системы обработки встреч

Контракты:
- MeetingMeta  — meta.json для каждой папки встречи
- MeetingStatus  — state machine статусов
- TranscriptSegment  — сегмент транскрипции с таймкодами
- TranscriptResult  — полный результат транскрипции
- AnalysisTask  — задача из анализа
- AnalysisResult  — структурированный результат LLM анализа
"""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, computed_field


# ============================================================================
# STATUS STATE MACHINE
# ============================================================================

class MeetingStatus(str, Enum):
    DETECTED = "detected"
    QUEUED = "queued"
    PROCESSING = "processing"
    EXTRACTING_AUDIO = "extracting_audio"
    TRANSCRIBING = "transcribing"
    DIARIZING = "diarizing"
    ANALYZING = "analyzing"
    GENERATING_DOCUMENTS = "generating_documents"
    EXPORTING_TO_OBSIDIAN = "exporting_to_obsidian"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL_COMPLETED = "partial_completed"


# Финальные статусы — дальнейшая обработка не требуется
TERMINAL_STATUSES = {
    MeetingStatus.COMPLETED,
    MeetingStatus.FAILED,
    MeetingStatus.PARTIAL_COMPLETED,
}

# Human-readable описания статусов
STATUS_LABELS: Dict[str, str] = {
    MeetingStatus.DETECTED: "Обнаружена",
    MeetingStatus.QUEUED: "В очереди",
    MeetingStatus.PROCESSING: "Обрабатывается",
    MeetingStatus.EXTRACTING_AUDIO: "Извлечение аудио",
    MeetingStatus.TRANSCRIBING: "Транскрибация",
    MeetingStatus.DIARIZING: "Разделение спикеров",
    MeetingStatus.ANALYZING: "LLM анализ",
    MeetingStatus.GENERATING_DOCUMENTS: "Генерация документов",
    MeetingStatus.EXPORTING_TO_OBSIDIAN: "Экспорт в Obsidian",
    MeetingStatus.COMPLETED: "Завершена",
    MeetingStatus.FAILED: "Ошибка",
    MeetingStatus.PARTIAL_COMPLETED: "Частично завершена",
}


# ============================================================================
# TRANSCRIPT MODELS
# ============================================================================

class TranscriptSegment(BaseModel):
    """Сегмент транскрипции с таймкодом и спикером"""
    start: float = 0.0
    end: float = 0.0
    speaker: Optional[str] = None
    text: str = ""

    @computed_field  # type: ignore[misc]
    @property
    def timecode(self) -> str:
        """Форматированный таймкод HH:MM:SS"""
        total = int(self.start)
        h, remainder = divmod(total, 3600)
        m, s = divmod(remainder, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"


class TranscriptResult(BaseModel):
    """Результат транскрипции"""
    text: str = ""
    language: str = "ru"
    segments: List[TranscriptSegment] = Field(default_factory=list)
    duration_sec: float = 0.0
    audio_duration_sec: float = 0.0
    has_speakers: bool = False


# ============================================================================
# ANALYSIS MODELS
# ============================================================================

class AnalysisTask(BaseModel):
    """Задача, извлечённая из анализа встречи"""
    title: str = ""
    description: str = ""
    assignee: Optional[str] = None
    due_date: Optional[str] = None
    priority: str = "medium"
    source_fragment: Optional[str] = None
    speaker: Optional[str] = None
    timecode: Optional[str] = None


class AnalysisResult(BaseModel):
    """
    Структурированный результат LLM анализа встречи.
    Стабильный JSON-контракт.
    """
    meeting_id: str = ""
    title: str = ""
    language: str = "ru"
    duration_sec: float = 0.0
    participants: List[str] = Field(default_factory=list)
    summary: str = ""
    key_points: List[str] = Field(default_factory=list)
    decisions: List[str] = Field(default_factory=list)
    open_questions: List[str] = Field(default_factory=list)
    tasks: List[AnalysisTask] = Field(default_factory=list)
    notes_markdown: str = ""
    transcript_segments: List[TranscriptSegment] = Field(default_factory=list)


# ============================================================================
# MEETING META (meta.json)
# ============================================================================

class MeetingMeta(BaseModel):
    """
    Мета-данные встречи — сохраняются в meta.json рядом с артефактами.
    Единственный источник истины о состоянии встречи.
    """
    # Идентификация
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    folder_name: str = ""
    folder_path: str = ""

    # Статус
    status: MeetingStatus = MeetingStatus.DETECTED

    # Временные метки
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    started_at: Optional[str] = None
    finished_at: Optional[str] = None

    # Исходные файлы
    source_files: List[str] = Field(default_factory=list)

    # Подстатусы этапов pipeline
    audio_extracted: bool = False
    transcript_status: str = "pending"   # pending | done | failed
    diarization_status: str = "pending"  # pending | done | failed | skipped
    analysis_status: str = "pending"     # pending | done | failed
    documents_status: str = "pending"    # pending | done | failed
    obsidian_status: str = "pending"     # pending | done | failed | disabled

    # Артефакты
    audio_path: Optional[str] = None
    transcript_path: Optional[str] = None
    analysis_path: Optional[str] = None
    meeting_note_path: Optional[str] = None

    # Summary данные
    title: Optional[str] = None
    language: Optional[str] = None
    duration_sec: float = 0.0
    speaker_count: int = 0
    task_count: int = 0

    # Временной интервал встречи (вычисляется из folder_name + duration_sec)
    meeting_start_at: Optional[str] = None  # ISO datetime
    meeting_end_at: Optional[str] = None    # ISO datetime
    obsidian_folder: Optional[str] = None   # Имя папки в Obsidian (из названия встречи)

    # Прогресс текущей стадии (0-100, обновляется pipeline)
    progress_pct: int = 0
    progress_detail: Optional[str] = None  # e.g. "Транскрипция: 34%"

    # Запрос отмены
    cancel_requested: bool = False

    # Ошибки
    last_error: Optional[str] = None
    stage_errors: Dict[str, str] = Field(default_factory=dict)

    def touch(self) -> None:
        """Обновить updated_at"""
        self.updated_at = datetime.now().isoformat()

    def set_status(self, status: MeetingStatus, error: Optional[str] = None) -> None:
        """Сменить статус с опциональной записью ошибки"""
        self.status = status
        self.touch()
        if error:
            self.last_error = error


# ============================================================================
# API RESPONSE MODELS
# ============================================================================

class MeetingListItem(BaseModel):
    """Элемент списка встреч для API"""
    id: str
    folder_name: str
    status: str
    status_label: str
    created_at: str
    updated_at: str
    title: Optional[str] = None
    duration_sec: float = 0.0
    source_files_count: int = 0
    language: Optional[str] = None
    speaker_count: int = 0
    task_count: int = 0
    has_transcript: bool = False
    has_analysis: bool = False
    has_obsidian: bool = False
    last_error: Optional[str] = None


class MeetingDetail(BaseModel):
    """Детальная информация о встрече для API"""
    meta: MeetingMeta
    transcript: Optional[TranscriptResult] = None
    analysis: Optional[AnalysisResult] = None
    artifacts: List[str] = Field(default_factory=list)


class MeetingListResponse(BaseModel):
    meetings: List[MeetingListItem] = Field(default_factory=list)
    total: int = 0


class ReprocessRequest(BaseModel):
    """Запрос на повторную обработку"""
    from_stage: str = "start"  # start | transcription | analysis | documents | obsidian
    force: bool = False


class PatchMeetingRequest(BaseModel):
    """Частичное обновление метаданных встречи (PATCH)"""
    title: Optional[str] = None  # Новое название (пересчитает obsidian_folder и переименует папку)


class BulkReprocessRequest(BaseModel):
    """Массовый перезапуск встреч"""
    from_stage: str = "obsidian"  # Стадия перезапуска
    status_filter: Optional[str] = None  # Фильтр по статусу (completed|failed|all)


class ExportRequest(BaseModel):
    """Запрос на экспорт в Obsidian"""
    overwrite: bool = True


class ScanResponse(BaseModel):
    """Результат сканирования inbox"""
    new_meetings: int = 0
    total_detected: int = 0
    folders: List[str] = Field(default_factory=list)
