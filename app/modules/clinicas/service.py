from typing import Optional, Tuple, List
from fastapi import HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session
from app.modules.auth.models import Clinica, Usuario
from app.modules.clinicas.schemas import ClinicaItemResponse


def list_clinicas(
    db: Session,
    estado: Optional[str] = None,
    page: int = 1,
    per_page: int = 20,
) -> Tuple[int, List[ClinicaItemResponse]]:
    """List all clinics in the platform with active user counts and pagination."""
    query = db.query(Clinica)
    if estado:
        query = query.filter(func.upper(Clinica.estado) == estado.upper())
    
    total = query.count()
    clinicas = query.order_by(Clinica.id_clinica.asc()).offset((page - 1) * per_page).limit(per_page).all()
    
    items = []
    for c in clinicas:
        usuarios_activos = (
            db.query(func.count(Usuario.id_usuario))
            .filter(
                Usuario.id_clinica == c.id_clinica,
                func.upper(Usuario.estado) == "ACTIVO"
            )
            .scalar()
            or 0
        )
        items.append(
            ClinicaItemResponse(
                clinica_id=c.id_clinica,
                nombre=c.nombre,
                razon_social=c.razon_social,
                nit=c.nit,
                estado=c.estado,
                usuarios_activos=usuarios_activos,
                fecha_creacion=c.fecha_creacion,
            )
        )
    return total, items


def update_clinica_estado(
    db: Session,
    clinica_id: int,
    nuevo_estado: str,
) -> Clinica:
    """Updates the operational status of a clinic."""
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
