"""Las rutas clínicas usadas por el panel médico deben publicarse en la API."""

from app.main import app


def test_patient_and_hce_routes_are_exposed() -> None:
    paths = app.openapi()["paths"]

    assert "get" in paths["/api/v1/pacientes/{id_paciente}"]
    assert "get" in paths["/api/v1/hce/pacientes/{id_paciente}"]
    assert "post" in paths["/api/v1/hce/pacientes/{id_paciente}/consultas"]
