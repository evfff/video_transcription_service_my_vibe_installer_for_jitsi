"""
Meetings REST API — Video Transcription Service

Endpoints:
  GET    /api/meetings                           — список встреч
  GET    /api/meetings/{id}                      — детали встречи
  PATCH  /api/meetings/{id}                      — обновить название
  POST   /api/meetings/{id}/reprocess            — повторная обработка
  POST   /api/meetings/{id}/cancel               — отменить обработку
  POST   /api/meetings/{id}/export               — экспорт в Obsidian
  POST   /api/meetings/{id}/regenerate-analysis  — перегенерация анализа
  GET    /api/meetings/{id}/artifacts            — список артефактов
  POST   /api/meetings/scan                      — ручное сканирование inbox
  POST   /api/meetings/reprocess-all             — массовый перезапуск
  GET    /api/meetings/status/watcher            — статус watcher
"""
from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse

from meetings.models import (
    AnalysisResult,
    BulkReprocessRequest,
    ExportRequest,
    MeetingDetail,
    MeetingListResponse,
    MeetingStatus,
    PatchMeetingRequest,
    ReprocessRequest,
    ScanResponse,
    STATUS_LABELS,
    TranscriptResult,
)
from meetings.watcher import get_watcher

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/meetings", tags=["meetings"])


# ─── Watcher lazy init ────────────────────────────────────────────────────────

def _watcher():
    return get_watcher()


# ============================================================================
# LIST
# ============================================================================

@router.get("", response_model=MeetingListResponse)
@router.get("/", response_model=MeetingListResponse)
async def list_meetings(
    status: Optional[str] = Query(None, description="Фильтр по статусу"),
    search: Optional[str] = Query(None, description="Поиск по названию/папке"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    w = _watcher()
    all_meta = w.storage.list_all()

    if status:
        all_meta = [m for m in all_meta if m.status == status]

    if search:
        q = search.lower()
        all_meta = [
            m for m in all_meta
            if q in (m.folder_name or "").lower()
            or q in (m.title or "").lower()
        ]

    total = len(all_meta)
    page = all_meta[offset: offset + limit]
    items = [w.storage.to_list_item(m) for m in page]

    return MeetingListResponse(meetings=items, total=total)


# ============================================================================
# DETAIL
# ============================================================================

@router.get("/{meeting_id}", response_model=MeetingDetail)
async def get_meeting(meeting_id: str):
    w = _watcher()
    meta = w.storage.load_by_id(meeting_id)
    if not meta:
        raise HTTPException(status_code=404, detail=f"Встреча не найдена: {meeting_id}")

    artifacts_dir = w.storage.get_artifacts_dir(meta.folder_name)

    transcript: Optional[TranscriptResult] = None
    if meta.transcript_status == "done":
        json_path = artifacts_dir / "transcript.json"
        if json_path.exists():
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    transcript = TranscriptResult(**json.load(f))
            except Exception as exc:
                logger.warning(f"[API] Ошибка чтения transcript.json: {exc}")

    analysis: Optional[AnalysisResult] = None
    if meta.analysis_status == "done":
        json_path = artifacts_dir / "analysis.json"
        if json_path.exists():
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    analysis = AnalysisResult(**json.load(f))
            except Exception as exc:
                logger.warning(f"[API] Ошибка чтения analysis.json: {exc}")

    from meetings.documents import MeetingDocumentService
    doc_svc = MeetingDocumentService()
    artifacts = doc_svc.list_artifacts(artifacts_dir)

    return MeetingDetail(
        meta=meta,
        transcript=transcript,
        analysis=analysis,
        artifacts=artifacts,
    )


# ============================================================================
# ARTIFACTS
# ============================================================================

@router.get("/{meeting_id}/artifacts")
async def list_artifacts(meeting_id: str):
    w = _watcher()
    meta = w.storage.load_by_id(meeting_id)
    if not meta:
        raise HTTPException(status_code=404, detail="Встреча не найдена")

    artifacts_dir = w.storage.get_artifacts_dir(meta.folder_name)
    from meetings.documents import MeetingDocumentService
    files = MeetingDocumentService().list_artifacts(artifacts_dir)

    return {"meeting_id": meeting_id, "artifacts": files, "total": len(files)}


# ============================================================================
# REPROCESS
# ============================================================================

@router.post("/{meeting_id}/reprocess")
async def reprocess_meeting(meeting_id: str, request: ReprocessRequest = ReprocessRequest()):
    w = _watcher()
    success = w.reprocess(meeting_id, from_stage=request.from_stage)
    if not success:
        meta = w.storage.load_by_id(meeting_id)
        if not meta:
            raise HTTPException(status_code=404, detail="Встреча не найдена")
        raise HTTPException(
            status_code=409,
            detail="Встреча уже обрабатывается или не найдена"
        )
    return {"success": True, "meeting_id": meeting_id, "from_stage": request.from_stage}


# ============================================================================
# EXPORT TO OBSIDIAN
# ============================================================================

@router.post("/{meeting_id}/export")
async def export_to_obsidian(meeting_id: str, request: ExportRequest = ExportRequest()):
    w = _watcher()
    meta = w.storage.load_by_id(meeting_id)
    if not meta:
        raise HTTPException(status_code=404, detail="Встреча не найдена")

    artifacts_dir = w.storage.get_artifacts_dir(meta.folder_name)

    from meetings.obsidian import ObsidianExportService
    from meetings.pipeline import _make_obsidian_folder_name

    transcript = w.pipeline._load_saved_transcript(artifacts_dir)
    analysis = w.pipeline._load_saved_analysis(artifacts_dir)

    documents = {
        "резюме.md": w.pipeline.documents.build_summary_md(meta, analysis),
        "транскрипт.md": w.pipeline.documents.build_transcript_md(meta, transcript),
        "задачи.md": w.pipeline.documents.build_tasks_md(meta, analysis),
        "заметки.md": w.pipeline.documents.build_notes_md(meta, analysis),
    }

    obsidian_folder = _make_obsidian_folder_name(meta)
    old_folder = meta.obsidian_folder or meta.folder_name
    meta.obsidian_folder = obsidian_folder

    obsidian = ObsidianExportService(w.config)
    success = obsidian.export_folder(
        obsidian_folder, documents, meta.id,
        old_folder_name=old_folder if old_folder != obsidian_folder else None,
    )

    if success:
        meta.obsidian_status = "done"
    else:
        meta.obsidian_status = "failed"
        meta.stage_errors["obsidian"] = "Экспорт не удался"

    w.storage.save(meta)

    if not success:
        raise HTTPException(status_code=502, detail="Экспорт в Obsidian не удался")

    return {"success": True, "meeting_id": meeting_id}


# ============================================================================
# REGENERATE ANALYSIS
# ============================================================================

@router.post("/{meeting_id}/regenerate-analysis")
async def regenerate_analysis(meeting_id: str):
    w = _watcher()
    meta = w.storage.load_by_id(meeting_id)
    if not meta:
        raise HTTPException(status_code=404, detail="Встреча не найдена")

    if meta.transcript_status != "done":
        raise HTTPException(
            status_code=422,
            detail="Транскрипция ещё не выполнена. Нет данных для анализа."
        )

    if meeting_id in w._processing:
        raise HTTPException(status_code=409, detail="Встреча уже обрабатывается")

    w.reprocess(meeting_id, from_stage="analysis")
    return {"success": True, "meeting_id": meeting_id, "from_stage": "analysis"}


# ============================================================================
# SCAN INBOX
# ============================================================================

@router.post("/scan", response_model=ScanResponse)
async def scan_inbox():
    w = _watcher()
    new_meetings = w.scan_now()
    return ScanResponse(
        new_meetings=len(new_meetings),
        total_detected=len(new_meetings),
        folders=[m.folder_name for m in new_meetings],
    )


# ============================================================================
# WATCHER STATUS
# ============================================================================

@router.get("/status/watcher")
async def watcher_status():
    w = _watcher()
    all_meta = w.storage.list_all()
    processing_count = len([
        m for m in all_meta
        if m.status not in {MeetingStatus.COMPLETED, MeetingStatus.FAILED, MeetingStatus.PARTIAL_COMPLETED}
    ])
    return {
        "running": w.is_running(),
        "inbox_path": str(w.config.inbox_path),
        "polling_interval_sec": w.config.polling_interval_sec,
        "total_meetings": len(all_meta),
        "processing_count": processing_count,
        "currently_processing": list(w._processing),
    }


# ============================================================================
# PATCH
# ============================================================================

@router.patch("/{meeting_id}")
async def patch_meeting(meeting_id: str, request: PatchMeetingRequest):
    w = _watcher()
    meta = w.storage.load_by_id(meeting_id)
    if not meta:
        raise HTTPException(status_code=404, detail="Встреча не найдена")

    if request.title is not None:
        new_title = request.title.strip()
        if not new_title:
            raise HTTPException(status_code=422, detail="Название не может быть пустым")
        old_obsidian_folder = meta.obsidian_folder or meta.folder_name
        meta.title = new_title
        from meetings.pipeline import _make_obsidian_folder_name
        new_obsidian_folder = _make_obsidian_folder_name(meta)
        meta.obsidian_folder = new_obsidian_folder
        meta.touch()
        w.storage.save(meta)

        if old_obsidian_folder != new_obsidian_folder:
            from meetings.obsidian import ObsidianExportService
            obsidian = ObsidianExportService(w.config)
            vault = obsidian._get_vault_path()
            if vault:
                old_dir = vault / w.config.obsidian_meetings_dir / old_obsidian_folder
                new_dir = vault / w.config.obsidian_meetings_dir / new_obsidian_folder
                if old_dir.exists() and not new_dir.exists():
                    shutil.move(str(old_dir), str(new_dir))

    return {"success": True, "meeting_id": meeting_id, "title": meta.title, "obsidian_folder": meta.obsidian_folder}


# ============================================================================
# CANCEL
# ============================================================================

@router.post("/{meeting_id}/cancel")
async def cancel_meeting(meeting_id: str):
    w = _watcher()
    meta = w.storage.load_by_id(meeting_id)
    if not meta:
        raise HTTPException(status_code=404, detail="Встреча не найдена")

    active = {
        MeetingStatus.PROCESSING, MeetingStatus.QUEUED,
        MeetingStatus.TRANSCRIBING, MeetingStatus.DIARIZING,
        MeetingStatus.ANALYZING, MeetingStatus.EXTRACTING_AUDIO,
        MeetingStatus.GENERATING_DOCUMENTS, MeetingStatus.EXPORTING_TO_OBSIDIAN,
    }
    if meta.status not in active:
        raise HTTPException(
            status_code=409,
            detail=f"Встреча не в процессе обработки (статус: {meta.status})"
        )

    w.pipeline.cancel(meta)
    return {"success": True, "meeting_id": meeting_id}


# ============================================================================
# BULK REPROCESS
# ============================================================================

@router.post("/reprocess-all")
async def bulk_reprocess(request: BulkReprocessRequest = BulkReprocessRequest()):
    w = _watcher()
    all_meta = w.storage.list_all()

    status_filter = (request.status_filter or "completed").lower()

    if status_filter == "all":
        targets = all_meta
    elif status_filter == "failed":
        targets = [m for m in all_meta if m.status == MeetingStatus.FAILED]
    else:
        targets = [m for m in all_meta if m.status == MeetingStatus.COMPLETED]

    started = 0
    for meta in targets:
        if meta.id not in w._processing:
            w.reprocess(meta.id, from_stage=request.from_stage)
            started += 1

    return {
        "success": True,
        "started": started,
        "total_found": len(targets),
        "from_stage": request.from_stage,
    }
