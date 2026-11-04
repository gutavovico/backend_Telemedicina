from typing import Annotated, Literal
import math
from fastapi import APIRouter, Depends, Query, Path, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.modules.auth.models import Usuario
from .dependencies import require_catalog_admin
from .schemas import PlanCreate, VersionCreate, Desactivar, PlanResponse, PlanPage, VersionPage, VersionResponse, SERVICIOS, RECURSOS
from . import service

class CatalogRoute(APIRoute):
    """Keep invalid nonfinite JSON numbers from breaking the 422 error serializer.

    Scoped to CU34: other modules retain their existing exception behavior.
    """
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def validated(request: Request):
            try:
                return await handler(request)
            except RequestValidationError as exc:
                errors = jsonable_encoder(exc.errors(), custom_encoder={
                    float: lambda value: value if math.isfinite(value) else str(value),
                    ValueError: str,
                })
                return JSONResponse(status_code=422, content={"detail": errors})
        return validated


router = APIRouter(prefix="/api/v1/planes", tags=["Planes (CU34)"],
                   route_class=CatalogRoute, dependencies=[Depends(require_catalog_admin)])
Db = Annotated[Session, Depends(get_db)]
Actor = Annotated[Usuario, Depends(require_catalog_admin)]
Id = Annotated[int, Path(gt=0)]


async def plan_error_handler(request: Request, exc: service.PlanError):
    return JSONResponse(status_code=exc.status, content={"detail": exc.detail, "code": exc.code})


def _ip(request):
    return request.client.host if request.client else None


@router.get("/opciones")
def options():
    return {"moneda": "BOB", "ciclo": "MENSUAL",
            "servicios": [{"codigo": k, "nombre": v} for k, v in SERVICIOS.items()],
            "recursos": [{"recurso": k, "unidad": v[0], "nombre": v[1]} for k, v in RECURSOS.items()]}


@router.get("", response_model=PlanPage)
def list_plans(db: Db, q: str = Query("", max_length=150), estado: Literal["ACTIVO", "INACTIVO"] | None = None,
               page: int = Query(1, ge=1), per_page: int = Query(20, ge=1, le=100)):
    return service.list_plans(db, q.strip(), estado, page, per_page)


@router.post("", response_model=PlanResponse, status_code=201)
def create(data: PlanCreate, request: Request, db: Db, user: Actor):
    return service.create(db, data, user.id_usuario, _ip(request))


@router.get("/{plan_id}", response_model=PlanResponse)
def detail(plan_id: Id, db: Db):
    return service.detail(db, plan_id)


@router.get("/{plan_id}/versiones", response_model=VersionPage)
def history(plan_id: Id, db: Db, page: int = Query(1, ge=1), per_page: int = Query(20, ge=1, le=100)):
    return service.history(db, plan_id, page, per_page)


@router.get("/{plan_id}/versiones/{numero}", response_model=VersionResponse)
def version_detail(plan_id: Id, numero: Id, db: Db):
    return service.version_detail(db, plan_id, numero)


@router.post("/{plan_id}/versiones", response_model=PlanResponse, status_code=201)
def new_version(plan_id: Id, data: VersionCreate, request: Request, db: Db, user: Actor):
    return service.new_version(db, plan_id, data, user.id_usuario, _ip(request))


@router.patch("/{plan_id}/estado", response_model=PlanResponse)
def deactivate(plan_id: Id, data: Desactivar, request: Request, db: Db, user: Actor):
    return service.deactivate(db, plan_id, user.id_usuario, _ip(request))
