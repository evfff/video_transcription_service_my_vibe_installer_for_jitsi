"""
LM Studio Model Manager
Загружает и выгружает модель через LM Studio REST API.

Пробует два набора эндпоинтов:
  v0: POST /api/v0/models/load    (body: {"identifier": "<id>"})
  v1: POST /api/v1/models/load    (body: {"model": "<id>"})

Если LM Studio не поддерживает load/unload (старые версии) — логируем
предупреждение и продолжаем анализ (предполагается, что модель уже загружена).
"""
from __future__ import annotations

import logging
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

# Таймаут ожидания загрузки модели (секунды).
LOAD_TIMEOUT_SEC = 180.0
UNLOAD_TIMEOUT_SEC = 30.0

# Фраза, которую LM Studio вставляет в ответ для неизвестных эндпоинтов
_UNSUPPORTED_MARKER = "unexpected endpoint"


def _derive_base_url(llm_url: str) -> str:
    """
    Из URL чат-completions вычленяем базовый хост LM Studio.
    Например: 'http://127.0.0.1:1234/v1/chat/completions' → 'http://127.0.0.1:1234'
    """
    parsed = urlparse(llm_url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _is_unsupported_response(resp: httpx.Response) -> bool:
    """Возвращает True если LM Studio вернул 200 для несуществующего эндпоинта."""
    try:
        body = resp.text.lower()
        return _UNSUPPORTED_MARKER in body
    except Exception:
        return False


class LMStudioModelManager:
    """
    Управляет загрузкой/выгрузкой модели в LM Studio.

    load() не бросает исключение если LM Studio не поддерживает API
    управления моделями — только логирует предупреждение.
    unload() вызывается только если load() прошёл успешно.
    """

    def __init__(self, base_url: str, model_identifier: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.model_identifier = model_identifier
        self._instance_id: str = model_identifier
        self._loaded: bool = False  # True только если load() реально сработал

    # ─── Public API ───────────────────────────────────────────────────────────

    def load(self) -> None:
        """
        Загрузить модель в LM Studio.
        При неподдерживаемом API логирует предупреждение и не блокирует анализ.
        При сетевой/HTTP ошибке бросает RuntimeError.
        """
        # Пробуем v0, затем v1
        candidates = [
            (f"{self.base_url}/api/v0/models/load", {"identifier": self.model_identifier}),
            (f"{self.base_url}/api/v1/models/load", {"model": self.model_identifier}),
        ]
        for url, payload in candidates:
            logger.info(f"[LMSTUDIO] Загрузка модели '{self.model_identifier}' → POST {url}")
            try:
                with httpx.Client(timeout=LOAD_TIMEOUT_SEC) as client:
                    resp = client.post(url, json=payload)
                if _is_unsupported_response(resp):
                    logger.debug(f"[LMSTUDIO] Эндпоинт {url} не поддерживается, пробуем следующий")
                    continue
                resp.raise_for_status()
                try:
                    data = resp.json()
                except Exception:
                    data = {}
                self._instance_id = data.get("instance_id", self.model_identifier)
                load_time = data.get("load_time_seconds", data.get("load_duration_seconds", "?"))
                logger.info(
                    f"[LMSTUDIO] ✓ Модель '{self.model_identifier}' загружена "
                    f"(instance_id={self._instance_id}, time={load_time}s)"
                )
                self._loaded = True
                return
            except httpx.HTTPStatusError as exc:
                raise RuntimeError(
                    f"[LMSTUDIO] Не удалось загрузить '{self.model_identifier}': "
                    f"HTTP {exc.response.status_code} — {exc.response.text[:300]}"
                ) from exc
            except RuntimeError:
                raise
            except Exception as exc:
                raise RuntimeError(
                    f"[LMSTUDIO] Не удалось загрузить '{self.model_identifier}': {exc}"
                ) from exc

        # Оба эндпоинта вернули "Unexpected endpoint"
        logger.warning(
            f"[LMSTUDIO] Эта версия LM Studio не поддерживает автоматическую "
            f"загрузку модели через REST API. "
            f"Убедитесь, что модель '{self.model_identifier}' уже загружена в LM Studio."
        )
        self._loaded = False

    def unload(self) -> None:
        """
        Выгрузить модель из LM Studio.
        Вызывается только если load() реально загрузил модель.
        Не бросает исключение.
        """
        if not self._loaded:
            return
        candidates = [
            (f"{self.base_url}/api/v0/models/unload", {"identifier": self._instance_id}),
            (f"{self.base_url}/api/v1/models/unload", {"instance_id": self._instance_id}),
        ]
        for url, payload in candidates:
            logger.info(f"[LMSTUDIO] Выгрузка модели '{self._instance_id}' → POST {url}")
            try:
                with httpx.Client(timeout=UNLOAD_TIMEOUT_SEC) as client:
                    resp = client.post(url, json=payload)
                if _is_unsupported_response(resp):
                    continue
                resp.raise_for_status()
                logger.info(f"[LMSTUDIO] ✓ Модель '{self._instance_id}' выгружена")
                return
            except Exception as exc:
                logger.warning(f"[LMSTUDIO] Не удалось выгрузить '{self._instance_id}': {exc}")
                returndates = [
            (f"{self.base_url}/api/v0/models/unload", {"identifier": self._instance_id}),
            (f"{self.base_url}/api/v1/models/unload", {"instance_id": self._instance_id}),
        ]
        for url, payload in candidates:
            logger.info(f"[LMSTUDIO] Выгрузка модели '{self._instance_id}' → POST {url}")
            try:
                with httpx.Client(timeout=UNLOAD_TIMEOUT_SEC) as client:
                    resp = client.post(url, json=payload)
                if _is_unsupported_response(resp):
                    continue
                resp.raise_for_status()
                logger.info(f"[LMSTUDIO] ✓ Модель '{self._instance_id}' выгружена")
                return
            except Exception as exc:
                logger.warning(f"[LMSTUDIO] Не удалось выгрузить '{self._instance_id}': {exc}")
                return
