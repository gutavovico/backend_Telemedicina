"""Bounded validation of transient browser recordings before provider upload."""

from fastapi import HTTPException, UploadFile

from .groq_client import ProviderInvalid
from .transcription_client import TranscriptionProvider


MAX_AUDIO_BYTES = 5 * 1024 * 1024
FORMATS = {
    "webm": "audio/webm", "ogg": "audio/ogg",
    "mp4": "audio/mp4", "wav": "audio/wav",
}


def _format(data: bytes) -> str | None:
    if data.startswith(b"\x1a\x45\xdf\xa3") and b"webm" in data[:4096].lower():
        return "webm"
    if data.startswith(b"OggS\x00"):
        return "ogg"
    if len(data) >= 12 and data[4:8] == b"ftyp":
        return "mp4"
    if data.startswith(b"RIFF") and data[8:12] == b"WAVE":
        return "wav"
    return None


def transcribe(audio: UploadFile, provider: TranscriptionProvider) -> dict[str, str]:
    try:
        data = audio.file.read(MAX_AUDIO_BYTES + 1)
    finally:
        audio.file.close()
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "El audio supera el límite de 5 MiB.")
    if not data:
        raise HTTPException(422, "El audio está vacío.")
    kind = _format(data)
    declared = (audio.content_type or "").split(";", 1)[0].lower().strip()
    extension = (audio.filename or "").rsplit(".", 1)[-1].lower()
    if kind is None or declared != FORMATS.get(kind) or extension != kind:
        raise HTTPException(422, "El formato de audio no es válido o no coincide con el archivo.")
    text = provider.transcribe(data, f"dictado.{kind}", FORMATS[kind])
    if not isinstance(text, str) or not text.strip() or len(text.strip()) > 1000:
        raise ProviderInvalid
    return {"texto": text.strip()}
