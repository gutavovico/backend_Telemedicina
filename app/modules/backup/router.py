"""Endpoints de copias de seguridad (ver contracts/backup.md)."""

from fastapi import APIRouter, Depends, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.auth.models import Usuario
from app.modules.backup import scheduler, service
from app.modules.backup.dependencies import require_backup_admin
from app.modules.backup.schemas import (
    BackupConfigOut,
    BackupConfigUpdate,
    BackupListResponse,
    RestoreResponse,
)

router = APIRouter(prefix="/backup", tags=["Copias de Seguridad (Backup)"])


def _ip(request: Request) -> str | None:
    try:
        return request.client.host if request.client else None
    except Exception:  # noqa: BLE001
        return None


@router.post(
    "/generar",
    status_code=status.HTTP_200_OK,
    summary="Generar copia ahora y descargarla",
)
def generar(
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_backup_admin),
):
    destino = service.generar_backup(db, current_user, _ip(request))
    return FileResponse(
        path=str(destino),
        media_type="application/octet-stream",
        filename=destino.name,
        headers={"Access-Control-Expose-Headers": "Content-Disposition"},
    )


@router.get(
    "/listar",
    response_model=BackupListResponse,
    summary="Listar copias disponibles",
)
def listar(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_backup_admin),
):
    return BackupListResponse(data=service.listar_backups(db))


@router.get(
    "/descargar/{nombre}",
    summary="Descargar una copia específica",
)
def descargar(
    nombre: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_backup_admin),
):
    from app.core.audit import registrar_auditoria

    path = service.leer_backup(nombre)
    try:
        registrar_auditoria(
            db,
            id_usuario=current_user.id_usuario,
            id_clinica=current_user.id_clinica,
            tabla_afectada="backup",
            accion="CONSULTAR",
            descripcion=f"Descargó backup: {nombre}",
            direccion_ip=_ip(request),
        )
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
    return FileResponse(
        path=str(path),
        media_type="application/octet-stream",
        filename=path.name,
        headers={"Access-Control-Expose-Headers": "Content-Disposition"},
    )


@router.post(
    "/restaurar",
    response_model=RestoreResponse,
    summary="Restaurar la BD desde un .sql (solo Super)",
)
def restaurar(
    request: Request,
    archivo: UploadFile,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_backup_admin),
):
    mensaje = service.restaurar_backup(db, current_user, archivo, _ip(request))
    return RestoreResponse(mensaje=mensaje)


@router.get(
    "/config",
    response_model=BackupConfigOut,
    summary="Ver programación automática",
)
def ver_config(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_backup_admin),
):
    cfg = service.obtener_config(db)
    ultima, estado = service.ultimo_estado()
    return BackupConfigOut(
        hora=cfg.hora,
        dias_semana=list(cfg.dias_semana or []),
        activo=bool(cfg.activo),
        retencion_dias=int(cfg.retencion_dias or 7),
        ultima_ejecucion=ultima,
        ultimo_estado=estado,
    )


@router.put(
    "/config",
    response_model=BackupConfigOut,
    summary="Actualizar programación automática (solo Super)",
)
def editar_config(
    datos: BackupConfigUpdate,
    request: Request,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_backup_admin),
):
    cfg = service.actualizar_config(db, current_user, datos, _ip(request),
                                    reprogramar=scheduler.reprogramar)
    ultima, estado = service.ultimo_estado()
    return BackupConfigOut(
        hora=cfg.hora,
        dias_semana=list(cfg.dias_semana or []),
        activo=bool(cfg.activo),
        retencion_dias=int(cfg.retencion_dias or 7),
        ultima_ejecucion=ultima,
        ultimo_estado=estado,
    )


__all__ = ["router"]
