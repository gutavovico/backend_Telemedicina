"""Replaceable Groq audio transcription adapter; no database or report access."""

from typing import Protocol

import httpx

from app.core.config import settings

from .groq_client import ProviderInvalid, ProviderRateLimited, ProviderTimeout, ProviderUnavailable


GROQ_TRANSCRIPTION_URL = "https://api.groq.com/openai/v1/audio/transcriptions"


class TranscriptionProvider(Protocol):
    def transcribe(self, audio: bytes, filename: str, mime: str) -> str: ...


class GroqTranscriptionProvider:
    def transcribe(self, audio: bytes, filename: str, mime: str) -> str:
        key = settings.GROQ_API_KEY.get_secret_value()
        if not key:
            raise ProviderUnavailable("configuration")
        timeout = min(max(settings.GROQ_TRANSCRIPTION_TIMEOUT_SECONDS, 1.0), 60.0)
        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.post(
                    GROQ_TRANSCRIPTION_URL,
                    headers={"Authorization": f"Bearer {key}"},
                    data={"model": settings.GROQ_TRANSCRIPTION_MODEL,
                          "language": "es", "response_format": "json"},
                    files={"file": (filename, audio, mime)},
                )
        except httpx.TimeoutException as exc:
            raise ProviderTimeout from exc
        except httpx.HTTPError as exc:
            raise ProviderUnavailable from exc
        if response.status_code == 429:
            raise ProviderRateLimited
        if response.status_code >= 400:
            raise ProviderUnavailable
        if len(response.content) > 16384:
            raise ProviderInvalid
        try:
            text = response.json()["text"]
        except (ValueError, KeyError, TypeError) as exc:
            raise ProviderInvalid from exc
        if not isinstance(text, str) or not text.strip() or len(text.strip()) > 1000:
            raise ProviderInvalid
        return text.strip()


def get_transcription_provider() -> TranscriptionProvider:
    return GroqTranscriptionProvider()
