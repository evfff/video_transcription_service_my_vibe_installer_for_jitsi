# Video Transcription Service

Автономный сервис транскрибации и анализа видеозаписей встреч.

**Возможности:**
- Автоматическая транскрибация видео/аудио файлов (faster-whisper)
- Определение спикеров — диаризация (опционально, pyannote)
- Анализ с LLM: краткое изложение, задачи, ключевые тезисы (опционально)
- Экспорт в Obsidian vault (опционально)
- Веб-интерфейс с тёмной темой RetroCyber

---

## 🚀 Деплой на Linux-сервер (Ollama + Docker)

> Если разворачиваете на Linux VPS — используйте скрипт автоустановки и `DEPLOY.md`.

**Требования:** Ubuntu 22.04/24.04, 16+ GB RAM, 20+ GB диск.

```bash
# 1. Клонировать репозиторий
git clone https://github.com/evfff/video_transcription_service_my_vibe_installer_for_jitsi
cd video_transcription_service_my_vibe_installer_for_jitsi

# 2. Запустить скрипт установки (установит Docker, Ollama, qwen3:8b, настроит UFW)
sudo bash install.sh
```

Скрипт автоматически определит IP сервера и создаст `.env`. После завершения сервис доступен по адресу `http://SERVER_IP:3020`.

> 📖 Подробная документация: [DEPLOY.md](DEPLOY.md)

**LLM:** сервис использует **Ollama** (порт 11434) с моделью **qwen3:8b**.  
Это отличается от оригинального проекта, где используется LM Studio (порт 1234).

---

## Быстрый старт (Docker)

> **Windows:** используй `mkdir data\inbox` вместо `mkdir -p data/inbox`, и `cd video_transcription_service` для перехода в папку.

### 1. Скопировать папку сервиса к себе

```
video_transcription_service/
├── config.yaml          ← редактируй конфиг здесь
├── docker-compose.yml
├── data/
│   └── inbox/           ← сюда бросать видеофайлы
├── backend/
└── ui/
```

### 2. Создать папку данных

**Windows (CMD или PowerShell):**
```
mkdir data\inbox
```

**Linux / macOS:**
```bash
mkdir -p data/inbox
```

### 3. Отредактировать `config.yaml`

Минимальные настройки:
```yaml
meetings:
  inbox_path: /app/data/inbox   # не менять для Docker
  whisper_model: medium          # tiny/base/small/medium/large-v2
  language: ru                   # ru / en / auto
  device: cpu                    # cpu / cuda
```

### 4. Запустить

> ⚠️ **Важно:** запускать строго из папки `video_transcription_service`, не выше!

```cmd
cd D:\JarvisVoice\services\video_transcription_service
docker-compose up -d
```

Контейнеры сервиса (не пересекаются с JarvisVoice):
- `videotranscription-api` — порт **8020**
- `videotranscription-ui`  — порт **3020**

### 5. Открыть UI

- **Веб-интерфейс:** http://localhost:3020
- **API документация:** http://localhost:8020/docs
- **Health check:** http://localhost:8020/health

### 6. Обработать видео

Скопируй `.mp4` / `.webm` / `.mkv` файл в папку `data/inbox/`.  
Через ~30 секунд он появится в интерфейсе и начнёт обрабатываться.

---

## Конфигурация

Все настройки в `config.yaml`. Основные параметры:

| Параметр | Описание | По умолчанию |
|---|---|---|
| `whisper_model` | Размер модели Whisper | `medium` |
| `device` | CPU или CUDA (GPU) | `cpu` |
| `language` | Язык (`ru`/`en`/`auto`) | `ru` |
| `llm_url` | URL LM Studio / OpenAI API | localhost:1234 |
| `diarization_enabled` | Определение спикеров | `false` |
| `obsidian_export_enabled` | Экспорт в Obsidian | `false` |

---

## Интеграция с LM Studio (анализ встреч)

1. Запусти **LM Studio** → Local Server → **Start**
2. Загрузи любую модель (Qwen3-8B, Mistral-7B, Gemma-2-9B)
3. В `config.yaml` уже настроен правильный URL:
   ```yaml
   llm_url: http://host.docker.internal:1234/v1/chat/completions
   ```
4. Перезапусти сервис: `docker-compose restart backend`

> Если LM Studio недоступен — сервис работает без анализа, транскрипция сохраняется.

---

## Диаризация спикеров (опционально)

Определяет "кто говорит" — помечает SPEAKER_00, SPEAKER_01, ...

1. Прими лицензию на HuggingFace: https://huggingface.co/pyannote/speaker-diarization-3.1
2. Создай токен на https://huggingface.co/settings/tokens
3. Раскомментируй в `docker-compose.yml`:
   ```yaml
   - HF_TOKEN=hf_твой_токен
   ```
4. В `config.yaml`:
   ```yaml
   diarization_enabled: true
   ```

---

## Экспорт в Obsidian (опционально)

Создаёт папку встречи прямо в Obsidian Vault:
```
Встречи/
  2025-01-15 Встреча команды/
    резюме.md
    транскрипт.md
    задачи.md
    заметки.md
```

1. Укажи путь к vault в `docker-compose.yml`:
   ```yaml
   - OBSIDIAN_VAULT_PATH=/obsidian/vault
   volumes:
     - /path/to/your/vault:/obsidian/vault
   ```
2. В `config.yaml`:
   ```yaml
   obsidian_export_enabled: true
   ```

---

## GPU ускорение (NVIDIA)

1. Убедись что установлен **nvidia-docker**: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html
2. В `config.yaml`:
   ```yaml
   device: cuda
   compute_type: float16
   ```
3. В `docker-compose.yml` добавь к сервису `backend`:
   ```yaml
   deploy:
     resources:
       reservations:
         devices:
           - driver: nvidia
             count: 1
             capabilities: [gpu]
   ```

---

## Локальный запуск (без Docker)

### Backend (Python 3.11+)

```bash
cd backend
pip install -r requirements.txt
# Установить ffmpeg: winget install ffmpeg (Windows) / apt install ffmpeg (Linux)
CONFIG_PATH=../config.yaml uvicorn app.main:app --host 0.0.0.0 --port 8020 --reload
```

### Frontend (Node.js 20+)

```bash
cd ui
npm install
NEXT_PUBLIC_API_BASE_URL=http://localhost:8020 npm run dev
# Открыть: http://localhost:3020
```

---

## API Endpoints

| Метод | URL | Описание |
|---|---|---|
| GET | `/api/meetings` | Список встреч |
| GET | `/api/meetings/{id}` | Детали встречи |
| POST | `/api/meetings/{id}/reprocess` | Повторная обработка |
| POST | `/api/meetings/{id}/cancel` | Отменить обработку |
| POST | `/api/meetings/{id}/export` | Экспорт в Obsidian |
| POST | `/api/meetings/{id}/regenerate-analysis` | Перегенерация анализа |
| GET | `/api/meetings/{id}/artifacts` | Список файлов |
| POST | `/api/meetings/scan` | Сканировать inbox |
| GET | `/api/meetings/status/watcher` | Статус watcher |
| PATCH | `/api/meetings/{id}` | Обновить название |
| GET | `/health` | Статус сервиса |
| GET | `/docs` | Swagger UI |

---

## Поддерживаемые форматы

`.mp4` `.webm` `.mkv` `.avi` `.mov` `.m4v` `.wmv` `.flv` `.mp3` `.wav` `.m4a` `.ogg`

---

## Структура данных

```
data/inbox/
├── 2025-01-15_team-meeting/
│   ├── meta.json              ← статус и метаданные встречи
│   ├── source/
│   │   └── recording.mp4      ← исходный видеофайл
│   └── artifacts/
│       ├── audio.wav           ← извлечённое аудио (16kHz mono)
│       ├── transcript.json     ← транскрипция (JSON)
│       ├── transcript.md       ← транскрипция (Markdown)
│       ├── analysis.json       ← анализ LLM (JSON)
│       ├── summary.md          ← краткое изложение
│       ├── tasks.json          ← задачи
│       └── meeting_note.md     ← полная заметка Obsidian
```

---

## Лицензия

MIT — свободное использование, распространение и продажа.
