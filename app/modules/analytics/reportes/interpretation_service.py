"""Bounded CU22 interpretation; provider output is never trusted as a query."""

import re
import unicodedata

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session

from . import service
from .catalog import MODALITIES, REPORTS, STATES, public_catalog
from .groq_client import (
    InterpretationProvider, ProviderInvalid, ProviderRateLimited,
    ProviderTimeout, ProviderUnavailable,
)
from .interpretation_schemas import (
    InterpretRequest, InterpretResponse, ProposedInterpretation,
)
from .periods import resolve_period
from .schemas import QueryRequest


FIELDS = sorted({name for report in REPORTS.values()
                 for name in report.dimensions + report.metrics})
FILTER_FIELDS = sorted({name for report in REPORTS.values() for name in report.filters})


def _object(properties: dict) -> dict:
    return {"type": "object", "properties": properties,
            "required": list(properties), "additionalProperties": False}


PROVIDER_SCHEMA = _object({
    "estado": {"type": "string", "enum": ["valida", "aclaracion", "no_admitida"]},
    "reporte": {"type": "string", "enum": [*REPORTS, ""]},
    "periodo": _object({"desde": {"type": "string"}, "hasta": {"type": "string"}}),
    "filtros": {"type": "array", "items": _object({
        "campo": {"type": "string", "enum": FILTER_FIELDS},
        "valor": {"type": "string"},
    })},
    "agrupacion": {"type": "array", "items": {"type": "string", "enum": FIELDS}},
    "columnas": {"type": "array", "items": {"type": "string", "enum": FIELDS}},
    "orden": {"type": "array", "items": _object({
        "campo": {"type": "string", "enum": FIELDS},
        "direccion": {"type": "string", "enum": ["asc", "desc"]},
    })},
    "campos_aclaracion": {"type": "array", "items": {"type": "string", "enum": [
        "reporte", "periodo", "id_medico", "id_especialidad", "filtros",
        "agrupacion", "columnas", "orden",
    ]}},
})


def _fold(value: str) -> str:
    return "".join(char for char in unicodedata.normalize("NFD", value.casefold())
                   if not unicodedata.combining(char))


def _answer(state: str, summary: str, fields: list[str] | None = None,
            warnings: list[str] | None = None) -> InterpretResponse:
    return InterpretResponse(
        estado=state, definicion=None, resumen=summary,
        campos_aclaracion=fields or [], advertencias=warnings or [],
    )


def _report_evidence(text: str) -> str | None:
    if re.search(r"\bcancelacion(?:es)?\b|\bcancelad[ao]s?\b", text):
        return "cancelaciones"
    if re.search(r"\bpacientes?\s+(?:unicos?|distintos?)\b", text):
        return "pacientes_unicos"
    if re.search(r"\bencuentros?\b|\bconsultas?\s+registradas?\b", text):
        return "encuentros"
    if re.search(r"\bcitas?\b", text):
        return "citas"
    return None


def _group_mentioned(text: str, field: str) -> bool:
    # An ordering clause is not evidence of a requested grouping.
    text = re.sub(r"\bordenad[oa]s?\s+por\s+\w+\b", "", text)
    phrases = {
        "fecha": r"\bpor\s+(?:fecha|dia|dias)\b|\bdiari[oa]s?\b|\bpor\s+(?:medico|doctora?|medica)\s+y\s+(?:fecha|dia|dias)\b",
        "id_medico": r"\bpor\s+(?:medico|doctora?|medica)\b|\bpor\s+(?:fecha|dia|dias)\s+y\s+(?:medico|doctora?|medica)\b",
        "id_especialidad": r"\bpor\s+especialidad\b",
        "estado": r"\bpor\s+estado\b",
        "modalidad": r"\bpor\s+modalidad\b",
    }
    return bool(re.search(phrases.get(field, r"a^"), text))


def _aliases(text: str, options: dict) -> tuple[str, dict[str, dict[str, int]], list[str]]:
    redacted = text
    aliases: dict[str, dict[str, int]] = {"id_medico": {}, "id_especialidad": {}}
    ambiguous: list[str] = []
    for field, collection, prefix in (
        ("id_medico", "medicos", "MEDICO"),
        ("id_especialidad", "especialidades", "ESPECIALIDAD"),
    ):
        names: dict[str, list[int]] = {}
        for item in options[collection]:
            name = _fold(item["nombre"]).strip()
            names.setdefault(name, []).append(item[field])
        for name in sorted(names, key=len, reverse=True):
            expression = r"(?<!\w)" + re.escape(name) + r"(?!\w)"
            if not re.search(expression, redacted):
                continue
            if len(names[name]) != 1:
                ambiguous.append(field)
                continue
            token = f"{prefix}_{len(aliases[field]) + 1}"
            redacted = re.sub(expression, token, redacted)
            aliases[field][token] = names[name][0]
        explicit = re.compile(r"\b" + field + r"\s*(?:=|:)?\s*(\d+)\b")
        for match in list(explicit.finditer(redacted)):
            number = int(match.group(1))
            allowed = {item[field] for item in options[collection]}
            if number not in allowed:
                ambiguous.append(field)
                continue
            token = f"{prefix}_{len(aliases[field]) + 1}"
            redacted = redacted.replace(match.group(0), token, 1)
            aliases[field][token] = number
    return redacted, aliases, list(dict.fromkeys(ambiguous))


def interpret(db: Session, clinic_id: int, request: InterpretRequest,
              provider: InterpretationProvider) -> InterpretResponse:
    folded = _fold(request.texto)
    if re.search(r"\b(?:ausentismo|ausencias?)\b", folded):
        return _answer("no_admitida", "Ausentismo no disponible: SIN_ESTADO_AUSENCIA.",
                       warnings=["No se sustituye por cancelaciones."])
    if re.search(r"\b(?:id_clinica|tenant_id|sql|select|drop|join|tabla_origen)\b", folded) or re.search(
        r"\b(?:otra|diferente)\s+clinica\b|\bclinica\s*(?:id|numero|nro|#|=|:|\d)", folded
    ):
        return _answer("no_admitida", "La solicitud contiene instrucciones o campos no admitidos.")
    if re.search(r"\b(?:ingresos|facturacion|recaudacion)\b", folded):
        return _answer("no_admitida", "La métrica solicitada no está en el catálogo de reportes.")
    if re.search(r"[\w.+-]+@[\w.-]+\.[a-z]{2,}|(?<!\d)\d{7,}(?!\d)", folded):
        return _answer("no_admitida", "Retira datos personales innecesarios de la solicitud.")
    if re.search(r"\b(?:paciente|usuario)\s+(?!unico\b|distinto\b)[a-z]{2,}(?:\s+[a-z]{2,})?\b", folded):
        return _answer("no_admitida", "Retira datos personales innecesarios de la solicitud.")
    report_id = _report_evidence(folded)
    if re.search(r"\bencuentros?\b", folded) and re.search(r"\bcitas?\b", folded):
        return _answer("aclaracion", "Elige un solo tipo de reporte.", ["reporte"])
    if report_id is None:
        return _answer("aclaracion", "Indica un reporte del catálogo: citas, cancelaciones, encuentros o pacientes únicos.",
                       ["reporte"])
    period = resolve_period(folded, request.fecha_referencia)
    if period is None:
        return _answer("aclaracion", "Indica un período completo: por ejemplo, del 1 de enero de 2026 al 3 de octubre de 2026, o septiembre de 2026. Comprueba que las fechas sean reales, estén en orden y no superen 366 días; para «este mes» se necesita la fecha actual.",
                       ["periodo"])
    # The model receives only aliases for in-scope, explicitly named options.
    scoped = service.options(db, clinic_id)
    redacted, aliases, ambiguous = _aliases(folded, scoped)
    if ambiguous:
        return _answer("aclaracion", "La opción indicada es ambigua o no está disponible en esta clínica.",
                       ambiguous)
    if re.search(r"\b(?:del|de la|para el)\s+(?:doctor|doctora|medico|medica)\s+[a-z]{2,}\b", redacted) and not aliases["id_medico"]:
        return _answer("aclaracion", "Indica el nombre completo de un médico disponible.", ["id_medico"])
    if re.search(r"\bespecialidad\s+[a-z]{2,}\b", redacted) and not aliases["id_especialidad"]:
        return _answer("aclaracion", "Indica una especialidad disponible.", ["id_especialidad"])
    prompt = {
        "texto": redacted,
        "reporte_identificado": report_id,
        "periodo_resuelto": {"desde": period[0].isoformat(), "hasta": period[1].isoformat()},
        "catalogo": [{"id": item["id"], "dimensiones": item["dimensiones"],
                       "columnas": item["columnas"], "filtros": [f["campo"] for f in item["filtros"]]}
                      for item in public_catalog()["reportes"]],
        "alias_disponibles": {field: list(values) for field, values in aliases.items()},
        "regla": "Definición nueva. No hay configuración previa ni resultados.",
    }
    try:
        raw = provider.generate(prompt, PROVIDER_SCHEMA)
    except (ProviderInvalid, ProviderRateLimited, ProviderTimeout, ProviderUnavailable):
        raise
    except Exception as exc:
        raise ProviderUnavailable from exc
    try:
        proposed = ProposedInterpretation.model_validate(raw)
    except ValidationError as exc:
        raise ProviderInvalid from exc
    report_spec = REPORTS[report_id]
    if (len(set(proposed.agrupacion)) != len(proposed.agrupacion) or
        any(field not in report_spec.dimensions for field in proposed.agrupacion)):
        raise ProviderInvalid
    if (len({item.campo for item in proposed.orden}) != len(proposed.orden) or
        any(item.campo not in report_spec.dimensions + report_spec.metrics or
            item.direccion not in {"asc", "desc"} for item in proposed.orden)):
        raise ProviderInvalid
    requested_group = any(_group_mentioned(folded, field) for field in report_spec.dimensions)
    requested_group = requested_group or bool(re.search(
        r"\b(?:agrupad[oa]s?|agrupar|agrupacion|desglosad[oa]s?|desglose)\b", folded
    ))
    if re.search(r"\bsin\s+(?:agrupar|agrupacion|desglose)\b", folded):
        requested_group = False
    explicit_columns = bool(re.search(r"\bcolumnas?\b", folded)) or any(
        metric != report_spec.primary and _fold(metric.replace("_", " ")) in folded
        for metric in report_spec.metrics
    )
    explicit_order = bool(re.search(r"\b(?:ordenad[oa]s?|ordenar|orden)\b", folded))
    if proposed.estado == "aclaracion":
        requested = {"agrupacion": requested_group, "columnas": explicit_columns,
                     "orden": explicit_order}
        unresolved = [field for field in proposed.campos_aclaracion
                      if field not in requested or requested[field]]
        if not proposed.campos_aclaracion:
            unresolved = ["filtros"]
        if unresolved:
            return _answer("aclaracion", "La solicitud necesita una aclaración antes de generar.",
                           unresolved)
        # A provider request to clarify only omitted preferences is not an
        # ambiguity. Report and period were established from the text locally.
        expected_period = (period[0].isoformat(), period[1].isoformat())
        proposed_period = (proposed.periodo.desde, proposed.periodo.hasta)
        if proposed.reporte not in {"", report_id} or proposed_period not in {
            ("", ""), expected_period,
        }:
            raise ProviderInvalid
        proposed = proposed.model_copy(update={
            "estado": "valida", "reporte": report_id,
            "periodo": proposed.periodo.model_copy(update={
                "desde": expected_period[0], "hasta": expected_period[1],
            }),
        })
    if proposed.estado == "no_admitida":
        # Report and period were already verified against the local catalog.
        raise ProviderInvalid
    if proposed.reporte != report_id:
        return _answer("aclaracion", "No se pudo confirmar el tipo de reporte solicitado.", ["reporte"])
    if (proposed.periodo.desde, proposed.periodo.hasta) != (
        period[0].isoformat(), period[1].isoformat()
    ):
        return _answer("aclaracion", "No se pudo confirmar el período solicitado.", ["periodo"])
    if (len(set(proposed.columnas)) != len(proposed.columnas) or
        any(field not in report_spec.dimensions + report_spec.metrics for field in proposed.columnas)):
        raise ProviderInvalid
    if not requested_group:
        # A model-suggested grouping cannot add a preference absent from text.
        proposed = proposed.model_copy(update={"agrupacion": []})
    converted = []
    used_aliases: dict[str, set[str]] = {"id_medico": set(), "id_especialidad": set()}
    for item in proposed.filtros:
        value: int | str = item.valor
        if item.campo in aliases:
            if item.valor not in aliases[item.campo]:
                return _answer("aclaracion", "La opción indicada no se pudo resolver en esta clínica.", [item.campo])
            used_aliases[item.campo].add(item.valor)
            value = aliases[item.campo][item.valor]
        elif item.campo == "estado" and item.valor not in STATES:
            raise ProviderInvalid
        elif item.campo == "modalidad" and item.valor not in MODALITIES:
            raise ProviderInvalid
        if item.campo in {"estado", "modalidad"} and _fold(str(value))[:7] not in folded:
            return _answer("aclaracion", "Confirma el valor del filtro solicitado.", ["filtros"])
        converted.append({"campo": item.campo, "operador": "eq", "valor": value})
    for field, values in aliases.items():
        if set(values) != used_aliases[field]:
            return _answer("aclaracion", "Confirma la opción mencionada antes de aplicar filtros.", [field])
    for field in REPORTS[report_id].dimensions:
        requested = _group_mentioned(folded, field)
        selected = field in proposed.agrupacion
        if requested != selected:
            return _answer("aclaracion", "Confirma las agrupaciones solicitadas.", ["agrupacion"])
    if explicit_columns and not proposed.columnas and not re.search(
        r"\bcolumnas?\s+(?:predeterminadas?|por defecto)\b", folded
    ):
        raise ProviderInvalid
    for metric in REPORTS[report_id].metrics:
        if explicit_columns and metric != REPORTS[report_id].primary and metric in proposed.columnas:
            phrase = _fold(metric.replace("_", " "))
            if phrase not in folded:
                return _answer("aclaracion", "Confirma la métrica adicional solicitada.", ["columnas"])
    for field in REPORTS[report_id].dimensions:
        if re.search(r"\bordenad[oa]s?\s+por\s+" + field.replace("id_", "") + r"\b", folded):
            if not any(item.campo == field for item in proposed.orden):
                return _answer("aclaracion", "Confirma el criterio de orden solicitado.", ["orden"])
    if re.search(r"\bdescendente\b", redacted) and not any(
        item.direccion == "desc" for item in proposed.orden
    ):
        return _answer("aclaracion", "Confirma el orden descendente solicitado.", ["orden"])
    # Empty lists invoke the same catalog defaults as /consulta. Model-generated
    # dimensions/sorts are not an instruction when the user did not request them.
    columns = proposed.columnas if explicit_columns else []
    if explicit_order and not proposed.orden and not re.search(r"\borden\s+por defecto\b", folded):
        raise ProviderInvalid
    order = [item.model_dump() for item in proposed.orden] if explicit_order else []
    if explicit_order and not proposed.agrupacion and any(
        item.campo in report_spec.dimensions for item in proposed.orden
    ):
        return _answer("aclaracion", "Ordenar por una dimensión requiere agrupar por ella.",
                       ["agrupacion"])
    try:
        candidate = QueryRequest(
            reporte=proposed.reporte,
            periodo={"desde": period[0], "hasta": period[1]},
            filtros=converted, agrupacion=proposed.agrupacion,
            columnas=columns, orden=order,
            pagina=1, tamano_pagina=20,
        )
        definition, report = service.normalize(db, clinic_id, candidate)
    except ValidationError as exc:
        raise ProviderInvalid from exc
    except HTTPException as exc:
        if exc.status_code == 404:
            return _answer("no_admitida", "Una opción solicitada no está disponible en esta clínica.")
        if exc.status_code == 422:
            raise ProviderInvalid from exc
        raise
    warnings = [report.semantics, "Ausentismo no disponible: SIN_ESTADO_AUSENCIA."]
    if definition.agrupacion and "pacientes_unicos" in report.metrics:
        warnings.append("Los pacientes únicos globales no se obtienen sumando grupos.")
    summary = f"{report.title} del {period[0].isoformat()} al {period[1].isoformat()}."
    if definition.agrupacion:
        summary += " Agrupado por " + ", ".join(definition.agrupacion) + "."
    if definition.filtros:
        summary += " Con filtros: " + ", ".join(item.campo for item in definition.filtros) + "."
    return InterpretResponse(estado="valida", definicion=definition, resumen=summary,
                             campos_aclaracion=[], advertencias=warnings)
