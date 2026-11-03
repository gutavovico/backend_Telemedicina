"""Lógica de copias manuales y programadas (cambio backup-copias-seguridad).

Referencia: estacion_servicio_backend/backup/{views,crons}.py adaptado a
FastAPI + carpeta local `backups/` + Neon (libpq con sslmode) + hora Bolivia.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional
from zoneinfo import ZoneInfo

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.audit import registrar_auditoria
from app.core.config import settings
from app.modules.auth.models import Usuario
from app.modules.backup.models import BackupConfig
from app.modules.backup.schemas import BackupConfigUpdate, BackupFile

LA_PAZ = ZoneInfo("America/La_Paz")
NOMBRE_RE = re.compile(r"^backup_\d{8}_\d{6}\.sql$")
# Rutas típicas de instalación (fallback si no están en el PATH).
_BIN_CANDIDATOS = [
    r"C:\Program Files\PostgreSQL\18\bin",
    r"C:\Program Files\PostgreSQL\17\bin",
    r"C:\Program Files\PostgreSQL\16\bin",
    "/usr/lib/postgresql/16/bin",
    "/usr/lib/postgresql/15/bin",
    "/usr/pgsql-16/bin",
]
# Errores de restore tolerados (idempotencia), igual que el Django de referencia.
_ERRORES_TOLERADOS = (
    "already exists",
    "duplicate key",
    "multiple primary keys",
    "event trigger",
    "ya existe",
    "llave duplicada",
    "no se permiten",
)
_ULTIMA_EJECUCION: Optional[str] = None
_ULTIMO_ESTADO: Optional[str] = None


def backup_dir() -> Path:
    """Carpeta propia de copias (NO storage_documents)."""
    base = Path(settings.BACKUP_DIR)
    if not base.is_absolute():
        base = Path(__file__).resolve().parents[3] / settings.BACKUP_DIR
    base.mkdir(parents=True, exist_ok=True)
    return base


def _which(exe: str) -> Optional[str]:
    """Busca el binario en el PATH y en rutas típicas de instalación."""
    encontrado = shutil.which(exe)
    if encontrado:
        return encontrado
    nombres = [exe] if os.name != "nt" else [exe, f"{exe}.exe"]
    for carpeta in _BIN_CANDIDATOS:
        for nombre in nombres:
            candidato = str(Path(carpeta) / nombre)
            if Path(candidato).is_file():
                return candidato
    return None


def _libpq_url() -> str:
    """DATABASE_URL sin el driver +psycopg2 (pg_dump/psql usan libpq)."""
    return settings.DATABASE_URL.replace("postgresql+psycopg2://", "postgresql://")


def _ahora_lp() -> datetime:
    return datetime.now(LA_PAZ)


def _auditar(
    db: Session,
    user: Optional[Usuario],
    accion: str,
    descripcion: str,
    ip: Optional[str] = None,
) -> None:
    """Eventos de backup con la clínica del ADMIN que ejecuta (Super denegado)."""
    if user is None:
        return
    if user.id_clinica is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="La cuenta autenticada no está asociada a una clínica.",
        )
    try:
        registrar_auditoria(
            db,
            id_usuario=user.id_usuario,
            id_clinica=user.id_clinica,
            tabla_afectada="backup",
            accion=accion,
            descripcion=descripcion,
            direccion_ip=ip,
        )
        db.commit()
    except Exception:
        db.rollback()


def _marcar_estado(ok: bool) -> None:
    global _ULTIMA_EJECUCION, _ULTIMO_ESTADO
    _ULTIMA_EJECUCION = _ahora_lp().isoformat()
    _ULTIMO_ESTADO = "OK" if ok else "ERROR"


def ultimo_estado() -> tuple[Optional[str], Optional[str]]:
    return _ULTIMA_EJECUCION, _ULTIMO_ESTADO


def generar_backup(db: Session, user: Usuario, ip: Optional[str] = None) -> Path:
    pg_dump = _which("pg_dump")
    if not pg_dump:
        _auditar(db, user, "CREAR", "Error al crear backup: pg_dump no instalado", ip)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="pg_dump no está instalado en el servidor",
        )
    nombre = f"backup_{_ahora_lp().strftime('%Y%m%d_%H%M%S')}.sql"
    destino = backup_dir() / nombre
    resultado = subprocess.run(
        [pg_dump, "--dbname", _libpq_url(), "-F", "p",
         "--schema=public", "--no-owner", "--no-privileges",
         "-f", str(destino)],
        capture_output=True, text=True, timeout=600,
    )
    if resultado.returncode != 0:
        _marcar_estado(False)
        _auditar(db, user, "CREAR", f"Error al crear backup: {resultado.stderr[:500]}", ip)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"pg_dump falló: {resultado.stderr[:500]}",
        )
    _marcar_estado(True)
    _auditar(db, user, "CREAR",
             f"Backup generado: {nombre} ({destino.stat().st_size} bytes)", ip)
    return destino


def listar_backups(db: Session | None = None) -> List[BackupFile]:
    """Lista .sql con fecha (mtime, hora La Paz) y origen manual/automática.

    Origen por auditoría CU21: si existe un CREAR en ``backup`` cuya
    descripción contiene el nombre del archivo → ``manual`` (hecha por un
    ADMIN); si no hay rastro manual → ``automatica`` (job programado con
    ``user=None``, que no audita). Si hay auditoría manual se usa su
    ``fecha_hora`` como "cuándo se hizo"; si no, el mtime del archivo.
    """
    manuales: set[str] = set()
    fechas_audit: dict[str, str] = {}
    if db is not None:
        try:
            from app.modules.auth.models import Auditoria

            filas = (
                db.query(Auditoria)
                .filter(
                    Auditoria.tabla_afectada == "backup",
                    Auditoria.accion == "CREAR",
                )
                .order_by(Auditoria.id_auditoria.desc())
                .limit(500)
                .all()
            )
            for fila in filas:
                desc = fila.descripcion or ""
                for path in backup_dir().glob("backup_*.sql"):
                    if path.name and path.name in desc:
                        manuales.add(path.name)
                        if path.name not in fechas_audit and fila.fecha_hora:
                            fh = fila.fecha_hora
                            if fh.tzinfo is None:
                                fh = fh.replace(tzinfo=LA_PAZ)
                            fechas_audit[path.name] = fh.isoformat()
        except Exception:
            manuales = set()
    archivos: List[BackupFile] = []
    for path in backup_dir().glob("backup_*.sql"):
        if not NOMBRE_RE.match(path.name):
            continue
        stat = path.stat()
        # Sin db no se puede consultar auditoría: se asume manual para no
        # ocultar nada. Con db, lo auditado como CREAR es manual y el resto
        # (job programado user=None, sin auditoría) es automático.
        origen = "manual" if (db is None or path.name in manuales) else "automatica"
        fecha = fechas_audit.get(
            path.name,
            datetime.fromtimestamp(stat.st_mtime, LA_PAZ).isoformat(),
        )
        archivos.append(BackupFile(
            nombre=path.name,
            tamanio=stat.st_size,
            fecha=fecha,
            origen=origen,
        ))
    archivos.sort(key=lambda f: f.nombre, reverse=True)
    return archivos


def leer_backup(nombre: str) -> Path:
    """Valida el nombre y evita path traversal fuera de backups/."""
    if not NOMBRE_RE.match(nombre or ""):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Backup no encontrado")
    path = (backup_dir() / nombre).resolve()
    if path.parent != backup_dir().resolve() or not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="Backup no encontrado")
    return path


def restaurar_backup(db: Session, user: Usuario, archivo: UploadFile,
                     ip: Optional[str] = None) -> str:
    if not archivo.filename or not archivo.filename.endswith(".sql"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="El archivo debe tener extensión .sql")
    psql = _which("psql")
    if not psql:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="psql no está instalado en el servidor")
    if not NOMBRE_RE.match(archivo.filename):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Nombre de archivo inválido")
    tmp_path = backup_dir() / f"restore_{archivo.filename}"
    contenido = archivo.file.read()
    if len(contenido) > 500 * 1024 * 1024:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Archivo demasiado grande (máx 500MB)")
    tmp_path.write_bytes(contenido)
    try:
        resultado = subprocess.run(
            [psql, "--dbname", _libpq_url(), "-f", str(tmp_path),
             "-v", "ON_ERROR_CONTINUE=on"],
            capture_output=True, text=True, timeout=1800,
        )
    finally:
        tmp_path.unlink(missing_ok=True)
    fatales = [
        line.strip() for line in resultado.stderr.splitlines()
        if "error" in line.lower()
        and not any(t in line.lower() for t in _ERRORES_TOLERADOS)
        and line.strip()
    ]
    if fatales:
        _auditar(db, user, "EDITAR", f"Error al restaurar: {fatales[0][:500]}", ip)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail=fatales[0][:500])
    _auditar(db, user, "EDITAR",
             f"Base de datos restaurada desde: {archivo.filename}", ip)
    return f"Base de datos restaurada correctamente desde {archivo.filename}"


def obtener_config(db: Session) -> BackupConfig:
    cfg = db.query(BackupConfig).filter(BackupConfig.id == 1).first()
    if not cfg:
        cfg = BackupConfig(id=1, hora="02:00",
                           dias_semana=["lun", "mar", "mie", "jue", "vie", "sab", "dom"],
                           activo=True, retencion_dias=7)
        db.add(cfg)
        db.commit()
        db.refresh(cfg)
    return cfg


def actualizar_config(db: Session, user: Usuario, datos: BackupConfigUpdate,
                      ip: Optional[str] = None,
                      reprogramar: Optional[Callable[[], None]] = None) -> BackupConfig:
    cfg = obtener_config(db)
    cfg.hora = datos.hora
    cfg.dias_semana = datos.dias_semana
    cfg.activo = datos.activo
    cfg.retencion_dias = datos.retencion_dias
    cfg.updated_by = user.id_usuario
    cfg.updated_at = datetime.now(LA_PAZ)
    db.commit()
    db.refresh(cfg)
    _auditar(db, user, "EDITAR",
             f"Programación de backups actualizada: {cfg.hora} {cfg.dias_semana} "
             f"activo={cfg.activo} retención={cfg.retencion_dias}d", ip)
    if reprogramar is not None:
        reprogramar()
    return cfg


def limpiar_antiguos(retencion_dias: int) -> int:
    """Borra copias con antigüedad mayor a la retención. Devuelve eliminados."""
    ahora = _ahora_lp().timestamp()
    eliminados = 0
    for path in backup_dir().glob("backup_*.sql"):
        if not NOMBRE_RE.match(path.name):
            continue
        if ahora - path.stat().st_mtime > retencion_dias * 86400:
            path.unlink(missing_ok=True)
            eliminados += 1
    return eliminados


__all__ = [
    "LA_PAZ",
    "backup_dir",
    "generar_backup",
    "listar_backups",
    "leer_backup",
    "restaurar_backup",
    "obtener_config",
    "actualizar_config",
    "limpiar_antiguos",
    "ultimo_estado",
]
