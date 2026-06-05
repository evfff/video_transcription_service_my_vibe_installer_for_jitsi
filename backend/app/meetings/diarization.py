"""
Diarization Service — опциональное разделение спикеров.

Реализация:
- Если pyannote.audio доступна и diarization_enabled=True → разделяем
- При любой ошибке → graceful fallback, pipeline продолжается
- Сопоставляем diarization сегменты с Whisper-сегментами по таймкоду

ВНИМАНИЕ: pyannote требует токен HuggingFace для скачивания модели.
Если недоступно → статус "skipped", meeting продолжает обработку.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import List, Optional

from .config import MeetingsConfig
from .models import TranscriptResult, TranscriptSegment

# ─── Compatibility shim for torchaudio >= 2.6 and huggingface_hub >= 0.20 ──
# torchaudio 2.11 dropped AudioMetaData, info(), list_audio_backends().
# huggingface_hub >= 0.20 dropped use_auth_token (renamed to token).
# pyannote.audio 3.3.2 still uses both; inject shims before any pyannote import.
def _patch_torchaudio() -> None:
    try:
        import torchaudio  # noqa: PLC0415
        if not hasattr(torchaudio, "AudioMetaData"):
            from collections import namedtuple
            _AM = namedtuple(
                "AudioMetaData",
                ["sample_rate", "num_frames", "num_channels", "bits_per_sample", "encoding"],
            )
            torchaudio.AudioMetaData = _AM  # type: ignore[attr-defined]
        if not hasattr(torchaudio, "info"):
            import soundfile as _sf
            def _info(uri, format=None, buffer_size=4096, **kwargs):  # noqa: ANN202
                i = _sf.info(str(uri))
                return torchaudio.AudioMetaData(  # type: ignore[attr-defined]
                    sample_rate=i.samplerate,
                    num_frames=i.frames,
                    num_channels=i.channels,
                    bits_per_sample=0,
                    encoding="unknown",
                )
            torchaudio.info = _info  # type: ignore[attr-defined]
        if not hasattr(torchaudio, "list_audio_backends"):
            torchaudio.list_audio_backends = lambda: ["soundfile"]  # type: ignore[attr-defined]
        # torchaudio 2.11 load() defaults to TorchCodec which is not available in slim containers.
        # Replace with soundfile-based loader that returns torch.Tensor pairs.
        _orig_load = getattr(torchaudio, "load", None)
        if _orig_load and not getattr(_orig_load, "_sf_patched", False):
            import soundfile as _sf2
            import torch as _torch

            def _load_via_sf(uri, frame_offset=0, num_frames=-1, normalize=True,
                              channels_first=True, format=None, buffer_size=4096, **kwargs):  # noqa: ANN
                data, sr = _sf2.read(str(uri), dtype="float32", always_2d=True,
                                     start=frame_offset,
                                     stop=None if num_frames < 0 else frame_offset + num_frames)
                waveform = _torch.from_numpy(data.T if channels_first else data)
                return waveform, sr

            _load_via_sf._sf_patched = True
            torchaudio.load = _load_via_sf  # type: ignore[attr-defined]
    except Exception:
        pass  # если torchaudio вообще нет — pyannote сама разберётся


def _patch_huggingface_hub() -> None:
    """Rename use_auth_token → token in hf_hub_download/snapshot_download."""
    try:
        import huggingface_hub as _hf  # noqa: PLC0415
        import functools

        def _wrap(fn):
            @functools.wraps(fn)
            def _wrapper(*args, **kwargs):
                if "use_auth_token" in kwargs:
                    kwargs.setdefault("token", kwargs.pop("use_auth_token"))
                return fn(*args, **kwargs)
            return _wrapper

        for _name in ("hf_hub_download", "snapshot_download", "model_info"):
            _orig = getattr(_hf, _name, None)
            if _orig and not getattr(_orig, "_uat_patched", False):
                _patched = _wrap(_orig)
                _patched._uat_patched = True
                setattr(_hf, _name, _patched)
    except Exception:
        pass


def _patch_torch_load() -> None:
    """PyTorch >= 2.6 defaults weights_only=True, breaking pyannote checkpoint loading.
    Also fixes version mismatch: pytorch_lightning passes weights_only= to lightning_fabric._load
    which doesn't accept it."""
    try:
        import torch  # noqa: PLC0415

        # 1. Allow TorchVersion global that pyannote embeds in its checkpoints
        if hasattr(torch, "serialization") and hasattr(torch.serialization, "add_safe_globals"):
            if hasattr(torch, "torch_version") and hasattr(torch.torch_version, "TorchVersion"):
                torch.serialization.add_safe_globals([torch.torch_version.TorchVersion])

        # 2. Patch lightning_fabric._load to accept weights_only kwarg and use weights_only=False.
        #    pytorch_lightning >= 2.x passes weights_only= but older lightning_fabric ignores it.
        try:
            import lightning_fabric.utilities.cloud_io as _lio  # noqa: PLC0415
            import pytorch_lightning.core.saving as _plsaving  # noqa: PLC0415

            def _patched_load(path_or_url, map_location=None, weights_only=None):
                # Always use weights_only=False for pyannote checkpoints (trusted HF source)
                return torch.load(path_or_url, map_location=map_location, weights_only=False)

            _patched_load._patched_wo = True
            _lio._load = _patched_load
            # Also update the reference already imported into pytorch_lightning
            _plsaving.pl_load = _patched_load
        except Exception:
            pass
    except Exception:
        pass


_patch_torchaudio()
_patch_huggingface_hub()
_patch_torch_load()

logger = logging.getLogger(__name__)


class DiarizationService:
    """
    Опциональная диаризация (разделение спикеров).
    При недоступности gracefully деградирует до fallback.
    """

    def __init__(self, config: MeetingsConfig) -> None:
        self.config = config
        self._pipeline = None
        self._available: Optional[bool] = None  # None = не проверяли

    def is_available(self) -> bool:
        """Проверить доступность pyannote.audio"""
        if not self.config.diarization_enabled:
            return False
        if self._available is None:
            self._available = self._check_availability()
        return self._available

    def diarize(
        self,
        audio_path: Path,
        transcript: TranscriptResult,
    ) -> TranscriptResult:
        """
        Запустить диаризацию и обновить сегменты транскрипции speaker-полем.
        При ошибке → возвращает исходный transcript без изменений (graceful).
        """
        if not self.is_available():
            logger.info("[DIARIZATION] Диаризация отключена или недоступна — пропуск")
            return transcript

        try:
            logger.info(f"[DIARIZATION] Начало диаризации: {audio_path.name}")
            pipeline = self._get_pipeline()
            diar = pipeline(str(audio_path))

            # Получаем сегменты спикеров: [(start, end, speaker_label), ...]
            diar_segments = [
                (turn.start, turn.end, speaker)
                for turn, _, speaker in diar.itertracks(yield_label=True)
            ]
            logger.info(f"[DIARIZATION] Получено {len(diar_segments)} диаризованных сегментов")

            # Нормализуем метки: SPEAKER_00 → Спикер 1, SPEAKER_01 → Спикер 2, ...
            raw_labels = sorted(set(sp for _, _, sp in diar_segments))
            speaker_map = {sp: f"Спикер {i + 1}" for i, sp in enumerate(raw_labels)}
            diar_segments = [
                (s, e, speaker_map[sp]) for s, e, sp in diar_segments
            ]
            logger.info(f"[DIARIZATION] Карта спикеров: {speaker_map}")

            # Сопоставляем с Whisper сегментами
            enriched = self._align_speakers(transcript.segments, diar_segments)
            speakers = set(s.speaker for s in enriched if s.speaker)
            logger.info(
                f"[DIARIZATION] ✓ Определено спикеров: {len(speakers)}: {', '.join(sorted(speakers))}"
            )

            return TranscriptResult(
                text=transcript.text,
                language=transcript.language,
                segments=enriched,
                duration_sec=transcript.duration_sec,
                audio_duration_sec=transcript.audio_duration_sec,
                has_speakers=True,
            )

        except Exception as exc:
            logger.warning(
                f"[DIARIZATION] Ошибка диаризации (fallback без спикеров): {exc}"
            )
            # Сохраняем ошибку в transcript для передачи в pipeline
            transcript._diarization_error = str(exc)
            return transcript

    # ─── Private ──────────────────────────────────────────────────────────────

    def _check_availability(self) -> bool:
        try:
            import pyannote.audio  # noqa: F401
            token = os.environ.get("HF_TOKEN", "").strip()
            if not token:
                logger.warning(
                    "[DIARIZATION] pyannote.audio установлена, но HF_TOKEN не задан. "
                    "Добавьте HF_TOKEN в .env файл."
                )
                return False
            return True
        except ImportError:
            logger.info(
                "[DIARIZATION] pyannote.audio не установлена; "
                "диаризация недоступна."
            )
            return False

    def _get_pipeline(self):
        if self._pipeline is None:
            import torch
            from pyannote.audio import Pipeline
            token = os.environ.get("HF_TOKEN", "").strip()
            if not token:
                raise ValueError("[DIARIZATION] HF_TOKEN не задан")
            # huggingface_hub >= 0.20 reads HF_TOKEN env var automatically;
            # passing use_auth_token= or token= raises TypeError on newer versions.
            # We set it explicitly so pyannote picks it up without an argument.
            os.environ.setdefault("HUGGING_FACE_HUB_TOKEN", token)
            self._pipeline = Pipeline.from_pretrained(
                "pyannote/speaker-diarization-3.1",
            )
            device = self.config.device  # "cuda" или "cpu"
            if device == "cuda" and torch.cuda.is_available():
                self._pipeline = self._pipeline.to(torch.device("cuda"))
                logger.info("[DIARIZATION] ✓ Pipeline загружен (pyannote 3.1 CUDA)")
            else:
                if device == "cuda":
                    logger.warning("[DIARIZATION] CUDA запрошена, но недоступна — используется CPU")
                logger.info("[DIARIZATION] ✓ Pipeline загружен (pyannote 3.1 CPU)")
        return self._pipeline

    @staticmethod
    def _align_speakers(
        whisper_segments: List[TranscriptSegment],
        diar_segments: list,  # [(start, end, speaker), ...]
    ) -> List[TranscriptSegment]:
        """
        Сопоставить Whisper-сегменты со спикерами по overlapping интервалов.
        Каждому Whisper-сегменту назначаем спикера с наибольшим overlap.
        """
        result = []
        for seg in whisper_segments:
            speaker = _find_dominant_speaker(
                seg.start, seg.end, diar_segments
            )
            result.append(
                TranscriptSegment(
                    start=seg.start,
                    end=seg.end,
                    speaker=speaker,
                    text=seg.text,
                )
            )
        return result


def _find_dominant_speaker(
    seg_start: float,
    seg_end: float,
    diar_segments: list,
) -> Optional[str]:
    """Найти спикера с наибольшим временем пересечения с сегментом"""
    speaker_time: dict = {}
    for d_start, d_end, speaker in diar_segments:
        overlap_start = max(seg_start, d_start)
        overlap_end = min(seg_end, d_end)
        overlap = max(0.0, overlap_end - overlap_start)
        if overlap > 0:
            speaker_time[speaker] = speaker_time.get(speaker, 0.0) + overlap

    if not speaker_time:
        return None
    return max(speaker_time, key=speaker_time.get)  # type: ignore[arg-type]
