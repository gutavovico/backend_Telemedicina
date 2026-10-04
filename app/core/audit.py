import json
from typing import Any, Dict, Optional, Union
from sqlalchemy.orm import Session

from app.modules.auth.models import Auditoria


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
    datos_ant_str = (
        json.dumps(datos_anteriores)
        if isinstance(datos_anteriores, dict)
        else datos_anteriores
    )
    datos_nuev_str = (
        json.dumps(datos_nuevos)
        if isinstance(datos_nuevos, dict)
        else datos_nuevos
    )

    auditoria = Auditoria(
        id_usuario=id_usuario,
        id_clinica=id_clinica,
        tabla_afectada=tabla_afectada,
        registro_id=registro_id,
        accion=accion,
        descripcion=descripcion,
        datos_anteriores=datos_ant_str,
        datos_nuevos=datos_nuev_str,
        direccion_ip=direccion_ip,
    )
    db.add(auditoria)
    db.flush()
    return auditoria
