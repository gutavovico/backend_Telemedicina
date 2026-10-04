"""CU22/CU27 report contracts against a deliberately legacy-shaped SQLite schema."""

import csv
import io
import re
import unittest
import zipfile
from collections import Counter
from types import SimpleNamespace
from unittest.mock import patch
from xml.etree import ElementTree

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import get_db
from app.main import app as production_app
from app.modules.analytics.router import router
from app.modules.analytics.exportacion import exporter
from app.modules.analytics.reportes.schemas import QueryResponse
from app.modules.auth.dependencies import get_current_user


PERIOD = {"desde": "2026-09-01", "hasta": "2026-09-30"}
SHEET_NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


class CU22ReportsTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        cls.SessionLocal = sessionmaker(bind=cls.engine)
        with cls.engine.begin() as connection:
            for ddl in (
                "CREATE TABLE clinicas (id_clinica INTEGER PRIMARY KEY, estado TEXT)",
                "CREATE TABLE usuarios (id_usuario INTEGER PRIMARY KEY, id_clinica INTEGER, nombres TEXT, apellidos TEXT)",
                "CREATE TABLE medicos (id_medico INTEGER PRIMARY KEY, id_usuario INTEGER)",
                "CREATE TABLE especialidades (id_especialidad INTEGER PRIMARY KEY, nombre TEXT)",
                "CREATE TABLE citas (id_cita INTEGER PRIMARY KEY, id_paciente INTEGER, id_medico INTEGER, id_especialidad INTEGER, fecha_cita DATE, estado TEXT, tipo_consulta TEXT, modalidad TEXT)",
                "CREATE TABLE historias_clinicas (id_historia INTEGER PRIMARY KEY, id_clinica INTEGER, id_paciente INTEGER)",
                "CREATE TABLE consultas (id_consulta INTEGER PRIMARY KEY, id_clinica INTEGER, id_historia INTEGER, id_cita INTEGER, id_medico INTEGER, fecha_consulta DATETIME)",
            ):
                connection.exec_driver_sql(ddl)
            for statement in (
                "INSERT INTO clinicas VALUES (1,'ACTIVO'),(2,'ACTIVO'),(3,'INACTIVO')",
                "INSERT INTO usuarios VALUES (100,1,'Ana','Pérez'),(200,2,'Luis','Ajeno')",
                "INSERT INTO medicos VALUES (20,100),(30,200)",
                "INSERT INTO especialidades VALUES (5,'Cardiología'),(6,'Dermatología')",
                "INSERT INTO citas VALUES (1,1,20,5,'2026-09-10','FINALIZADA','TELEMEDICINA','TELEMEDICINA'),(2,1,30,6,'2026-09-10','FINALIZADA','PRESENCIAL','PRESENCIAL'),(3,2,20,5,'2026-09-12','CANCELADA','PRESENCIAL','PRESENCIAL'),(4,2,20,NULL,'2026-09-13','PENDIENTE','PRESENCIAL','TELEMEDICINA'),(5,1,20,5,'2026-09-14','FINALIZADA','TELEMEDICINA','TELEMEDICINA')",
                "INSERT INTO historias_clinicas VALUES (10,1,1),(20,2,1),(30,1,2)",
                "INSERT INTO consultas VALUES (1,1,10,1,20,'2026-09-10 10:00:00'),(2,1,10,1,20,'2026-09-10 11:00:00'),(3,2,20,2,30,'2026-09-10 10:00:00'),(4,1,10,5,20,'2026-09-11 10:00:00'),(5,1,10,2,30,'2026-09-10 12:00:00'),(6,1,30,1,20,'2026-09-10 13:00:00')",
            ):
                connection.exec_driver_sql(statement)

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()

    def setUp(self):
        self.user = self._user()
        self.app = FastAPI()
        self.app.include_router(router)

        def local_db():
            with self.SessionLocal() as session:
                yield session

        self.app.dependency_overrides[get_db] = local_db
        self.app.dependency_overrides[get_current_user] = lambda: self.user
        self.client = TestClient(self.app)

    @staticmethod
    def _user(clinic=1, role="ADMIN", role_state="ACTIVO", role_clinic=1,
              user_state="ACTIVO"):
        return SimpleNamespace(
            id_clinica=clinic, estado=user_state,
            rol=SimpleNamespace(nombre=role, estado=role_state, id_clinica=role_clinic),
        )

    def _query(self, report="encuentros", **extra):
        return {"reporte": report, "periodo": PERIOD, **extra}

    def test_catalog_options_and_authorization(self):
        # FastAPI 0.12x conserva include_router como _IncludedRouter diferido.
        # Contar contextos efectivos también detecta rutas públicas duplicadas.
        routes = (
            (context.path, getattr(context, "original_route", context).methods)
            for route in production_app.routes
            for context in (route.effective_route_contexts() if hasattr(route, "effective_route_contexts")
                            else (route,))
            if getattr(context, "path", "").startswith("/analytics/reportes")
        )
        registered = Counter(
            (path, method)
            for path, methods in routes
            for method in methods
        )
        self.assertEqual(registered, Counter({
            ("/analytics/reportes/catalogo", "GET"): 1,
            ("/analytics/reportes/opciones", "GET"): 1,
            ("/analytics/reportes/consulta", "POST"): 1,
            ("/analytics/reportes/exportar", "POST"): 1,
            ("/analytics/reportes/interpretar", "POST"): 1,
            ("/analytics/reportes/transcribir", "POST"): 1,
        }))
        catalog = self.client.get("/analytics/reportes/catalogo").json()
        self.assertEqual({r["id"] for r in catalog["reportes"]},
                         {"encuentros", "citas", "cancelaciones", "pacientes_unicos"})
        self.assertEqual(catalog["metricas_no_disponibles"]["ausentismo"]["causa"],
                         "SIN_ESTADO_AUSENCIA")
        self.assertEqual(catalog["categorias_nulas"]["id_especialidad"],
                         "Sin especialidad registrada")
        self.assertEqual(self.client.get("/analytics/reportes/opciones").json()["medicos"],
                         [{"id_medico": 20, "nombre": "Ana Pérez"}])
        self.assertEqual(self.client.get("/analytics/reportes/opciones").json()["especialidades"],
                         [{"id_especialidad": 5, "nombre": "Cardiología"}])
        self.user = self._user(clinic=2, role_clinic=2)
        self.assertEqual(self.client.get("/analytics/reportes/opciones").json()["medicos"],
                         [{"id_medico": 30, "nombre": "Luis Ajeno"}])
        for user in (
            self._user(role="MEDICO"), self._user(role_state="INACTIVO"),
            self._user(user_state="INACTIVO"),
            self._user(clinic=1, role_clinic=2), self._user(clinic=3, role_clinic=3),
            self._user(clinic=None),
        ):
            self.user = user
            for path in ("catalogo", "opciones"):
                self.assertEqual(self.client.get(f"/analytics/reportes/{path}").status_code, 403)
            self.assertEqual(self.client.post("/analytics/reportes/consulta",
                                              json=self._query()).status_code, 403)
            self.assertEqual(self.client.post("/analytics/reportes/exportar",
                                              json={**self._query(), "formato": "csv"}).status_code, 403)
        self.app.dependency_overrides.pop(get_current_user)
        self.assertEqual(self.client.get("/analytics/reportes/catalogo").status_code, 401)

    def test_encounters_distinct_patient_and_clinic_isolation(self):
        response = self.client.post(
            "/analytics/reportes/consulta",
            json=self._query("encuentros", agrupacion=["fecha"],
                             columnas=["fecha", "encuentros", "pacientes_unicos"]),
            headers={"X-Tenant-ID": "2"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["metricas"]["encuentros"]["valor"], 2)
        self.assertEqual(body["metricas"]["pacientes_unicos"]["valor"], 1)
        self.assertEqual(body["total"], 2)
        self.assertEqual(body["filas"], [
            {"fecha": "2026-09-10", "encuentros": 1, "pacientes_unicos": 1},
            {"fecha": "2026-09-11", "encuentros": 1, "pacientes_unicos": 1},
        ])
        self.assertIsNone(body["metricas"]["ausentismo"]["valor"])
        self.user = self._user(clinic=2, role_clinic=2)
        other = self.client.post("/analytics/reportes/consulta", json=self._query()).json()
        self.assertEqual(other["metricas"]["encuentros"]["valor"], 1)
        unique = self.client.post("/analytics/reportes/consulta",
                                  json=self._query("pacientes_unicos")).json()
        self.assertEqual(unique["filas"], [{"pacientes_unicos": 1}])
        empty = self.client.post("/analytics/reportes/consulta", json=self._query(
            periodo={"desde": "2026-08-01", "hasta": "2026-08-31"}
        )).json()
        self.assertEqual((empty["total"], empty["filas"]), (0, []))
        self.assertEqual(empty["metricas"]["encuentros"]["valor"], 0)
        self.assertIsNone(empty["metricas"]["ausentismo"]["valor"])

    def test_appointments_cancellations_modalities_and_null_specialty(self):
        body = self.client.post(
            "/analytics/reportes/consulta",
            json=self._query("citas", agrupacion=["modalidad"],
                             columnas=["modalidad", "citas", "cancelaciones"]),
        ).json()
        self.assertEqual(body["metricas"]["citas"]["valor"], 4)
        self.assertEqual(body["metricas"]["cancelaciones"]["valor"], 1)
        self.assertEqual({row["modalidad"]: row["citas"] for row in body["filas"]},
                         {"CONFLICTO": 1, "PRESENCIAL": 1, "TELEMEDICINA": 2})
        cancel = self.client.post(
            "/analytics/reportes/consulta",
            json=self._query("cancelaciones", filtros=[
                {"campo": "estado", "operador": "eq", "valor": "CANCELADA"}
            ]),
        ).json()
        self.assertEqual(cancel["filas"], [{"cancelaciones": 1}])
        conflict = self.client.post(
            "/analytics/reportes/consulta",
            json=self._query("citas", filtros=[
                {"campo": "modalidad", "operador": "eq", "valor": "CONFLICTO"}
            ]),
        ).json()
        self.assertEqual(conflict["metricas"]["citas"]["valor"], 1)
        specialty = self.client.post(
            "/analytics/reportes/consulta",
            json=self._query("citas", agrupacion=["id_especialidad"],
                             columnas=["id_especialidad", "citas"]),
        ).json()
        self.assertIn({"id_especialidad": None, "citas": 1}, specialty["filas"])

    def test_filters_pagination_and_invalid_requests(self):
        request = self._query("encuentros", agrupacion=["fecha"],
                              columnas=["fecha", "encuentros"],
                              orden=[{"campo": "fecha", "direccion": "desc"}],
                              pagina=2, tamano_pagina=1)
        body = self.client.post("/analytics/reportes/consulta", json=request).json()
        self.assertEqual(body["total"], 2)
        self.assertEqual(body["metricas"]["encuentros"]["valor"], 2)
        self.assertEqual(body["filas"][0]["fecha"], "2026-09-10")
        for field, value in (("id_medico", 30), ("id_especialidad", 6)):
            response = self.client.post("/analytics/reportes/consulta", json=self._query(
                filtros=[{"campo": field, "operador": "eq", "valor": value}]
            ))
            self.assertEqual(response.status_code, 404, response.text)
        invalid = [
            self._query("ausentismo"),
            self._query("otro"),
            self._query(periodo={"desde": "2026-10-01", "hasta": "2026-09-01"}),
            self._query(periodo={"desde": "2025-01-01", "hasta": "2026-09-01"}),
            self._query(columnas=["tabla_origen", "encuentros"]),
            self._query(agrupacion=["fecha", "fecha"]),
            self._query(agrupacion=["fecha"], columnas=["encuentros"]),
            self._query(orden=[{"campo": "fecha", "direccion": "asc"}]),
            self._query(pagina="2"),
            self._query(filtros=[{"campo": "estado", "operador": "eq", "valor": "CANCELADA"}]),
            self._query(id_clinica=2),
        ]
        for payload in invalid:
            self.assertEqual(self.client.post("/analytics/reportes/consulta", json=payload).status_code, 422)

    def test_four_exports_are_real_and_complete(self):
        request = self._query("citas", agrupacion=["fecha"],
                              columnas=["fecha", "citas", "cancelaciones"],
                              pagina=2, tamano_pagina=1)
        query = self.client.post("/analytics/reportes/consulta", json=request).json()
        self.assertEqual(query["total"], 4)
        self.assertEqual(len(query["filas"]), 1)
        files = {}
        for format_name in ("csv", "xlsx", "html", "pdf"):
            response = self.client.post("/analytics/reportes/exportar",
                                        json={**request, "formato": format_name})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertIn(f".{format_name}", response.headers["content-disposition"])
            self.assertIn("Content-Disposition", response.headers["access-control-expose-headers"])
            files[format_name] = response.content
        csv_rows = list(csv.reader(io.StringIO(files["csv"].decode("utf-8-sig"))))
        self.assertIn(["Fecha", "Citas", "Cancelaciones"], csv_rows)
        self.assertEqual(sum(row[1] == "1" for row in csv_rows if len(row) == 3), 4)
        full = self.client.post("/analytics/reportes/consulta",
                                json={**request, "pagina": 1, "tamano_pagina": 100}).json()
        exported_dates = [row[0] for row in csv_rows if len(row) == 3 and row[0].startswith("2026-")]
        self.assertEqual(exported_dates, [row["fecha"] for row in full["filas"]])
        self.assertIn("2026-09-13", files["html"].decode())
        with zipfile.ZipFile(io.BytesIO(files["xlsx"])) as archive:
            sheet = ElementTree.fromstring(archive.read("xl/worksheets/sheet1.xml"))
            self.assertEqual(len(sheet.findall(".//s:row", SHEET_NS)), 14)
            self.assertNotIn(b"<f>", archive.read("xl/worksheets/sheet1.xml"))
        self.assertTrue(files["pdf"].startswith(b"%PDF-1.4"))
        self.assertIn(b"/Type /Page ", files["pdf"])
        self.assertIn("Clínica ID".encode("cp1252").hex().upper().encode(), files["pdf"])
        self.user = self._user(clinic=2, role_clinic=2)
        other = self.client.post("/analytics/reportes/exportar",
                                 json={**request, "formato": "csv"}).content.decode("utf-8-sig")
        self.assertNotIn("2026-09-12", other)
        self.assertNotIn("2026-09-13", other)

    def test_export_limit_and_text_escaping(self):
        request = self._query("citas", agrupacion=["fecha"],
                              columnas=["fecha", "citas"])
        with patch("app.modules.analytics.reportes.service.MAX_EXPORT_ROWS", 1):
            response = self.client.post("/analytics/reportes/exportar",
                                        json={**request, "formato": "csv"})
        self.assertEqual(response.status_code, 413)
        body = self.client.post("/analytics/reportes/consulta", json=request).json()
        result = QueryResponse.model_validate(body)
        result.filas[0]["fecha"] = '=HYPERLINK("https://example.invalid")<tag>'
        csv_text = exporter.csv_file(result, 1).decode("utf-8-sig")
        self.assertIn("'=HYPERLINK", csv_text)
        html_text = exporter.html_file(result, 1).decode()
        self.assertIn("&lt;tag&gt;", html_text)
        with zipfile.ZipFile(io.BytesIO(exporter.xlsx_file(result, 1))) as archive:
            sheet = archive.read("xl/worksheets/sheet1.xml")
            self.assertIn(b"'=HYPERLINK", sheet)
            self.assertNotIn(b"<f>", sheet)
        result.filas = [{"fecha": "texto extenso " * 20, "citas": 1} for _ in range(80)]
        pdf = exporter.pdf_file(result, 1)
        page_count = pdf.count(b"/Type /Page ")
        self.assertGreater(page_count, 1)
        self.assertEqual(pdf.count("Clínica ID".encode("cp1252").hex().upper().encode()),
                         page_count)

    def test_pdf_rows_stay_between_rules_and_long_cells_continue_on_new_pages(self):
        body = self.client.post("/analytics/reportes/consulta", json=self._query(
            "citas", agrupacion=["fecha"], columnas=["fecha", "citas"]
        )).json()
        result = QueryResponse.model_validate(body)
        long_value = "texto extenso " * 600
        result.filas = [{"fecha": long_value, "citas": 1}]
        pdf = exporter.pdf_file(result, 1)
        streams = re.findall(rb"stream\n(.*?)\nendstream", pdf, re.DOTALL)
        self.assertGreater(len(streams), 1)
        cell_lines = []
        for stream in streams:
            rules = [float(value) for value in re.findall(
                rb"0\.7 G 0\.35 w 36\.0 ([0-9.]+) m 806\.0 [0-9.]+ l S 0 G", stream
            )]
            texts = [
                (float(x), float(y), bytes.fromhex(raw.decode()).decode("cp1252"))
                for x, y, raw in re.findall(
                    rb"BT /F[12] 8 Tf ([0-9.]+) ([0-9.]+) Td <([0-9A-F]*)> Tj ET", stream
                )
            ]
            self.assertIn("Fecha", [value for _, _, value in texts])
            for x, baseline, value in texts:
                if x < 42 or baseline < 42:  # Page metadata and footer are not table cells.
                    continue
                lower = [line for line in rules if line < baseline]
                upper = [line for line in rules if line > baseline]
                self.assertTrue(lower, value)
                self.assertGreaterEqual(baseline - max(lower), 9, value)
                if upper:
                    self.assertGreaterEqual(min(upper) - baseline, 13, value)
                if x == 42 and value != "Fecha":
                    cell_lines.append(value)
        self.assertEqual(" ".join(cell_lines).split(), long_value.split())


if __name__ == "__main__":
    unittest.main()
