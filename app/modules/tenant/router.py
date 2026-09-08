from typing import List, Optional
from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.orm import Session, joinedload
from app.core.database import get_db
from app.core.dependencies.tenant import is_super_admin
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.models import Clinica, Usuario
from app.modules.tenant.schemas import TenantContextResponse

router = APIRouter(prefix="/tenant", tags=["Tenant Context"])


@router.get("/context", response_model=TenantContextResponse)
def get_tenant_context(
    x_tenant_id: Optional[str] = Header(None, alias="X-Tenant-ID"),
    current_user: Usuario = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Returns the tenant (clinic) and identity context of the authenticated user.
    """
    super_admin = is_super_admin(current_user)
    
    clinica_id: Optional[int] = None
    clinica_nombre: str = ""
    clinica_estado: Optional[str] = None
    
    if super_admin:
        if x_tenant_id:
            try:
                target_id = int(x_tenant_id)
            except ValueError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Encabezado X-Tenant-ID inválido",
                )
            clinica = db.query(Clinica).filter(Clinica.id_clinica == target_id).first()
            if not clinica:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Clínica no encontrada",
                )
            if clinica.estado.upper() != "ACTIVO":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Clínica inactiva. Contacte al administrador.",
                )
            clinica_id = clinica.id_clinica
            clinica_nombre = clinica.nombre
            clinica_estado = clinica.estado
    else:
        if current_user.id_clinica is not None:
            clinica = db.query(Clinica).filter(Clinica.id_clinica == current_user.id_clinica).first()
            if not clinica:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Clínica no encontrada",
                )
            if clinica.estado.upper() != "ACTIVO":
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Clínica inactiva. Contacte al administrador.",
                )
            clinica_id = clinica.id_clinica
            clinica_nombre = clinica.nombre
            clinica_estado = clinica.estado

    # Extract permissions
    permisos: List[str] = []
    user_with_perms = (
        db.query(Usuario)
        .options(joinedload(Usuario.rol))
        .filter(Usuario.id_usuario == current_user.id_usuario)
        .first()
    )
    rol_nombre = ""
    if user_with_perms and user_with_perms.rol:
        rol_nombre = user_with_perms.rol.nombre
        for p in user_with_perms.rol.permisos:
            if p.estado and p.estado.upper() != "ACTIVO":
                continue
            if p.nombre and p.nombre not in permisos:
                permisos.append(p.nombre)
            if p.modulo and p.accion:
                code = f"{p.modulo}.{p.accion}"
                if code not in permisos:
                    permisos.append(code)

    return TenantContextResponse(
        clinica_id=clinica_id,
        clinica_nombre=clinica_nombre,
        clinica_estado=clinica_estado,
        usuario_id=current_user.id_usuario,
        usuario_nombres=current_user.nombres,
        usuario_apellidos=current_user.apellidos,
        usuario_correo=current_user.correo,
        rol=rol_nombre,
        permisos=permisos,
        es_super_admin=super_admin,
    )
