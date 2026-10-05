"""CU22 dictation tests use synthetic bytes, fake Groq, and isolated SQLite."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.config import settings
from app.core.database import get_db
from app.modules.analytics.reportes import service
from app.modules.analytics.reportes.groq_client import (
    ProviderInvalid, ProviderRateLimited, ProviderTimeout, ProviderUnavailable,
)
from app.modules.analytics.reportes.transcription_client import (
    GROQ_TRANSCRIPTION_URL, GroqTranscriptionProvider, get_transcription_provider,
)
from app.modules.analytics.router import router
from app.modules.auth.dependencies import get_current_user
import test_cu22_reports as report_fixture


WAV = b"RIFF" + b"\x00\x00\x00\x00" + b"WAVEfmt " + b"\x00" * 40


class FakeTranscription:
    def __init__(self):
        self.output: str | Exception = "Encuentros de septiembre de 2026"
        self.calls = []

    def transcribe(self, audio, filename, mime):
        self.calls.append((len(audio), filename, mime))
        if isinstance(self.output, Exception):
            raise self.output
        return self.output


class CU22TranscriptionTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        report_fixture.CU22ReportsTestCase.setUpClass()
        cls.SessionLocal = report_fixture.CU22ReportsTestCase.SessionLocal

    @classmethod
    def tearDownClass(cls):
        report_fixture.CU22ReportsTestCase.tearDownClass()

    def setUp(self):
        self.user = report_fixture.CU22ReportsTestCase._user()
        self.provider = FakeTranscription()
        self.app = FastAPI()
        self.app.include_router(router)

        def local_db():
            with self.SessionLocal() as session:
                yield session

        self.app.dependency_overrides[get_db] = local_db
        self.app.dependency_overrides[get_current_user] = lambda: self.user
        self.app.dependency_overrides[get_transcription_provider] = lambda: self.provider
        self.client = TestClient(self.app)

    def post(self, data=WAV, filename="dictado.wav", mime="audio/wav"):
        return self.client.post("/analytics/reportes/transcribir",
                                files={"audio": (filename, data, mime)})

    def test_valid_audio_only_transcribes_without_query_or_interpretation(self):
        with patch.object(service, "query", side_effect=AssertionError("query called")), \
             patch("app.modules.analytics.reportes.interpretation_service.interpret",
                   side_effect=AssertionError("interpret called")):
            response = self.post()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"texto": "Encuentros de septiembre de 2026"})
        self.assertEqual(self.provider.calls, [(len(WAV), "dictado.wav", "audio/wav")])

    def test_invalid_audio_and_oversize_never_call_provider(self):
        self.assertEqual(self.post(b"").status_code, 422)
        self.assertEqual(self.post(b"not audio").status_code, 422)
        self.assertEqual(self.post(WAV, mime="audio/webm").status_code, 422)
        self.assertEqual(self.post(WAV, filename="dictado.webm").status_code, 422)
        self.assertEqual(self.post(WAV + b"x" * (5 * 1024 * 1024)).status_code, 413)
        self.assertEqual(self.provider.calls, [])

    def test_rejects_other_role_and_client_scope(self):
        self.user = report_fixture.CU22ReportsTestCase._user(role="MEDICO")
        self.assertEqual(self.post().status_code, 403)
        self.assertEqual(self.provider.calls, [])
        self.user = report_fixture.CU22ReportsTestCase._user()
        response = self.client.post("/analytics/reportes/transcribir",
                                    data={"id_clinica": "2"},
                                    files={"audio": ("dictado.wav", WAV, "audio/wav")})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(self.provider.calls, [])

    def test_provider_failures_and_empty_text(self):
        for output, status in (("  ", 502), (ProviderInvalid(), 502),
                               (ProviderRateLimited(), 429), (ProviderTimeout(), 504),
                               (ProviderUnavailable(), 503)):
            with self.subTest(status=status, output=type(output).__name__):
                self.provider.output = output
                self.assertEqual(self.post().status_code, status)

    def test_missing_configuration_without_external_call(self):
        self.app.dependency_overrides[get_transcription_provider] = GroqTranscriptionProvider
        with patch.object(settings, "GROQ_API_KEY", SecretStr("")):
            self.assertEqual(self.post().status_code, 503)

    def test_groq_adapter_sends_audio_without_real_network(self):
        testcase = self

        class FakeClient:
            def __init__(self, **kwargs):
                testcase.assertLessEqual(kwargs["timeout"], 60)

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def post(self, url, *, headers, data, files):
                testcase.assertEqual(url, GROQ_TRANSCRIPTION_URL)
                testcase.assertTrue(headers["Authorization"].startswith("Bearer "))
                testcase.assertEqual(data["model"], settings.GROQ_TRANSCRIPTION_MODEL)
                testcase.assertEqual(data["response_format"], "json")
                testcase.assertEqual(files["file"], ("dictado.wav", WAV, "audio/wav"))
                return SimpleNamespace(status_code=200, content=b'{"text":"Citas de septiembre"}',
                                       json=lambda: {"text": "Citas de septiembre"})

        with patch.object(settings, "GROQ_API_KEY", SecretStr("synthetic-test-key")), \
             patch("app.modules.analytics.reportes.transcription_client.httpx.Client", FakeClient):
            self.assertEqual(GroqTranscriptionProvider().transcribe(WAV, "dictado.wav", "audio/wav"),
                             "Citas de septiembre")


if __name__ == "__main__":
    unittest.main()
