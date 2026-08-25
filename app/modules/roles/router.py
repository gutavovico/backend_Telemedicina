from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.auth.dependencies import require_admin
from app.modules.auth.models import Usuario
from app.modules.roles.schemas import (
    PermissionResponse,
    RoleCreate,
    RolePermissionsUpdate,
    RoleResponse,
    RoleStatusUpdate,
    RoleUpdate,
)
from app.modules.roles.service import (
    create_role,
    get_role_detail,
    get_role_permissions,
    list_permissions,
    list_roles,
    replace_role_permissions,
    set_role_status,
    update_role,
)

router = APIRouter(tags=["Roles y Permisos"])


@router.get(
    "/roles",
    response_model=list[RoleResponse],
    summary="Listar roles",
)
def get_roles(
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
):
    return list_roles(db)


@router.get(
    "/roles/{id_rol}",
    response_model=RoleResponse,
    summary="Obtener rol",
)
def get_role(
    id_rol: int,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
):
    return get_role_detail(db, id_rol)


@router.post(
    "/roles",
    response_model=RoleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear rol",
)
def post_role(
    role_data: RoleCreate,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
):
    return create_role(db, role_data.model_dump())


@router.put(
    "/roles/{id_rol}",
    response_model=RoleResponse,
    summary="Actualizar rol",
)
def put_role(
    id_rol: int,
    role_data: RoleUpdate,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
):
    return update_role(db, id_rol, role_data.model_dump(exclude_unset=True))


@router.patch(
    "/roles/{id_rol}/status",
    response_model=RoleResponse,
    summary="Cambiar estado de rol",
)
def patch_role_status(
    id_rol: int,
    status_data: RoleStatusUpdate,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
):
    return set_role_status(db, id_rol, status_data.activo)


@router.get(
    "/permissions",
    response_model=list[PermissionResponse],
    summary="Listar permisos",
)
def get_permissions(
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
):
    return list_permissions(db)


@router.get(
    "/roles/{id_rol}/permissions",
    response_model=list[PermissionResponse],
    summary="Obtener permisos de un rol",
)
def get_permissions_for_role(
    id_rol: int,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
):
    return get_role_permissions(db, id_rol)


@router.put(
    "/roles/{id_rol}/permissions",
    response_model=list[PermissionResponse],
    summary="Reemplazar permisos de un rol",
)
def put_permissions_for_role(
    id_rol: int,
    payload: RolePermissionsUpdate,
    db: Session = Depends(get_db),
    _: Usuario = Depends(require_admin),
):
    return replace_role_permissions(db, id_rol, payload.id_permisos)
