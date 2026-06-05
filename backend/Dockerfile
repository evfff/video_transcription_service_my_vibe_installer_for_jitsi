# ─── Build stage ──────────────────────────────────────────────────────────────
FROM python:3.11-slim AS base

# Системные зависимости: ffmpeg для конвертации аудио
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ─── Python deps ──────────────────────────────────────────────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ─── App code ─────────────────────────────────────────────────────────────────
# Копируем модуль meetings и stt в корень /app
COPY app/ ./app/
COPY stt/  ./stt/

# config.yaml монтируется через Docker volume (см. docker-compose.yml)
# data/inbox  монтируется через Docker volume

# ─── Runtime ──────────────────────────────────────────────────────────────────
ENV PYTHONPATH=/app:/app/app
ENV CONFIG_PATH=/app/config.yaml

EXPOSE 8020

# Папка для данных по умолчанию
RUN mkdir -p /app/data/inbox

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8020/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8020", "--workers", "1"]
