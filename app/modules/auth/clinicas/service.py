from typing import List, Optional, Tuple

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.modules.auth.models import Clinica, Rol, Usuario
from app.modules.auth.clinicas.schemas import ClinicaItemResponse, ClinicaRegistroRequest


def list_clinicas(
    db: Session,
    estado: Optional[str] = None,
    page: int = 1,
    per_page: int = 20,
) -> Tuple[int, List[ClinicaItemResponse]]:
    """Lista las clínicas de la plataforma con conteo de usuarios activos."""
    query = db.query(Clinica)
    if estado:
        query = query.filter(func.upper(Clinica.estado) == estado.upper())

    total = query.count()
    clinicas = (
        query.order_by(Clinica.id_clinica.asc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )

    items = []
    for c in clinicas:
        usuarios_activos = (
            db.query(func.count(Usuario.id_usuario))
            .filter(
                Usuario.id_clinica == c.id_clinica,
                func.upper(Usuario.estado) == "ACTIVO",
            )
            .scalar()
            or 0
        )
        admin = (
            db.query(Usuario)
            .join(Rol, Usuario.id_rol == Rol.id_rol)
            .filter(
                Usuario.id_clinica == c.id_clinica,
                func.upper(Rol.nombre) == "ADMINISTRADOR",
            )
            .order_by(Usuario.id_usuario.asc())
            .first()
        )
        # Fallback: primer admin (ADMIN/ADMINISTRACION y variantes) si no hay "ADMINISTRADOR".
        if not admin:
            admin = (
                db.query(Usuario)
                .join(Rol, Usuario.id_rol == Rol.id_rol)
                .filter(
                    Usuario.id_clinica == c.id_clinica,
                    func.upper(Rol.nombre).in_(
                        ["ADMIN", "ADMINISTRACION", "ADMINISTRACIÓN", "ADMINISTRADOR DEL SISTEMA"]
                    ),
                )
                .order_by(Usuario.id_usuario.asc())
                .first()
            )
        items.append(
            ClinicaItemResponse(
                clinica_id=c.id_clinica,
                nombre=c.nombre,
                razon_social=c.razon_social,
                nit=c.nit,
                estado=c.estado,
                usuarios_activos=usuarios_activos,
                admin_nombre=f"{admin.nombres} {admin.apellidos}".strip() if admin else None,
                admin_correo=admin.correo if admin else None,
                fecha_creacion=c.fecha_creacion,
            )
        )
    return total, items


def update_clinica_estado(
    db: Session,
    clinica_id: int,
    nuevo_estado: str,
) -> Clinica:
    """Actualiza el estado operativo de una clínica."""
    clinica = db.query(Clinica).filter(Clinica.id_clinica == clinica_id).first()
    if not clinica:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Clínica no encontrada",
        )
    clinica.estado = nuevo_estado.upper()
    db.commit()
    db.refresh(clinica)
    return clinica


def registrar_clinica(
    db: Session, data: ClinicaRegistroRequest
) -> Tuple[Clinica, Usuario]:
    """Onboarding público: registra clínica + rol y cuenta de admin inicial."""
    existing_user = db.query(Usuario).filter(Usuario.correo == data.admin_email).first()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El correo electrónico ya está registrado en la plataforma",
        )

    if data.nit:
        existing_nit = db.query(Clinica).filter(Clinica.nit == data.nit).first()
        if existing_nit:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El NIT ya está registrado",
            )

    try:
        nueva_clinica = Clinica(
            nombre=data.nombre,
            razon_social=data.razon_social,
            nit=data.nit,
            telefono=data.telefono,
            direccion=data.direccion,
            estado="ACTIVO",
        )
        db.add(nueva_clinica)
        db.flush()

        admin_rol = Rol(
            id_clinica=nueva_clinica.id_clinica,
            nombre="Administrador",
            descripcion="Administrador principal de la clínica",
            estado="ACTIVO",
        )
        db.add(admin_rol)
        db.flush()

        admin_usuario = Usuario(
            id_clinica=nueva_clinica.id_clinica,
            id_rol=admin_rol.id_rol,
            nombres=data.admin_nombres,
            apellidos=data.admin_apellidos,
            correo=data.admin_email,
            password_hash=hash_password(data.admin_password),
            estado="ACTIVO",
        )
        db.add(admin_usuario)
        db.commit()
        db.refresh(nueva_clinica)
        db.refresh(admin_usuario)

        return nueva_clinica, admin_usuario
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al registrar la clínica: {str(e)}",
        )
