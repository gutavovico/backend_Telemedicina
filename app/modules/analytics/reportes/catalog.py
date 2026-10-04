"""Closed server-side catalog for CU22; client strings never become SQL identifiers."""

from dataclasses import dataclass

MAX_PERIOD_DAYS = 366
MAX_FILTERS = 8
MAX_GROUPS = 2
MAX_COLUMNS = 6
MAX_PAGE_SIZE = 100
MAX_EXPORT_ROWS = 5000
FORMATS = ("pdf", "xlsx", "csv", "html")
MODALITIES = ("PRESENCIAL", "TELEMEDICINA", "CONFLICTO", "DESCONOCIDA", "OTRA")
STATES = ("PENDIENTE", "CONFIRMADA", "COMPLETADA", "FINALIZADA", "CANCELADA")
NO_SHOW = {"disponible": False, "valor": None, "causa": "SIN_ESTADO_AUSENCIA"}


@dataclass(frozen=True)
class Report:
    id: str
    title: str
    source: str
    primary: str
    metrics: tuple[str, ...]
    dimensions: tuple[str, ...]
    filters: tuple[str, ...]
    semantics: str


REPORTS = {
    "encuentros": Report(
        "encuentros", "Encuentros con consulta registrada", "consultas", "encuentros",
        ("encuentros", "pacientes_unicos"),
        ("fecha", "id_medico", "id_especialidad", "modalidad"),
        ("id_medico", "id_especialidad", "modalidad"),
        "Citas distintas con consulta registrada por fecha de consulta; no es el total exhaustivo histórico de atenciones.",
    ),
    "pacientes_unicos": Report(
        "pacientes_unicos", "Pacientes únicos atendidos", "consultas", "pacientes_unicos",
        ("pacientes_unicos", "encuentros"),
        ("fecha", "id_medico", "id_especialidad", "modalidad"),
        ("id_medico", "id_especialidad", "modalidad"),
        "Pacientes distintos entre citas con consulta válida por fecha de consulta; los grupos no se suman para obtener el global.",
    ),
    "citas": Report(
        "citas", "Actividad de citas", "citas", "citas",
        ("citas", "cancelaciones"),
        ("fecha", "id_medico", "id_especialidad", "estado", "modalidad"),
        ("id_medico", "id_especialidad", "estado", "modalidad"),
        "Citas distintas por fecha programada; una cita no demuestra una atención efectiva.",
    ),
    "cancelaciones": Report(
        "cancelaciones", "Cancelaciones de citas", "citas", "cancelaciones",
        ("cancelaciones", "citas"),
        ("fecha", "id_medico", "id_especialidad", "estado", "modalidad"),
        ("id_medico", "id_especialidad", "estado", "modalidad"),
        "Citas con estado CANCELADA por fecha programada; no se conoce la fecha histórica de cancelación ni se calcula una tasa.",
    ),
}


def public_catalog() -> dict:
    return {
        "reportes": [
            {
                "id": report.id, "titulo": report.title, "fuente": report.source,
                "metrica_principal": report.primary, "metricas": list(report.metrics),
                "dimensiones": list(report.dimensions), "columnas": list(report.dimensions + report.metrics),
                "ordenables": list(report.dimensions + report.metrics),
                "filtros": [{"campo": field, "operadores": ["eq"]} for field in report.filters],
                "semantica": report.semantics,
            }
            for report in REPORTS.values()
        ],
        "metricas_no_disponibles": {"ausentismo": NO_SHOW},
        "formatos": list(FORMATS),
        "limites": {
            "periodo_dias": MAX_PERIOD_DAYS, "filtros": MAX_FILTERS,
            "agrupaciones": MAX_GROUPS, "columnas": MAX_COLUMNS,
            "tamano_pagina": MAX_PAGE_SIZE, "filas_exportacion": MAX_EXPORT_ROWS,
        },
        "modalidades": list(MODALITIES),
        "categorias_nulas": {"id_especialidad": "Sin especialidad registrada"},
    }
