"""CU22 interpretation tests use only fake provider responses and in-memory SQLite."""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import text

from app.core.config import settings
from app.core.database import get_db
from app.modules.analytics.router import router
from app.modules.analytics.reportes.groq_client import (
    GroqProvider, ProviderRateLimited, ProviderTimeout, get_interpretation_provider,
)
from app.modules.analytics.reportes import service
from app.modules.auth.dependencies import get_current_user
import test_cu22_reports as report_fixture


def proposal(prompt, **changes):
    result = {
        "estado": "valida", "reporte": prompt["reporte_identificado"],
        "periodo": prompt["periodo_resuelto"], "filtros": [],
        "agrupacion": ["fecha"],
        "columnas": ["fecha", prompt["reporte_identificado"]],
        "orden": [{"campo": "fecha", "direccion": "asc"}],
        "campos_aclaracion": [],
    }
    result.update(changes)
    return result


class FakeProvider:
    def __init__(self, output=None):
        self.output = output
        self.calls = []

    def generate(self, prompt, schema):
        self.calls.append((prompt, schema))
        if isinstance(self.output, Exception):
            raise self.output
        return self.output(prompt) if callable(self.output) else (self.output or proposal(prompt))


class CU22InterpretationTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        report_fixture.CU22ReportsTestCase.setUpClass()
        cls.SessionLocal = report_fixture.CU22ReportsTestCase.SessionLocal

    @classmethod
    def tearDownClass(cls):
        report_fixture.CU22ReportsTestCase.tearDownClass()

    def setUp(self):
        self.user = report_fixture.CU22ReportsTestCase._user()
        self.provider = FakeProvider()
        self.app = FastAPI()
        self.app.include_router(router)

        def local_db():
            with self.SessionLocal() as session:
                yield session

        self.app.dependency_overrides[get_db] = local_db
        self.app.dependency_overrides[get_current_user] = lambda: self.user
        self.app.dependency_overrides[get_interpretation_provider] = lambda: self.provider
        self.client = TestClient(self.app)

    def post(self, text="Citas de septiembre de 2026 por fecha", **extra):
        return self.client.post("/analytics/reportes/interpretar", json={"texto": text, **extra})

    def test_valid_normalized_without_query_or_export(self):
        with patch.object(service, "query", side_effect=AssertionError("query called")):
            response = self.post()
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["estado"], "valida")
        self.assertEqual(body["definicion"]["periodo"],
                         {"desde": "2026-09-01", "hasta": "2026-09-30"})
        self.assertEqual(body["definicion"]["agrupacion"], ["fecha"])
        self.assertEqual(body["definicion"]["pagina"], 1)
        self.assertIn("Ausentismo no disponible", " ".join(body["advertencias"]))
        self.assertNotIn("id_clinica", body["definicion"])
        self.assertEqual(len(self.provider.calls), 1)
        prompt, schema = self.provider.calls[0]
        self.assertEqual(schema["additionalProperties"], False)
        self.assertNotIn("medicos", json.dumps(prompt))

    def test_two_groups_and_order_match_contract_example(self):
        self.provider.output = lambda prompt: proposal(
            prompt, agrupacion=["fecha", "id_medico"],
            columnas=["fecha", "id_medico", "citas"],
        )
        result = self.post("Citas de septiembre de 2026 por fecha y médico, ordenadas por fecha").json()
        self.assertEqual(result["estado"], "valida")
        self.assertEqual(result["definicion"]["agrupacion"], ["fecha", "id_medico"])
        self.assertEqual(result["definicion"]["orden"],
                         [{"campo": "fecha", "direccion": "asc"}])

    def test_this_month_uses_explicit_reference_and_month_without_year_clarifies(self):
        without = self.post("Citas de este mes")
        self.assertEqual(without.json()["estado"], "aclaracion")
        self.assertIn("periodo", without.json()["campos_aclaracion"])
        missing_year = self.post("Citas de septiembre", fecha_referencia="2026-10-03")
        self.assertEqual(missing_year.json()["estado"], "aclaracion")
        self.assertEqual(self.provider.calls, [])
        valid = self.post("Citas de este mes por fecha", fecha_referencia="2026-10-03")
        self.assertEqual(valid.json()["definicion"]["periodo"],
                         {"desde": "2026-10-01", "hasta": "2026-10-31"})

    def test_spanish_numeric_and_spoken_ranges_reach_provider_and_normalize(self):
        texts = (
            "Citas agrupadas por fecha desde el 1 de enero de 2026 hasta el 3 de octubre de 2026",
            "Citas agrupadas por fecha, desde el primero de enero de 2026 hasta el tres de octubre de 2026",
            "Citas agrupadas por fecha del uno de enero de 2026 al tres de octubre de 2026",
        )
        for text in texts:
            with self.subTest(text=text):
                self.provider.calls.clear()
                with patch.object(service, "query", side_effect=AssertionError("query called during interpretation")):
                    response = self.post(text)
                self.assertEqual(response.status_code, 200, response.text)
                body = response.json()
                self.assertEqual(body["estado"], "valida")
                definition = body["definicion"]
                self.assertEqual(definition["periodo"],
                                 {"desde": "2026-01-01", "hasta": "2026-10-03"})
                self.assertEqual(definition["agrupacion"], ["fecha"])
                self.assertEqual(len(self.provider.calls), 1)
                self.assertEqual(self.provider.calls[0][0]["periodo_resuelto"], definition["periodo"])
                query = self.client.post("/analytics/reportes/consulta", json=definition)
                self.assertEqual(query.status_code, 200, query.text)
                self.assertEqual(query.json()["definicion"], definition)
                self.assertEqual(query.json()["metricas"]["citas"]["valor"], 4)

    def test_shared_year_and_month_are_explicit_not_inferred_from_reference(self):
        cases = (
            ("Citas del 1 de enero al 3 de octubre de 2026", "2026-01-01", "2026-10-03"),
            ("Citas desde el primero de enero de 2026 hasta el tres de octubre", "2026-01-01", "2026-10-03"),
            ("Citas del 1 al 15 de septiembre de 2026", "2026-09-01", "2026-09-15"),
            ("Citas desde el veinte hasta el treinta y uno de diciembre de 2026", "2026-12-20", "2026-12-31"),
            ("Citas del veintitrés de febrero de 2026 al primero de marzo de 2026", "2026-02-23", "2026-03-01"),
            ("Citas del 1 de enero de 2024 al 31 de diciembre de 2024", "2024-01-01", "2024-12-31"),
            ("Citas desde 2026-01-01 hasta 2026-10-03", "2026-01-01", "2026-10-03"),
        )
        for text, start, end in cases:
            with self.subTest(text=text):
                response = self.post(text, fecha_referencia="2025-04-02")
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["definicion"]["periodo"],
                                 {"desde": start, "hasta": end})

    def test_invalid_inverted_long_missing_or_ambiguous_ranges_clarify_locally(self):
        texts = (
            "Citas desde el 30 de febrero de 2026 hasta el 3 de octubre de 2026",
            "Citas del 29 de febrero de 2026 al 1 de marzo de 2026",
            "Citas del 3 de octubre de 2026 al 1 de enero de 2026",
            "Citas del 1 de enero de 2025 al 3 de octubre de 2026",
            "Citas del 1 de enero al 3 de octubre",
            "Citas del primero al tres de octubre",
            "Citas del 1 de enero de 2026 al 3 de octubre de 2026 o noviembre de 2026",
        )
        for text in texts:
            with self.subTest(text=text):
                self.provider.calls.clear()
                response = self.post(text, fecha_referencia="2026-10-03")
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json()["estado"], "aclaracion")
                self.assertEqual(response.json()["campos_aclaracion"], ["periodo"])
                self.assertIsNone(response.json()["definicion"])
                self.assertNotIn("ISO", response.json()["resumen"])
                self.assertNotIn("fecha_referencia", response.json()["resumen"])
                self.assertEqual(self.provider.calls, [])

    def test_invalid_date_and_unsupported_metrics_or_columns(self):
        self.assertEqual(self.post("Citas del 1 al 15 de septiembre de 2026").json()["estado"],
                         "valida")
        self.assertEqual(self.post("Ausentismo de septiembre de 2026").json()["estado"],
                         "no_admitida")
        self.assertEqual(self.post("Ingresos de septiembre de 2026").json()["estado"],
                         "no_admitida")
        self.provider.output = lambda prompt: proposal(
            prompt, agrupacion=[], columnas=["tabla_inventada"], orden=[],
        )
        self.assertEqual(self.post("Citas de septiembre de 2026 con columna citas").status_code, 502)
        self.assertEqual(self.post("Reporte de citas de septiembre de 2026").status_code, 502)
        self.provider.output = lambda prompt: proposal(
            prompt, agrupacion=[], columnas=["citas"], orden=[],
            filtros=[{"campo": "estado", "valor": "INVENTADO"}],
        )
        self.assertEqual(self.post("Reporte de citas de septiembre de 2026").status_code, 502)
        self.provider.output = lambda prompt: proposal(prompt, estado="no_admitida")
        self.assertEqual(self.post("Reporte de citas de septiembre de 2026").status_code, 502)

    def test_ungrouped_request_uses_catalog_defaults_despite_provider_dimension_columns(self):
        # Exact shape observed from the real provider for this user request.
        self.provider.output = lambda prompt: proposal(
            prompt, agrupacion=[],
            columnas=["fecha", "id_medico", "id_especialidad", "estado", "modalidad", "citas"],
            orden=[],
        )
        with patch.object(service, "query", side_effect=AssertionError("query called during interpretation")):
            response = self.post("Reporte de citas de septiembre de 2026",
                                 fecha_referencia="2026-10-03")
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["estado"], "valida")
        definition = body["definicion"]
        self.assertEqual(definition["reporte"], "citas")
        self.assertEqual(definition["agrupacion"], [])
        self.assertEqual(definition["columnas"], ["citas"])
        self.assertEqual(definition["orden"], [])
        result = self.client.post("/analytics/reportes/consulta", json=definition)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["definicion"], definition)
        self.assertEqual(result.json()["metricas"]["citas"]["valor"], 4)
        self.assertEqual(result.json()["filas"], [{"citas": 4}])

    def test_optional_clarification_uses_defaults_for_ungrouped_reports(self):
        for report, expected in (("citas", 4), ("encuentros", 2),
                                 ("cancelaciones", 1), ("pacientes_unicos", 1)):
            with self.subTest(report=report):
                self.provider.output = lambda prompt: proposal(
                    prompt, estado="aclaracion",
                    campos_aclaracion=["agrupacion", "columnas", "orden"],
                )
                name = "Pacientes únicos" if report == "pacientes_unicos" else report.capitalize()
                with patch.object(service, "query", side_effect=AssertionError("query called during interpretation")):
                    response = self.post(f"{name} de septiembre de 2026",
                                         fecha_referencia="2026-10-03")
                self.assertEqual(response.status_code, 200, response.text)
                body = response.json()
                self.assertEqual(body["estado"], "valida")
                definition = body["definicion"]
                self.assertEqual(definition["reporte"], report)
                self.assertEqual(definition["periodo"],
                                 {"desde": "2026-09-01", "hasta": "2026-09-30"})
                self.assertEqual(definition["agrupacion"], [])
                self.assertEqual(definition["columnas"], [report])
                self.assertEqual(definition["orden"], [])
                result = self.client.post("/analytics/reportes/consulta", json=definition)
                self.assertEqual(result.status_code, 200, result.text)
                self.assertEqual(result.json()["definicion"], definition)
                self.assertEqual(result.json()["metricas"][report]["valor"], expected)

    def test_optional_clarification_keeps_explicit_group_request(self):
        self.provider.output = lambda prompt: proposal(
            prompt, estado="aclaracion",
            campos_aclaracion=["agrupacion", "columnas", "orden"],
            agrupacion=[], columnas=[], orden=[],
        )
        response = self.post("Encuentros de septiembre de 2026 agrupados por fecha")
        self.assertEqual(response.json()["estado"], "aclaracion")
        self.assertEqual(response.json()["campos_aclaracion"], ["agrupacion"])
        self.assertIsNone(response.json()["definicion"])

    def test_optional_clarification_keeps_explicit_columns_and_order(self):
        self.provider.output = lambda prompt: proposal(
            prompt, estado="aclaracion",
            campos_aclaracion=["agrupacion", "columnas", "orden"],
            agrupacion=[], columnas=[], orden=[],
        )
        response = self.post("Citas de septiembre de 2026 con columnas citas, ordenadas por citas")
        self.assertEqual(response.json()["estado"], "aclaracion")
        self.assertEqual(response.json()["campos_aclaracion"], ["columnas", "orden"])
        self.assertIsNone(response.json()["definicion"])

    def test_optional_clarification_does_not_hide_invalid_catalog_fields(self):
        self.provider.output = lambda prompt: proposal(
            prompt, estado="aclaracion", campos_aclaracion=["agrupacion", "columnas", "orden"],
            agrupacion=["estado"], columnas=["encuentros"], orden=[],
        )
        self.assertEqual(self.post("Encuentros de septiembre de 2026").status_code, 502)

    def test_optional_clarification_can_use_locally_confirmed_report_and_period(self):
        self.provider.output = lambda prompt: proposal(
            prompt, estado="aclaracion", reporte="",
            periodo={"desde": "", "hasta": ""},
            campos_aclaracion=["agrupacion", "columnas", "orden"],
            agrupacion=[], columnas=[], orden=[],
        )
        body = self.post("Encuentros de septiembre de 2026").json()
        self.assertEqual(body["estado"], "valida")
        self.assertEqual(body["definicion"]["reporte"], "encuentros")
        self.assertEqual(body["definicion"]["periodo"],
                         {"desde": "2026-09-01", "hasta": "2026-09-30"})

    def test_patient_name_is_not_sent_to_provider(self):
        result = self.post("Citas de septiembre de 2026 del paciente Juan Pérez")
        self.assertEqual(result.json()["estado"], "no_admitida")
        self.assertEqual(self.provider.calls, [])

    def test_clinic_context_cannot_change_authenticated_scope(self):
        allowed = self.post("Citas de mi clínica de septiembre de 2026 por fecha")
        self.assertEqual(allowed.json()["estado"], "valida")
        self.provider.calls.clear()
        rejected = self.post("Citas de la clínica 2 de septiembre de 2026")
        self.assertEqual(rejected.json()["estado"], "no_admitida")
        self.assertEqual(self.provider.calls, [])

    def test_doctor_alias_is_scoped_and_duplicate_name_clarifies(self):
        self.provider.output = lambda prompt: proposal(
            prompt, filtros=[{"campo": "id_medico", "valor": "MEDICO_1"}],
            agrupacion=[], columnas=["citas"], orden=[],
        )
        response = self.post("Citas de septiembre de 2026 del médico Ana Pérez")
        self.assertEqual(response.json()["estado"], "valida")
        self.assertEqual(response.json()["definicion"]["filtros"][0]["valor"], 20)
        sent = self.provider.calls[-1][0]
        self.assertNotIn("Ana Pérez", json.dumps(sent))
        self.assertNotIn("ana perez", json.dumps(sent))
        self.provider.calls.clear()
        alien = self.post("Citas de septiembre de 2026 id_medico=30")
        self.assertIsNone(alien.json()["definicion"])
        self.assertEqual(self.provider.calls, [])
        with self.SessionLocal() as db:
            db.execute(text("INSERT INTO medicos (id_medico,id_usuario) VALUES (21,100)"))
            db.commit()
        try:
            duplicate = self.post("Citas de septiembre de 2026 del médico Ana Pérez")
            self.assertEqual(duplicate.json()["estado"], "aclaracion")
            self.assertIn("id_medico", duplicate.json()["campos_aclaracion"])
        finally:
            with self.SessionLocal() as db:
                db.execute(text("DELETE FROM medicos WHERE id_medico=21"))
                db.commit()

    def test_authorization_and_forbidden_body(self):
        self.user = report_fixture.CU22ReportsTestCase._user(role="MEDICO")
        self.assertEqual(self.post().status_code, 403)
        self.assertEqual(self.provider.calls, [])
        self.user = report_fixture.CU22ReportsTestCase._user()
        self.assertEqual(self.client.post("/analytics/reportes/interpretar", json={
            "texto": "Citas de septiembre de 2026", "id_clinica": 2,
        }).status_code, 422)

    def test_clinic_two_only_accepts_its_own_doctor_id(self):
        self.user = report_fixture.CU22ReportsTestCase._user(clinic=2, role_clinic=2)
        self.assertEqual(self.post("Citas de septiembre de 2026 id_medico=20").json()["estado"],
                         "aclaracion")
        self.provider.output = lambda prompt: proposal(
            prompt, filtros=[{"campo": "id_medico", "valor": "MEDICO_1"}],
            agrupacion=[], columnas=["citas"], orden=[],
        )
        result = self.post("Citas de septiembre de 2026 id_medico=30").json()
        self.assertEqual(result["definicion"]["filtros"][0]["valor"], 30)

    def test_model_cannot_change_period_or_add_unrequested_group(self):
        self.provider.output = lambda prompt: proposal(
            prompt, periodo={"desde": "2026-01-01", "hasta": "2026-01-31"},
        )
        self.assertEqual(self.post().json()["campos_aclaracion"], ["periodo"])
        self.provider.output = lambda prompt: proposal(
            prompt, agrupacion=["id_medico"], columnas=["id_medico", "citas"],
            orden=[{"campo": "id_medico", "direccion": "asc"}],
        )
        ungrouped = self.post("Citas de septiembre de 2026").json()
        self.assertEqual(ungrouped["estado"], "valida")
        self.assertEqual(ungrouped["definicion"]["agrupacion"], [])
        self.assertEqual(ungrouped["definicion"]["columnas"], ["citas"])
        self.assertEqual(ungrouped["definicion"]["orden"], [])
        self.provider.output = lambda prompt: proposal(prompt)
        self.assertEqual(self.post("Citas de septiembre de 2026 ordenadas por fecha").json()["campos_aclaracion"],
                         ["agrupacion"])

    def test_invalid_provider_timeout_rate_and_missing_configuration(self):
        self.provider.output = {"estado": "valida"}
        self.assertEqual(self.post().status_code, 502)
        self.provider.output = ProviderTimeout()
        self.assertEqual(self.post().status_code, 504)
        self.provider.output = ProviderRateLimited()
        self.assertEqual(self.post().status_code, 429)
        self.app.dependency_overrides[get_interpretation_provider] = GroqProvider
        with patch.object(settings, "GROQ_API_KEY", SecretStr("")):
            self.assertEqual(self.post().status_code, 503)

    def test_groq_adapter_uses_strict_schema_without_real_network(self):
        prompt = {"texto": "solicitud sintética"}
        completion = {"choices": [{"finish_reason": "stop",
                                   "message": {"content": json.dumps({"estado": "aclaracion"})}}]}
        fake_response = SimpleNamespace(status_code=200, content=b"{}", json=lambda: completion)

        class FakeClient:
            def __init__(self, **kwargs):
                self.timeout = kwargs["timeout"]

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def post(self, url, *, headers, json):
                self_outer.assertEqual(url, "https://api.groq.com/openai/v1/chat/completions")
                self_outer.assertTrue(headers["Authorization"].startswith("Bearer "))
                self_outer.assertEqual(json["response_format"]["type"], "json_schema")
                self_outer.assertIs(json["response_format"]["json_schema"]["strict"], True)
                self_outer.assertNotIn("tools", json)
                return fake_response

        self_outer = self
        with patch.object(settings, "GROQ_API_KEY", SecretStr("synthetic-test-key")), \
             patch("app.modules.analytics.reportes.groq_client.httpx.Client", FakeClient):
            self.assertEqual(GroqProvider().generate(prompt, {"type": "object"}),
                             {"estado": "aclaracion"})


if __name__ == "__main__":
    unittest.main()
