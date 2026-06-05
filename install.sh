#!/bin/bash
# ================================================================
#  Video Transcription Service — скрипт установки
#  Запускать от root или через sudo
#  Совместим с Ubuntu 22.04 / 24.04
# ================================================================

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[VTS]${NC} $1"; }
warn() { echo -e "${YELLOW}[VTS]${NC} $1"; }
err()  { echo -e "${RED}[VTS]${NC} $1"; exit 1; }

# ── 1. Определить IP сервера ──────────────────────────────────────
SERVER_IP=$(curl -s ifconfig.me)
log "Публичный IP сервера: $SERVER_IP"

# ── 2. Создать .env если не существует ───────────────────────────
if [ ! -f .env ]; then
    echo "SERVER_IP=${SERVER_IP}" > .env
    log "Создан .env с SERVER_IP=${SERVER_IP}"
else
    warn ".env уже существует, пропуск"
fi

# ── 3. Docker ─────────────────────────────────────────────────────
if ! command -v docker &>/dev/null; then
    log "Установка Docker..."
    curl -fsSL https://get.docker.com | sh
    usermod -aG docker "$SUDO_USER" 2>/dev/null || true
    log "Docker установлен"
else
    log "Docker уже установлен: $(docker --version)"
fi

# ── 4. Ollama ─────────────────────────────────────────────────────
if ! command -v ollama &>/dev/null; then
    log "Установка Ollama..."
    curl -fsSL https://ollama.com/install.sh | sh
    log "Ollama установлена"
else
    log "Ollama уже установлена: $(ollama --version)"
fi

# ── 5. Настройка Ollama — слушать на всех интерфейсах ────────────
log "Настройка Ollama (OLLAMA_HOST=0.0.0.0:11434)..."
mkdir -p /etc/systemd/system/ollama.service.d/
tee /etc/systemd/system/ollama.service.d/override.conf > /dev/null << 'EOF'
[Service]
Environment="OLLAMA_HOST=0.0.0.0:11434"
EOF
systemctl daemon-reload
systemctl restart ollama
sleep 3
log "Ollama перезапущена"

# ── 6. Загрузить модель ───────────────────────────────────────────
OLLAMA_MODEL="qwen3:8b"
log "Загрузка модели $OLLAMA_MODEL (может занять несколько минут)..."
ollama pull "$OLLAMA_MODEL"
log "Модель загружена"

# ── 7. UFW — открыть порты ────────────────────────────────────────
if command -v ufw &>/dev/null; then
    log "Настройка UFW..."

    # IP которым разрешён доступ к UI (3020) и API (8020)
    ALLOWED_IPS=(
        "$SERVER_IP"       # сам сервер
        "5.255.101.124"    # admin IP
    )

    for IP in "${ALLOWED_IPS[@]}"; do
        ufw allow from "$IP" proto tcp to any port 3020
        ufw allow from "$IP" proto tcp to any port 8020
        log "Разрешён доступ для $IP → порты 3020, 8020"
    done

    # Ollama доступна только из Docker-сетей (не наружу)
    ufw allow from 172.16.0.0/12 to any port 11434

    log "UFW настроен"
else
    warn "UFW не найден, пропуск настройки firewall"
fi

# ── 8. Создать папку для видео ────────────────────────────────────
mkdir -p data/inbox
log "Папка data/inbox создана"

# ── 9. Сборка и запуск ───────────────────────────────────────────
log "Сборка и запуск Docker Compose..."
docker compose up -d --build

# ── 10. Проверка ─────────────────────────────────────────────────
sleep 10
if curl -sf http://localhost:8020/health > /dev/null; then
    log "✓ Backend работает: http://localhost:8020"
else
    warn "Backend ещё стартует, проверьте: docker logs videotranscription-api"
fi

echo ""
echo -e "${GREEN}══════════════════════════════════════════${NC}"
echo -e "${GREEN}  Установка завершена!${NC}"
echo -e "${GREEN}══════════════════════════════════════════${NC}"
echo ""
echo "  UI:      http://${SERVER_IP}:3020"
echo "  API:     http://${SERVER_IP}:8020"
echo "  Swagger: http://${SERVER_IP}:8020/docs"
echo ""
echo "  Добавить видео:"
echo "  mkdir -p data/inbox/2026-06-05_название/source/"
echo "  cp video.mp4 data/inbox/2026-06-05_название/source/"
echo ""
