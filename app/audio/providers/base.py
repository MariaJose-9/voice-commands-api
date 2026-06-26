"""Base interface for audio transcription providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from app.audio.schemas import AudioTranscriptionResponse


class TranscriptionProvider(ABC):
    """Abstract interface for pluggable transcription backends."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier."""

    @abstractmethod
    def load(self, force_reload: bool = False):
        """Load and return the provider's underlying model/client."""

    @abstractmethod
    def warmup(self, force_reload: bool = False) -> None:
        """Warm up the provider without requiring a real user request."""

    @abstractmethod
    def transcribe(
        self,
        file_path: Path,
        language_hint: Optional[str] = None,
    ) -> AudioTranscriptionResponse:
        """Transcribe the given audio file."""

    @abstractmethod
    def is_loaded(self) -> bool:
        """Return whether the provider is already loaded in memory."""
