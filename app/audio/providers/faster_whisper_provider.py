"""faster-whisper transcription provider."""

from __future__ import annotations

from importlib import import_module
from pathlib import Path
import subprocess
import tempfile
from threading import Lock
from typing import Any, Optional

from app.audio.providers.base import TranscriptionProvider
from app.audio.schemas import AudioSegment, AudioTranscriptionResponse


_AUTO_LANGUAGE_HINTS = {"", "auto", "automatic", "detect", "detect_language", "none", "null"}


def _normalize_language_hint(language_hint: Optional[str]) -> Optional[str]:
    """Map UI/API autodetect values to None for faster-whisper."""

    if language_hint is None:
        return None
    normalized = str(language_hint).strip().lower()
    if normalized in _AUTO_LANGUAGE_HINTS:
        return None
    return normalized


class FasterWhisperProvider(TranscriptionProvider):
    """Lazy-loaded faster-whisper provider."""

    def __init__(self, settings: dict[str, object]) -> None:
        self.settings = settings
        self._model: Any = None
        self._model_lock = Lock()
        self._model_loaded = False

    @property
    def name(self) -> str:
        return "faster_whisper"

    def load(self, force_reload: bool = False):
        if self._model is not None and not force_reload:
            return self._model

        with self._model_lock:
            if self._model is not None and not force_reload:
                return self._model

            try:
                faster_whisper = import_module("faster_whisper")
            except ImportError as exc:
                raise RuntimeError(
                    "faster-whisper is not installed or could not be imported."
                ) from exc

            try:
                self._model = faster_whisper.WhisperModel(
                    str(self.settings["model_name"]),
                    device=str(self.settings["device"]),
                    compute_type=str(self.settings["compute_type"]),
                )
            except Exception as exc:
                raise RuntimeError("Failed to initialize faster-whisper model.") from exc

            self._model_loaded = True
            return self._model

    def warmup(self, force_reload: bool = False) -> None:
        self.load(force_reload=force_reload)

    def transcribe(
        self,
        file_path: Path,
        language_hint: Optional[str] = None,
    ) -> AudioTranscriptionResponse:
        if not file_path.exists():
            raise ValueError("Audio file does not exist.")

        model = self.load()
        language = _normalize_language_hint(language_hint)
        if language is None:
            language = _normalize_language_hint(str(self.settings["language_default"]))

        try:
            segments_iter, info = self._transcribe_with_model(model, file_path, language)
        except Exception as original_exc:
            converted_path: Optional[Path] = None
            try:
                converted_path = self._convert_to_wav(file_path)
                segments_iter, info = self._transcribe_with_model(
                    model,
                    converted_path,
                    language,
                )
            except Exception as fallback_exc:
                raise RuntimeError(
                    "Failed to transcribe audio file after direct decode and WAV "
                    f"conversion. direct_error={original_exc}; "
                    f"conversion_or_retry_error={fallback_exc}"
                ) from fallback_exc
            finally:
                if converted_path is not None:
                    converted_path.unlink(missing_ok=True)

        detected_duration = getattr(info, "duration", None)
        if (
            detected_duration is not None
            and detected_duration > int(self.settings["max_duration_seconds"])
        ):
            raise ValueError(
                f"Audio duration exceeds maximum of {self.settings['max_duration_seconds']} seconds."
            )

        segment_models: list[AudioSegment] = []
        text_parts: list[str] = []
        for segment in segments_iter:
            segment_text = str(getattr(segment, "text", "")).strip()
            segment_models.append(
                AudioSegment(
                    start=float(getattr(segment, "start", 0.0)),
                    end=float(getattr(segment, "end", 0.0)),
                    text=segment_text,
                )
            )
            if segment_text:
                text_parts.append(segment_text)

        return AudioTranscriptionResponse(
            ok=True,
            text=" ".join(text_parts).strip(),
            language=getattr(info, "language", None),
            duration_seconds=detected_duration,
            engine=self.name,
            model=str(self.settings["model_name"]),
            segments=segment_models,
            message=None,
        )

    def is_loaded(self) -> bool:
        return self._model_loaded and self._model is not None

    def _transcribe_with_model(
        self,
        model: Any,
        file_path: Path,
        language: Optional[str],
    ):
        return model.transcribe(
            str(file_path),
            beam_size=int(self.settings["beam_size"]),
            language=language,
            vad_filter=bool(self.settings["vad_filter"]),
        )

    def _convert_to_wav(self, file_path: Path) -> Path:
        """Convert arbitrary supported containers to a Whisper-friendly WAV."""

        with tempfile.NamedTemporaryFile(
            suffix=".wav",
            prefix=f"{file_path.stem}_",
            dir=file_path.parent,
            delete=False,
        ) as temp_file:
            output_path = Path(temp_file.name)

        command = [
            "ffmpeg",
            "-y",
            "-i",
            str(file_path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-f",
            "wav",
            str(output_path),
        ]
        try:
            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
            )
        except FileNotFoundError as exc:
            output_path.unlink(missing_ok=True)
            raise RuntimeError("ffmpeg is not installed in the runtime image.") from exc
        except Exception:
            output_path.unlink(missing_ok=True)
            raise

        if result.returncode != 0:
            output_path.unlink(missing_ok=True)
            stderr = result.stderr.strip() or "unknown ffmpeg error"
            raise RuntimeError(f"ffmpeg conversion failed: {stderr}")

        return output_path
