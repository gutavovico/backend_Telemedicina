"""Catalog, options, and query endpoints for CU22."""

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.core.database import get_db

from . import service
from .catalog import public_catalog
from .dependencies import require_report_admin
from .schemas import QueryRequest, QueryResponse
from .groq_client import (
    get_interpretation_provider, ProviderInvalid, ProviderRateLimited,
    ProviderTimeout, ProviderUnavailable,
)
from .interpretation_schemas import InterpretRequest, InterpretResponse
from .interpretation_service import interpret
from .transcription_client import get_transcription_provider
from .transcription_service import transcribe

router = APIRouter(prefix="/analytics/reportes", tags=["CU22 Reportes / CU27 Exportación"])


@router.get("/catalogo")
def catalogo(clinic_id: int = Depends(require_report_admin)):
    return public_catalog()


@router.get("/opciones")
def opciones(db: Session = Depends(get_db), clinic_id: int = Depends(require_report_admin)):
    return service.options(db, clinic_id)


@router.post("/consulta", response_model=QueryResponse)
def consultar(
    request: QueryRequest,
    db: Session = Depends(get_db),
    clinic_id: int = Depends(require_report_admin),
):
    return service.query(db, clinic_id, request)


@router.post("/interpretar", response_model=InterpretResponse, responses={
    401: {"description": "Sesión inválida"},
    403: {"description": "Solo ADMIN activo de una clínica activa"},
    422: {"description": "Solicitud malformada"},
    429: {"description": "Límite del proveedor"},
    502: {"description": "Respuesta inválida del proveedor"},
    503: {"description": "Proveedor no configurado o no disponible"},
    504: {"description": "Tiempo de espera del proveedor agotado"},
})
def interpretar(
    request: InterpretRequest,
    db: Session = Depends(get_db),
    clinic_id: int = Depends(require_report_admin),
    provider=Depends(get_interpretation_provider),
):
    try:
        return interpret(db, clinic_id, request, provider)
    except ProviderRateLimited as exc:
        raise HTTPException(429, "Límite temporal del proveedor. Intenta más tarde.") from exc
    except ProviderTimeout as exc:
        raise HTTPException(504, "La interpretación tardó demasiado. Usa el formulario manual.") from exc
    except ProviderInvalid as exc:
        raise HTTPException(502, "La respuesta de interpretación no es válida. Usa el formulario manual.") from exc
    except ProviderUnavailable as exc:
        raise HTTPException(503, "Interpretación no disponible. Usa el formulario manual.") from exc


@router.post("/transcribir", responses={
    401: {"description": "Sesión inválida"},
    403: {"description": "Solo ADMIN activo de una clínica activa"},
    413: {"description": "Audio demasiado grande"},
    422: {"description": "Audio ausente o inválido"},
    429: {"description": "Límite del proveedor"},
    502: {"description": "Transcripción inválida"},
    503: {"description": "Proveedor no configurado o no disponible"},
    504: {"description": "Tiempo de espera agotado"},
})
async def transcribir(
    request: Request,
    audio: UploadFile = File(...),
    clinic_id: int = Depends(require_report_admin),
    provider=Depends(get_transcription_provider),
) -> dict[str, str]:
    # clinic_id is resolved by the existing ADMIN dependency; no client scope is accepted.
    form = await request.form()
    if set(form.keys()) != {"audio"} or len(form.getlist("audio")) != 1:
        audio.file.close()
        raise HTTPException(422, "Envía únicamente el archivo de audio.")
    try:
        return await run_in_threadpool(transcribe, audio, provider)
    except ProviderRateLimited as exc:
        raise HTTPException(429, "Límite temporal de transcripción. Intenta más tarde.") from exc
    except ProviderTimeout as exc:
        raise HTTPException(504, "La transcripción tardó demasiado. Escribe la solicitud manualmente.") from exc
    except ProviderInvalid as exc:
        raise HTTPException(502, "La transcripción no produjo texto válido. Reintenta o escribe la solicitud.") from exc
    except ProviderUnavailable as exc:
        raise HTTPException(503, "Transcripción no disponible. Escribe la solicitud manualmente.") from exc
