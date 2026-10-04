"""Exercise the real local CU22/CU27 API started by run_cu22_local.py.

Uses only synthetic accounts and writes sample exports under local_artifacts/cu22.
It never imports app.core.database or reads .env.
"""

import csv
from io import StringIO
from pathlib import Path
import re
import zipfile
from xml.etree import ElementTree

import httpx


BASE = "http://127.0.0.1:8000"
PASSWORD = "Cu22-local-2026!"
OUTPUT = Path(__file__).resolve().parents[1] / "local_artifacts" / "cu22"
MIMES = {
    "pdf": "application/pdf",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv; charset=utf-8",
    "html": "text/html; charset=utf-8",
}


def login(client: httpx.Client, email: str) -> dict:
    response = client.post("/auth/login", json={"correo": email, "password": PASSWORD})
    assert response.status_code == 200, (email, response.status_code, response.text)
    token = response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    profile = client.get("/auth/me", headers=headers)
    assert profile.status_code == 200, (email, profile.text)
    return headers


def request(client: httpx.Client, headers: dict, **changes) -> dict:
    payload = {
        "reporte": "citas", "periodo": {"desde": "2026-09-01", "hasta": "2026-09-30"},
        "filtros": [{"campo": "id_medico", "operador": "eq", "valor": 20}],
        "columnas": ["fecha", "citas", "cancelaciones"],
        "agrupacion": ["fecha"], "orden": [{"campo": "fecha", "direccion": "desc"}],
        "pagina": 1, "tamano_pagina": 10,
    }
    payload.update(changes)
    response = client.post("/analytics/reportes/consulta", headers=headers, json=payload)
    assert response.status_code == 200, (response.status_code, response.text)
    body = response.json()
    assert "id_clinica" not in body["definicion"]
    return body


def main() -> None:
    with httpx.Client(base_url=BASE, timeout=15) as client:
        assert client.get("/").status_code == 200
        preflight = client.options("/analytics/reportes/consulta", headers={
            "Origin": "http://127.0.0.1:4200",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        })
        assert preflight.status_code == 200
        assert preflight.headers["access-control-allow-origin"] == "http://127.0.0.1:4200"
        assert client.get("/analytics/reportes/catalogo").status_code == 401
        admin = login(client, "admin1@example.com")
        other_admin = login(client, "admin2@example.com")
        for email in ("medico@example.com", "recepcion@example.com", "paciente@example.com"):
            headers = login(client, email)
            assert client.get("/analytics/reportes/catalogo", headers=headers).status_code == 403
            assert client.get("/analytics/reportes/opciones", headers=headers).status_code == 403
            assert client.post("/analytics/reportes/consulta", headers=headers,
                               json={"reporte": "citas", "periodo": {"desde": "2026-09-01", "hasta": "2026-09-30"}}).status_code == 403
        catalog = client.get("/analytics/reportes/catalogo", headers=admin)
        options = client.get("/analytics/reportes/opciones", headers=admin)
        assert catalog.status_code == options.status_code == 200
        assert {item["id"] for item in catalog.json()["reportes"]} == {
            "encuentros", "citas", "cancelaciones", "pacientes_unicos"}
        assert 20 in {item["id_medico"] for item in options.json()["medicos"]}
        assert 50 not in {item["id_medico"] for item in options.json()["medicos"]}
        assert {item["id_especialidad"] for item in options.json()["especialidades"]} == {5}
        other_options = client.get("/analytics/reportes/opciones", headers=other_admin).json()
        assert {item["id_medico"] for item in other_options["medicos"]} == {50}
        assert {item["id_especialidad"] for item in other_options["especialidades"]} == {6}

        first = request(client, admin)
        second = request(client, admin, pagina=2)
        assert first["total"] == second["total"] == 14
        assert len(first["filas"]) == 10 and len(second["filas"]) == 4
        assert first["metricas"]["citas"]["valor"] == 14
        assert first["metricas"]["cancelaciones"]["valor"] == 2
        assert first["metricas"]["ausentismo"] == {
            "disponible": False, "valor": None, "causa": "SIN_ESTADO_AUSENCIA"}
        dates = [row["fecha"] for row in first["filas"] + second["filas"]]
        assert dates == sorted(dates, reverse=True) and len(set(dates)) == 14
        assert first["definicion"]["orden"] == [{"campo": "fecha", "direccion": "desc"}]
        encounters = request(client, admin, reporte="encuentros",
                             columnas=["fecha", "encuentros", "pacientes_unicos"])
        assert encounters["metricas"]["encuentros"]["valor"] == 12
        assert encounters["metricas"]["pacientes_unicos"]["valor"] == 2
        assert sum(row["pacientes_unicos"] for row in encounters["filas"]) > 2
        cancellations = request(client, admin, reporte="cancelaciones",
                                filtros=[{"campo": "estado", "operador": "eq", "valor": "CANCELADA"}],
                                columnas=["fecha", "cancelaciones"])
        assert cancellations["total"] == 2
        assert cancellations["metricas"]["cancelaciones"]["valor"] == 2
        specialty = request(client, admin, filtros=[
            {"campo": "id_especialidad", "operador": "eq", "valor": 5}])
        assert specialty["total"] == 13
        empty = request(client, admin, periodo={"desde": "2026-08-01", "hasta": "2026-08-31"})
        assert empty["total"] == 0 and empty["filas"] == []
        assert empty["metricas"]["ausentismo"]["valor"] is None
        clinic_two = request(client, other_admin, filtros=[{"campo": "id_medico", "operador": "eq", "valor": 50}])
        assert clinic_two["total"] == 4 and clinic_two["metricas"]["citas"]["valor"] == 4
        assert client.post("/analytics/reportes/consulta", headers=admin,
                           json={**first["definicion"], "filtros": [
                               {"campo": "id_medico", "operador": "eq", "valor": 50}]}).status_code == 404
        assert client.post("/analytics/reportes/consulta", headers=admin,
                           json={**first["definicion"], "periodo": {
                               "desde": "2026-10-01", "hasta": "2026-09-01"}}).status_code == 422
        assert request(client, admin)["total"] == 14  # Recovery after a rejected request.

        OUTPUT.mkdir(parents=True, exist_ok=True)
        exported = {}
        for format_name, mime in MIMES.items():
            response = client.post("/analytics/reportes/exportar", headers=admin,
                                   json={**first["definicion"], "formato": format_name})
            assert response.status_code == 200, (format_name, response.status_code, response.text)
            assert response.headers["content-type"] == mime
            assert response.headers["content-disposition"].endswith(f'.{format_name}"')
            assert "Content-Disposition" in response.headers["access-control-expose-headers"]
            assert len(response.content) > 100
            path = OUTPUT / f"cu22_citas_clinica1.{format_name}"
            path.write_bytes(response.content)
            exported[format_name] = path

        rows = list(csv.reader(StringIO(exported["csv"].read_text(encoding="utf-8-sig"))))
        csv_dates = [row[0] for row in rows if len(row) == 3 and row[0].startswith("2026-")]
        assert csv_dates == dates
        assert len(csv_dates) == 14  # Page 1 had only ten rows.
        with zipfile.ZipFile(exported["xlsx"]) as archive:
            sheet = ElementTree.fromstring(archive.read("xl/worksheets/sheet1.xml"))
            ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
            xml_rows = sheet.findall(".//s:row", ns)
            assert len(xml_rows) >= 14
            xlsx_dates = [
                value.text for row in xml_rows
                for value in row.findall(".//s:t", ns)
                if value.text and re.fullmatch(r"2026-09-\d{2}", value.text)
            ]
            assert xlsx_dates == dates
        html = exported["html"].read_text(encoding="utf-8")
        html_dates = re.findall(r"<tr><td>(2026-09-\d{2})</td>", html)
        assert html_dates == dates
        pdf = exported["pdf"].read_bytes()
        assert pdf.startswith(b"%PDF-")
        pdf_text = [bytes.fromhex(raw.decode()).decode("cp1252")
                    for raw in re.findall(rb"<([0-9A-F]+)> Tj", pdf)]
        pdf_dates = [item for item in pdf_text if re.fullmatch(r"2026-09-\d{2}", item)]
        assert pdf_dates == dates
        assert any("Clínica ID: 1" in item for item in pdf_text)
        assert any("Período:" in item for item in pdf_text)
        clinic_two_export = client.post("/analytics/reportes/exportar", headers=other_admin,
                                        json={**clinic_two["definicion"], "formato": "csv"})
        assert clinic_two_export.status_code == 200
        other_csv = clinic_two_export.content.decode("utf-8-sig")
        assert "Clínica ID,2" in other_csv and "2026-09-14" not in other_csv
        assert "2026-09-04" in other_csv
        logout_login = client.post("/auth/login", json={
            "correo": "medico@example.com", "password": PASSWORD})
        assert logout_login.status_code == 200
        access = logout_login.json()["access_token"]
        refresh = logout_login.json()["refresh_token"]
        assert client.post("/auth/logout", json={"refresh_token": refresh}).status_code == 204
        assert client.get("/auth/me", headers={"Authorization": f"Bearer {access}"}).status_code == 401
        print("API real: login 5 roles; autorización; dos clínicas; catálogo/opciones; ")
        print("14 grupos en dos páginas; 12 encuentros; 2 pacientes únicos globales; ")
        print("cero registros; 404/422; PDF/XLSX/CSV/HTML completos y con MIME correcto.")
        for format_name, path in exported.items():
            print(f"{format_name}: {path} ({path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
