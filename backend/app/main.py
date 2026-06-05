"""
Video Transcription Service — Standalone FastAPI Application

Запуск:
    uvicorn app.main:app --host 0.0.0.0 --port 8020 --reload

API:
    GET  /health                          — статус сервиса
    GET  /api/meetings                    — список встреч
    GET  /api/meetings/{id}               — детали встречи
    POST /api/meetings/{id}/reprocess     — перезапустить обработку
    POST /api/meetings/{id}/cancel        — отменить обработку
    POST /api/meetings/{id}/export        — экспорт в Obsidian
    POST /api/meetings/{id}/regenerate-analysis
    GET  /api/meetings/{id}/artifacts     — список файлов
    POST /api/meetings/scan               — сканировать inbox
    POST /api/meetings/reprocess-all      — массовый перезапуск
    GET  /api/meetings/status/watcher     — статус фонового watcher
    PATCH /api/meetings/{id}              — обновить название
"""
from __future__ import annotations

import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api_meetings import router as meetings_router

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ─── App ─────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Video Transcription Service",
    description="Автоматическая транскрибация и анализ видеозаписей встреч",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ─── CORS ────────────────────────────────────────────────────────────────────
# Разрешаем запросы от UI (порт 3020) и локальной разработки
CORS_ORIGINS = os.environ.get(
    "CORS_ORIGINS",
    "http://localhost:3020,http://127.0.0.1:3020,http://localhost:3000,http://127.0.0.1:3000",
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Routers ─────────────────────────────────────────────────────────────────
app.include_router(meetings_router)


# ─── Lifespan ─────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup() -> None:
    """Запустить фоновый watcher при старте сервиса."""
    logger.info("[STARTUP] Video Transcription Service запускается...")
    try:
        from meetings.watcher import get_watcher
        watcher = get_watcher()
        watcher.start()
        logger.info("[STARTUP] ✓ Meeting Watcher запущен")
    except Exception as exc:
        logger.error(f"[STARTUP] Ошибка запуска watcher: {exc}")


@app.on_event("shutdown")
async def shutdown() -> None:
    """Остановить watcher при завершении."""
    logger.info("[SHUTDOWN] Остановка сервиса...")
    try:
        from meetings.watcher import get_watcher
        watcher = get_watcher()
        watcher.stop()
        logger.info("[SHUTDOWN] ✓ Meeting Watcher остановлен")
    except Exception as exc:
        logger.warning(f"[SHUTDOWN] Ошибка остановки watcher: {exc}")


# ─── Health ───────────────────────────────────────────────────────────────────
@app.get("/health", tags=["system"])
async def health():
    return {
        "status": "ok",
        "service": "video-transcription-service",
        "version": "1.0.0",
    }


@app.get("/", tags=["system"])
async def root():
    return {
        "service": "video-transcription-service",
        "docs": "/docs",
        "health": "/health",
        "api": "/api/meetings",
    }
