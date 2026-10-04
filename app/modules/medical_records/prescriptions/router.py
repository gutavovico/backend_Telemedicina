"""Router CU16: 8 endpoints exactos del contrato prescriptions.md §4.

Orden crítico: `/validar/{codigo}` se registra antes de `/{id_receta}`.
"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.modules.auth.dependencies import get_current_tenant_id, get_current_user
from app.modules.auth.models import Usuario
from app.modules.medical_records.prescriptions import schemas, service
from app.modules.medical_records.prescriptions.dependencies import (
    PERMISO_CATALOG_WRITE,
    PERMISO_READ,
    require_prescription_roles,
)
from app.modules.medical_records.prescriptions.service import PrescriptionError


router = APIRouter(tags=["Recetas Médicas Digitales (CU16)"])
medicamentos_router = APIRouter(prefix="/api/v1/medicamentos",
                                tags=["Catálogo de Medicamentos (CU16)"])


def _trusted_proxy_set() -> set:
    """Conjunto de IPs de proxies de confianza desde TRUSTED_PROXY_IPS.

    Vacío por defecto: no se confía en ningún proxy. Las entradas
    inválidas se ignoran (validadas con `ipaddress`, nunca se aceptan
    valores arbitrarios).
    """
    import ipaddress

    raw = (settings.TRUSTED_PROXY_IPS or "")
    trusted: set = set()
    for part in raw.split(","):
        candidate = part.strip()
        if not candidate:
            continue
        try:
            trusted.add(str(ipaddress.ip_address(candidate)))
        except ValueError:
            continue
    return trusted


def _client_ip(request: Request) -> str:
    """Resuelve la IP real sin confiar automáticamente en X-Forwarded-For.

    - Si `request.client.host` pertenece a TRUSTED_PROXY_IPS, acepta el
      primer IP válido de `X-Forwarded-For` (validado con `ipaddress`).
    - En caso contrario ignora el encabezado y usa `request.client.host`.
    - Encabezados inválidos o sin IP válida se ignoran.
    El rate limit y la telemetría utilizan esta IP resuelta.
    """
    import ipaddress

    direct_ip = request.client.host if request.client is not None else "desconocida"
    trusted = _trusted_proxy_set()
    # Normalizar comparación (IPv4/IPv6); si el host directo no es IP
    # válida, nunca se considera proxy de confianza.
    try:
        direct_norm = str(ipaddress.ip_address(direct_ip)) if direct_ip != "desconocida" else "desconocida"
    except ValueError:
        return direct_ip
    if direct_norm not in trusted:
        return direct_ip
    forwarded = request.headers.get("X-Forwarded-For")
    if not forwarded:
        return direct_ip
    for part in forwarded.split(","):
        candidate = part.strip()
        if not candidate:
            continue
        try:
            return str(ipaddress.ip_address(candidate))
        except ValueError:
            continue
    return direct_ip


async def prescription_error_handler(request: Request, exc: PrescriptionError) -> JSONResponse:
    """Handler registrado a nivel de aplicación (ver app/main.py)."""
    headers = dict(exc.headers or {})
    if "/validar/" in request.url.path:
        headers.setdefault("Cache-Control", "no-store")
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.message, "code": exc.code},
        headers=headers or None,
    )


# --------------------------------------------------------------------------- #
# 4.1 GET /api/v1/medicamentos
# --------------------------------------------------------------------------- #

@medicamentos_router.get("", response_model=schemas.MedicamentoListResponse)
def buscar_medicamentos(
    query: Optional[str] = Query(default=None),
    estado: Optional[str] = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_prescription_roles(["MEDICO", "ADMIN"])),
):
    _exigir_permiso_catalogo(db, current_user, PERMISO_READ)
    items, total = service.listar_medicamentos(db, query=query, estado=estado, skip=skip, limit=limit)
    return schemas.MedicamentoListResponse(
        items=[schemas.MedicamentoResponse.model_validate(m) for m in items], total=total
    )


# --------------------------------------------------------------------------- #
# 4.2 POST /api/v1/medicamentos
# --------------------------------------------------------------------------- #

@medicamentos_router.post("", response_model=schemas.MedicamentoResponse, status_code=201)
def crear_medicamento(
    payload: schemas.MedicamentoCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_prescription_roles(["ADMIN"])),
):
    _exigir_permiso_catalogo(db, current_user, PERMISO_CATALOG_WRITE)
    medicamento = service.crear_medicamento(db, payload, current_user)
    return schemas.MedicamentoResponse.model_validate(medicamento)


def _exigir_permiso_catalogo(db: Session, user: Usuario, permiso: str) -> None:
    from fastapi import HTTPException, status
    from app.modules.medical_records.clinical_documents.dependencies import user_has_permission
    if not user_has_permission(db, user.id_rol, permiso):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail=f"Permiso denegado. Se requiere el permiso '{permiso}'.")


# --------------------------------------------------------------------------- #
# 4.3 POST /api/v1/recetas
# --------------------------------------------------------------------------- #

@router.post("/api/v1/recetas", status_code=201)
def emitir_receta(
    payload: schemas.RecetaCreateRequest,
    response: Response,
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
    tenant_id: Optional[int] = Depends(get_current_tenant_id),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    receta, es_reintento = service.emitir_receta(
        db, user=current_user, tenant_id=tenant_id,
        payload=payload, payload_raw=payload.model_dump(mode="json"),
        idempotency_key=idempotency_key or "", client_ip=_client_ip(request),
    )
    if es_reintento:
        response.status_code = 200
    else:
        response.status_code = 201
    return service.receta_to_response(db, receta)


# --------------------------------------------------------------------------- #
# 4.4 GET /api/v1/recetas
# --------------------------------------------------------------------------- #

@router.get("/api/v1/recetas", response_model=schemas.RecetaListResponse)
def listar_recetas(
    id_paciente: Optional[int] = Query(default=None),
    id_medico: Optional[int] = Query(default=None),
    estado: Optional[str] = Query(default=None),
    desde: Optional[date] = Query(default=None),
    hasta: Optional[date] = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
    tenant_id: Optional[int] = Depends(get_current_tenant_id),
):
    items, total = service.listar_recetas(
        db, user=current_user, tenant_id=tenant_id, id_paciente=id_paciente,
        id_medico=id_medico, estado=estado, desde=desde, hasta=hasta,
        skip=skip, limit=limit,
    )
    return schemas.RecetaListResponse(
        items=[service.receta_to_response(db, r) for r in items], total=total
    )


# --------------------------------------------------------------------------- #
# 4.8 GET /api/v1/recetas/validar/{codigo} (público; antes de /{id})
# --------------------------------------------------------------------------- #

@router.get("/api/v1/recetas/validar/{codigo_verificacion}")
def validar_receta_publica(
    codigo_verificacion: str,
    request: Request,
    db: Session = Depends(get_db),
):
    resultado = service.validar_publica(db, codigo_verificacion, _client_ip(request))
    return JSONResponse(
        content=resultado,
        headers={"Cache-Control": "no-store"},
    )


# --------------------------------------------------------------------------- #
# 4.5 GET /api/v1/recetas/{id_receta}
# --------------------------------------------------------------------------- #

@router.get("/api/v1/recetas/{id_receta}", response_model=schemas.RecetaResponse)
def obtener_receta(
    id_receta: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
    tenant_id: Optional[int] = Depends(get_current_tenant_id),
):
    receta = service.obtener_receta(db, user=current_user, tenant_id=tenant_id,
                                    id_receta=id_receta, client_ip=_client_ip(request))
    return service.receta_to_response(db, receta)


# --------------------------------------------------------------------------- #
# 4.6 GET /api/v1/recetas/{id_receta}/pdf
# --------------------------------------------------------------------------- #

@router.get("/api/v1/recetas/{id_receta}/pdf")
def descargar_pdf_receta(
    id_receta: int,
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
    tenant_id: Optional[int] = Depends(get_current_tenant_id),
):
    contenido, folio = service.obtener_pdf_receta(
        db, user=current_user, tenant_id=tenant_id, id_receta=id_receta,
        client_ip=_client_ip(request),
    )
    return Response(
        content=contenido,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="receta_{folio}.pdf"'},
    )


# --------------------------------------------------------------------------- #
# 4.7 POST /api/v1/recetas/{id_receta}/anular
# --------------------------------------------------------------------------- #

@router.post("/api/v1/recetas/{id_receta}/anular", response_model=schemas.RecetaResponse)
def anular_receta(
    id_receta: int,
    payload: schemas.RecetaAnulacionRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user),
    tenant_id: Optional[int] = Depends(get_current_tenant_id),
):
    receta = service.anular_receta(db, user=current_user, tenant_id=tenant_id,
                                   id_receta=id_receta, payload=payload,
                                   client_ip=_client_ip(request))
    return service.receta_to_response(db, receta)
