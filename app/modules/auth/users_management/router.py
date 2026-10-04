from typing import List, Optional
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.modules.auth.dependencies import get_current_tenant_id, require_admin
from app.modules.auth.models import Usuario
from app.modules.auth.users_management.schemas import (
    AdminUserCreate,
    AdminUserResponse,
    AdminUserStatusUpdate,
    AdminUserUpdate,
)
from app.modules.auth.users_management.service import (
    create_admin_user,
    get_user_detail,
    list_users,
    set_user_status,
    update_admin_user,
)

router = APIRouter(prefix="/users", tags=["Usuarios (CU02)"])


@router.get(
    "",
    response_model=List[AdminUserResponse],
    summary="Listar usuarios",
    description="Devuelve la lista de usuarios del tenant.",
)
def get_users(
    db: Session = Depends(get_db),
    admin_user: Usuario = Depends(require_admin),
    tenant_id: Optional[int] = Depends(get_current_tenant_id),
):
    return list_users(db, tenant_id=tenant_id)


@router.get(
    "/{id_usuario}",
    response_model=AdminUserResponse,
    summary="Obtener usuario",
    description="Devuelve el detalle administrativo de un usuario por su identificador dentro del tenant.",
)
def get_user(
    id_usuario: int,
    db: Session = Depends(get_db),
    admin_user: Usuario = Depends(require_admin),
    tenant_id: Optional[int] = Depends(get_current_tenant_id),
):
    return get_user_detail(db, id_usuario, tenant_id=tenant_id)


@router.post(
    "",
    response_model=AdminUserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear usuario administrativo",
    description="Crea un usuario interno asignándole un rol existente en el tenant.",
)
def create_user(
    user_data: AdminUserCreate,
    db: Session = Depends(get_db),
    admin_user: Usuario = Depends(require_admin),
    tenant_id: Optional[int] = Depends(get_current_tenant_id),
):
    return create_admin_user(db, user_data, current_tenant_id=tenant_id)


@router.put(
    "/{id_usuario}",
    response_model=AdminUserResponse,
    summary="Actualizar usuario",
    description="Actualiza los datos administrativos de un usuario existente en el tenant.",
)
def update_user(
    id_usuario: int,
    user_data: AdminUserUpdate,
    db: Session = Depends(get_db),
    admin_user: Usuario = Depends(require_admin),
    tenant_id: Optional[int] = Depends(get_current_tenant_id),
):
    return update_admin_user(db, id_usuario, user_data, current_tenant_id=tenant_id)


@router.patch(
    "/{id_usuario}/status",
    response_model=AdminUserResponse,
    summary="Cambiar estado de usuario",
    description="Habilita o deshabilita un usuario sin eliminarlo físicamente.",
)
def update_user_status(
    id_usuario: int,
    status_data: AdminUserStatusUpdate,
    db: Session = Depends(get_db),
    admin_user: Usuario = Depends(require_admin),
    tenant_id: Optional[int] = Depends(get_current_tenant_id),
):
    return set_user_status(db, id_usuario, status_data.activo, current_tenant_id=tenant_id)
