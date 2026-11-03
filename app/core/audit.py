import json
from typing import Any, Dict, Optional, Union
from sqlalchemy.orm import Session

from app.modules.auth.models import Auditoria


def _to_jsonb(value: Optional[Union[Dict[str, Any], str]]) -> Optional[Any]:
    """Normaliza a valor JSONB: dict/list nativo, str JSON parseado, resto tal cual."""
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed
        except Exception:
            return value
    return value


def registrar_auditoria(
    db: Session,
    *,
    id_usuario: int,
    id_clinica: int,
    tabla_afectada: str,
    registro_id: Optional[int] = None,
    accion: str,
    descripcion: Optional[str] = None,
    datos_anteriores: Optional[Union[Dict[str, Any], str]] = None,
    datos_nuevos: Optional[Union[Dict[str, Any], str]] = None,
    direccion_ip: Optional[str] = None,
) -> Auditoria:
    """
    Registra una traza en la tabla auditoria dentro de la transaccion activa.
    No hace commit ni rollback: queda a cargo del servicio que invoca al helper.
    """
    auditoria = Auditoria(
        id_usuario=id_usuario,
        id_clinica=id_clinica,
        tabla_afectada=tabla_afectada,
        registro_id=registro_id,
        accion=accion,
        descripcion=descripcion,
        datos_anteriores=_to_jsonb(datos_anteriores),
        datos_nuevos=_to_jsonb(datos_nuevos),
        direccion_ip=direccion_ip,
    )
    db.add(auditoria)
    db.flush()
    return auditoria
