# Video Transcription Service — Руководство по развёртыванию

Сервис автоматической транскрипции и анализа видеозаписей встреч.  
Стек: **faster-whisper** (STT) + **Ollama + Qwen3:8b** (LLM анализ) + **FastAPI** + **Next.js**, всё в Docker.

---

## Требования к серверу

| Параметр | Минимум | Рекомендуется |
|---|---|---|
| CPU | 4 ядра x86_64 | 8+ ядер (AVX2) |
| RAM | 16 GB | 32–48 GB |
| Диск | 20 GB | 50+ GB |
| ОС | Ubuntu 22.04 | Ubuntu 22.04 / 24.04 |
| GPU | не нужен | NVIDIA (ускорит Whisper) |

---

## Быстрый старт (автоматически)

```bash
# 1. Скопировать проект на сервер
scp -r video_transcription_service user@SERVER_IP:~/ 
ssh user@SERVER_IP

# 2. Перейти в папку проекта
cd ~/video_transcription_service
# (или куда скопировали, например /opt/video_transcription_service)

# 3. Запустить скрипт установки
sudo bash install.sh
```

Скрипт сам:
- установит Docker и Ollama
- настроит Ollama на всех интерфейсах
- скачает модель qwen3:8b (~5 GB)
- откроет нужные порты в UFW
- соберёт и запустит Docker Compose

---

## Ручная установка (шаг за шагом)

### Шаг 1 — Docker

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
newgrp docker
```

### Шаг 2 — Ollama

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

### Шаг 3 — Настройка Ollama (обязательно для Linux)

По умолчанию Ollama слушает только `localhost`. Docker-контейнеры не смогут к ней обратиться.  
Нужно разрешить слушать на всех интерфейсах:

```bash
sudo mkdir -p /etc/systemd/system/ollama.service.d/
sudo tee /etc/systemd/system/ollama.service.d/override.conf << 'EOF'
[Service]
Environment="OLLAMA_HOST=0.0.0.0:11434"
EOF

sudo systemctl daemon-reload
sudo systemctl restart ollama

# Проверить:
systemctl show ollama | grep OLLAMA_HOST
```

### Шаг 4 — Загрузить модель

```bash
ollama pull qwen3:1.7b

# Проверить:
ollama list
```

### Шаг 5 — Создать .env с IP сервера

```bash
cd /opt/video_transcription_service   # или куда распаковали

# Узнать публичный IP:
curl ifconfig.me

# Создать .env:
cp .env.example .env
nano .env
# Вписать: SERVER_IP=x.x.x.x
```

### Шаг 6 — UFW (firewall)

```bash
# Открыть UI (3020) и API (8020) только для нужных IP:
sudo ufw allow from YOUR_IP proto tcp to any port 3020
sudo ufw allow from YOUR_IP proto tcp to any port 8020
sudo ufw allow from SERVER_IP proto tcp to any port 3020
sudo ufw allow from SERVER_IP proto tcp to any port 8020

# Ollama доступна только из Docker-сетей (не наружу):
sudo ufw allow from 172.16.0.0/12 to any port 11434
```

### Шаг 7 — Создать папку и запустить

```bash
mkdir -p data/inbox
docker compose up -d --build
```

Первый запуск долгий (~3-5 минут) — собирает образы и скачивает модель Whisper (~1.5 GB).

### Шаг 8 — Проверить

```bash
# Backend:
curl http://localhost:8020/health

# Статус контейнеров:
docker compose ps

# Логи:
docker compose logs -f
```

Открыть в браузере: `http://SERVER_IP:3020`

---

## Добавление видео для обработки

Сервис следит за папкой `data/inbox/`. Структура папки встречи:

```
data/inbox/
└── 2026-06-05_название-встречи/     # Формат: YYYY-MM-DD_название
    └── source/
        └── запись.mp4
```

```bash
# Создать встречу вручную:
mkdir -p data/inbox/2026-06-05_планирование/source/
cp /path/to/video.mp4 data/inbox/2026-06-05_планирование/source/

# Watcher подхватит автоматически через ~30 секунд.
# Или принудительный скан:
curl -X POST http://localhost:8020/api/meetings/scan
```

> Если бросить `.mp4` файл прямо в `data/inbox/` (без папки) — сервис сам создаст нужную структуру.

---

## Конфигурация

Основные настройки в `config.yaml` (монтируется в контейнер, не требует пересборки):

```yaml
whisper_model: medium      # tiny / base / small / medium / large-v2
device: cpu                # cpu или cuda (если есть NVIDIA GPU)
compute_type: int8         # int8 для CPU, float16 для GPU
language: ru               # ru / en / auto

llm_url: http://host.docker.internal:11434/v1/chat/completions
llm_model: "qwen3:8b"
llm_max_tokens: 2000
```

После изменения `config.yaml`:
```bash
docker compose restart vts-api
```

---

## Производительность (CPU без GPU)

| Файл | Transcription | LLM анализ | Итого |
|---|---|---|---|
| 30 мин видео | ~10 мин | ~5 мин | ~15 мин |
| 1 час видео | ~20 мин | ~10 мин | ~30 мин |
| 2 часа видео | ~40 мин | ~20 мин | ~60 мин |

> На сервере с GPU (NVIDIA) транскрипция ускоряется в 5-10 раз.

---

## Полезные команды

```bash
# Статус:
docker compose ps

# Логи backend:
docker logs -f videotranscription-api

# Логи frontend:
docker logs -f videotranscription-ui

# Перезапустить анализ всех встреч:
curl -X POST http://localhost:8020/api/meetings/reprocess-all \
  -H "Content-Type: application/json" \
  -d '{"from_stage": "analyzing", "statuses": ["failed", "partial_completed", "completed"]}'

# Перезапустить конкретную встречу:
curl -X POST http://localhost:8020/api/meetings/<ID>/reprocess \
  -H "Content-Type: application/json" \
  -d '{"from_stage": "analyzing"}'

# Swagger UI:
open http://SERVER_IP:8020/docs

# Обновить проект (после изменения кода):
docker compose up -d --build

# Остановить:
docker compose down
```

---

## Устранение проблем

### "Failed to fetch" в браузере
Браузер не может достучаться до backend. Проверьте:
```bash
# 1. Правильный ли IP в .env:
cat .env

# 2. Доступен ли порт 8020:
curl http://SERVER_IP:8020/health

# 3. Пересобрать UI с правильным IP:
docker compose up -d --build vts-ui
```

### LLM не отвечает / таймаут
```bash
# Ollama запущена?
systemctl status ollama

# Модель загружена?
ollama list

# Доступна ли из контейнера:
docker exec videotranscription-api curl -s http://host.docker.internal:11434/api/tags

# Если зависает — разрешить Docker-сетям доступ:
sudo ufw allow from 172.16.0.0/12 to any port 11434
```

### Whisper не транскрибирует (0 символов)
Файл слишком тихий или пустой — Whisper VAD фильтрует тишину.  
Проверьте аудиодорожку: `ffprobe data/inbox/.../source/video.mp4`

### Пересборка с нуля
```bash
docker compose down
docker rmi video-transcription-svc-vts-api video-transcription-svc-vts-ui
docker compose up -d --build
```

---

## Структура проекта

```
video_transcription_service/
├── install.sh              # Скрипт автоустановки
├── docker-compose.yml      # Оркестрация сервисов
├── .env.example            # Шаблон переменных окружения
├── config.yaml             # Конфигурация сервиса (Whisper, LLM, etc.)
├── backend/                # FastAPI + Whisper + LLM анализ
├── ui/                     # Next.js фронтенд
└── data/inbox/             # Папка для видеофайлов
```
