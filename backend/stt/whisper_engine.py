"""
Whisper движок для распознавания речи
Использует faster-whisper для оптимальной производительности
Singleton pattern для переиспользования загруженной модели
"""
import os
import logging
import time
from pathlib import Path
from typing import Optional, Dict, Any, Union

logger = logging.getLogger(__name__)


class WhisperEngine:
    """
    Singleton Whisper движок для распознавания речи
    """
    _instance: Optional['WhisperEngine'] = None
    _model = None
    _device: str = "cpu"
    _compute_type: str = "int8"
    _model_name: str = "small"
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        # Инициализация происходит только один раз
        if not hasattr(self, '_initialized'):
            self._initialized = True
            logger.info("[WHISPER] Инициализация Whisper Engine")
    
    def load_model(
        self, 
        model_name: str = "small",
        device: Optional[str] = None,
        compute_type: Optional[str] = None
    ) -> None:
        """
        Загрузить модель Whisper (ленивая загрузка)
        
        Args:
            model_name: Размер модели (tiny, base, small, medium, large)
            device: "cuda" или "cpu" (auto-detect если None)
            compute_type: "float16", "int8", "float32" (auto-select если None)
        """
        if self._model is not None and self._model_name == model_name:
            logger.info(f"[WHISPER] Модель {model_name} уже загружена")
            return
        
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            raise ImportError(
                "faster-whisper не установлен. "
                "Установите: pip install faster-whisper"
            )

        # Определить устройство без torch: попробуем ctranslate2 CUDA,
        # fallback на cpu
        if device is None:
            try:
                import ctranslate2
                if "cuda" in ctranslate2.get_supported_compute_types("cuda"):
                    device = "cuda"
                else:
                    device = "cpu"
            except Exception:
                device = "cpu"

        # Определить compute_type
        if compute_type is None:
            if device == "cuda":
                compute_type = "float16"  # Оптимально для CUDA
            else:
                compute_type = "int8"  # Быстрее на CPU
        
        self._device = device
        self._compute_type = compute_type
        self._model_name = model_name
        
        logger.info(
            f"[WHISPER] Загрузка модели: {model_name}, "
            f"device={device}, compute_type={compute_type}"
        )
        
        start_time = time.time()
        
        try:
            self._model = WhisperModel(
                model_name,
                device=device,
                compute_type=compute_type
            )
            
            elapsed = time.time() - start_time
            logger.info(f"[WHISPER] ✓ Модель загружена за {elapsed:.2f}с")
            
        except Exception as e:
            logger.error(f"[WHISPER] Ошибка загрузки модели: {e}")
            self._model = None
            raise
    
    def transcribe(
        self,
        audio_path: Union[str, Path],
        language: Optional[str] = None,
        task: str = "transcribe"
    ) -> Dict[str, Any]:
        """
        Распознать речь из аудиофайла
        
        Args:
            audio_path: Путь к аудиофайлу
            language: Код языка (ru, en и т.д.), None = auto-detect
            task: "transcribe" или "translate"
        
        Returns:
            {
                "text": str,           # Распознанный текст
                "language": str,       # Определённый язык
                "segments": list,      # Сегменты с таймингами
                "duration_sec": float  # Длительность обработки
            }
        """
        if self._model is None:
            # Автоматически загрузить модель при первом использовании
            logger.info("[WHISPER] Модель не загружена, загружаем автоматически...")
            self.load_model()
        
        audio_path = Path(audio_path)
        if not audio_path.exists():
            raise FileNotFoundError(f"Аудиофайл не найден: {audio_path}")
        
        logger.info(f"[WHISPER] Распознавание: {audio_path.name}, язык={language or 'auto'}")
        
        start_time = time.time()
        
        try:
            segments, info = self._model.transcribe(
                str(audio_path),
                language=language,
                task=task,
                beam_size=5,
                vad_filter=True,  # Фильтрация тишины
                vad_parameters=dict(min_silence_duration_ms=500)
            )
            
            # Собрать текст из сегментов
            full_text = ""
            segments_data = []
            
            for segment in segments:
                full_text += segment.text + " "
                segments_data.append({
                    "start": round(segment.start, 2),
                    "end": round(segment.end, 2),
                    "text": segment.text.strip()
                })
            
            full_text = full_text.strip()
            elapsed = time.time() - start_time
            
            detected_language = info.language if hasattr(info, 'language') else (language or "unknown")
            
            logger.info(
                f"[WHISPER] ✓ Распознано {len(full_text)} символов, "
                f"язык={detected_language}, время={elapsed:.2f}с"
            )
            
            return {
                "text": full_text,
                "language": detected_language,
                "segments": segments_data,
                "duration_sec": round(elapsed, 2),
                "audio_duration_sec": round(info.duration, 2) if hasattr(info, 'duration') else 0
            }
            
        except Exception as e:
            logger.error(f"[WHISPER] Ошибка распознавания: {e}", exc_info=True)
            raise
    
    def is_ready(self) -> bool:
        """Проверить готовность модели"""
        return self._model is not None
    
    def get_info(self) -> Dict[str, Any]:
        """Получить информацию о движке"""
        return {
            "ready": self.is_ready(),
            "model": self._model_name if self._model else None,
            "device": self._device if self._model else None,
            "compute_type": self._compute_type if self._model else None
        }


# Глобальный экземпляр (singleton)
whisper_engine = WhisperEngine()
