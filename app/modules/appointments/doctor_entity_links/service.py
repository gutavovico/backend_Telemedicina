"""Servicio CU29: vinculación de médicos con entidades.

Todo el módulo usa `AsyncSession` y SQLAlchemy 2.0 (`select`, `execute`,
`scalars`). Las mutaciones, su historial y la auditoría se confirman en una
única transacción; cualquier fallo revierte el conjunto completo.
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException, status
from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from app.core.audit import registrar_auditoria_async
from app.core.security import generate_temporary_password, hash_password
from app.modules.appointments.doctor_entity_links.models import (
    CredencialTemporalMedico,
    HistorialVinculacionMedico,
    VinculacionMedicoEntidad,
    VinculacionMedicoEspecialidad,
    VinculacionMedicoRol,
    VinculacionMedicoSede,
)
from app.modules.appointments.doctor_entity_links.schemas import (
    AsignacionesInput,
    AsignacionesVinculacion,
    VinculacionCreate,
    VinculacionEstadoUpdate,
    VinculacionRechazo,
)
from app.modules.appointments.models import Especialidad, Medico
from app.modules.auth.models import Clinica, Permiso, Rol, RolPermiso, Usuario
from app.modules.tenants.models import Sede

TABLA_VINCULACION = "vinculaciones_medico_entidad"
HORAS_VIGENCIA_CREDENCIAL = 72
ESTADOS_TERMINALES = ("RECHAZADO", "BAJA")


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _normalizar_correo(valor: str) -> str:
    return (valor or "").strip().lower()


def _normalizar_documento(valor: str) -> str:
    return " ".join((valor or "").split()).upper()


def _normalizar_matricula(valor: str) -> str:
    return (valor or "").strip().upper()


def _enmascarar_documento(valor: Optional[str]) -> Optional[str]:
    if not valor:
        return None
    limpio = str(valor).strip()
    if len(limpio) <= 4:
        return "****"
    return f"****{limpio[-4:]}"


def _nombre_rol(usuario: Usuario) -> str:
    rol = getattr(usuario, "rol_rel", None)
    if rol is not None and getattr(rol, "nombre", None):
        return str(rol.nombre).strip().upper()
    valor = getattr(usuario, "rol", None)
    if isinstance(valor, str):
        return valor.strip().upper()
    return ""


def _serializar_roles(filas: List[Tuple[Rol, bool]]) -> List[Dict[str, Any]]:
    return [
        {"id_rol": rol.id_rol, "nombre": rol.nombre, "es_principal": bool(principal)}
        for rol, principal in filas
    ]


def _serializar_especialidades(
    filas: List[Tuple[Especialidad, bool]]
) -> List[Dict[str, Any]]:
    return [
        {
            "id_especialidad": especialidad.id_especialidad,
            "nombre": especialidad.nombre,
            "es_principal": bool(principal),
        }
        for especialidad, principal in filas
    ]


async def _roles_asignados(
    db: AsyncSession, id_vinculacion: int
) -> List[Tuple[Rol, bool]]:
    filas = await db.execute(
        select(Rol, VinculacionMedicoRol.es_principal)
        .join(VinculacionMedicoRol, VinculacionMedicoRol.id_rol == Rol.id_rol)
        .where(VinculacionMedicoRol.id_vinculacion == id_vinculacion)
        .order_by(Rol.nombre)
    )
    return list(filas.all())


async def _especialidades_asignadas(
    db: AsyncSession, id_vinculacion: int
) -> List[Tuple[Especialidad, bool]]:
    filas = await db.execute(
        select(Especialidad, VinculacionMedicoEspecialidad.es_principal)
        .join(
            VinculacionMedicoEspecialidad,
            VinculacionMedicoEspecialidad.id_especialidad == Especialidad.id_especialidad,
        )
        .where(VinculacionMedicoEspecialidad.id_vinculacion == id_vinculacion)
        .order_by(Especialidad.nombre)
    )
    return list(filas.all())


async def _sedes_asignadas(db: AsyncSession, id_vinculacion: int) -> List[int]:
    filas = await db.scalars(
        select(VinculacionMedicoSede.id_sede)
        .where(VinculacionMedicoSede.id_vinculacion == id_vinculacion)
        .order_by(VinculacionMedicoSede.id_sede)
    )
    return [int(id_sede) for id_sede in filas.all()]


async def _sedes_por_vinculacion(
    db: AsyncSession, ids: List[int]
) -> Dict[int, List[int]]:
    resultado: Dict[int, List[int]] = {id_vinculacion: [] for id_vinculacion in ids}
    if not ids:
        return resultado
    filas = await db.execute(
        select(VinculacionMedicoSede.id_vinculacion, VinculacionMedicoSede.id_sede)
        .where(VinculacionMedicoSede.id_vinculacion.in_(ids))
        .order_by(VinculacionMedicoSede.id_sede)
    )
    for id_vinculacion, id_sede in filas.all():
        resultado[id_vinculacion].append(int(id_sede))
    return resultado


async def _cargar_usuarios(
    db: AsyncSession, ids: List[int]
) -> Dict[int, Usuario]:
    if not ids:
        return {}
    usuarios = await db.scalars(
        select(Usuario)
        .where(Usuario.id_usuario.in_(set(ids)))
        .options(undefer(Usuario.documento_identidad))
    )
    return {usuario.id_usuario: usuario for usuario in usuarios.all()}


async def _cargar_medicos(db: AsyncSession, ids_usuarios: List[int]) -> Dict[int, Medico]:
    if not ids_usuarios:
        return {}
    medicos = await db.scalars(
        select(Medico).where(Medico.id_usuario.in_(set(ids_usuarios)))
    )
    return {medico.id_usuario: medico for medico in medicos.all()}


async def _asignaciones_por_vinculacion(
    db: AsyncSession, ids: List[int]
) -> Dict[int, Tuple[List[Tuple[Rol, bool]], List[Tuple[Especialidad, bool]]]]:
    resultado: Dict[int, Tuple[List[Tuple[Rol, bool]], List[Tuple[Especialidad, bool]]]] = {
        id_vinculacion: ([], []) for id_vinculacion in ids
    }
    if not ids:
        return resultado

    filas_roles = await db.execute(
        select(VinculacionMedicoRol.id_vinculacion, Rol, VinculacionMedicoRol.es_principal)
        .join(Rol, Rol.id_rol == VinculacionMedicoRol.id_rol)
        .where(VinculacionMedicoRol.id_vinculacion.in_(ids))
        .order_by(Rol.nombre)
    )
    for id_vinculacion, rol, principal in filas_roles.all():
        resultado[id_vinculacion][0].append((rol, principal))

    filas_especialidades = await db.execute(
        select(
            VinculacionMedicoEspecialidad.id_vinculacion,
            Especialidad,
            VinculacionMedicoEspecialidad.es_principal,
        )
        .join(
            Especialidad,
            Especialidad.id_especialidad
            == VinculacionMedicoEspecialidad.id_especialidad,
        )
        .where(VinculacionMedicoEspecialidad.id_vinculacion.in_(ids))
        .order_by(Especialidad.nombre)
    )
    for id_vinculacion, especialidad, principal in filas_especialidades.all():
        resultado[id_vinculacion][1].append((especialidad, principal))
    return resultado


def _respuesta_vinculacion(
    link: VinculacionMedicoEntidad,
    usuario: Optional[Usuario],
    medico: Optional[Medico],
    roles: List[Tuple[Rol, bool]],
    especialidades: List[Tuple[Especialidad, bool]],
    sedes: Optional[List[int]] = None,
) -> Dict[str, Any]:
    return {
        "id_vinculacion": link.id_vinculacion,
        "id_usuario": link.id_usuario,
        "id_medico": link.id_medico,
        "estado": link.estado,
        "nombres": usuario.nombres if usuario else "",
        "apellidos": usuario.apellidos if usuario else "",
        "correo": usuario.correo if usuario else "",
        "telefono": usuario.telefono if usuario else None,
        "documento_identidad": _enmascarar_documento(
            getattr(usuario, "documento_identidad", None) if usuario else None
        ),
        "matricula_profesional": medico.matricula_profesional if medico else None,
        "existe_perfil": medico is not None,
        "roles": _serializar_roles(roles),
        "especialidades": _serializar_especialidades(especialidades),
        "sedes": list(sedes or []),
        "fecha_invitacion": link.fecha_invitacion,
        "respondido_en": link.respondido_en,
        "fecha_estado": link.fecha_estado,
        "motivo_estado": link.motivo_estado,
        "row_version": link.row_version,
    }


async def buscar_candidato(
    db: AsyncSession, criterio: str, valor: str
) -> Dict[str, Any]:
    """Búsqueda global exacta y minimizada (excepción administrativa)."""
    criterio = (criterio or "").strip().lower()
    if criterio not in ("correo", "documento_identidad", "matricula_profesional"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Criterio de búsqueda inválido",
        )
    if not valor or len(valor.strip()) < 3:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El valor de búsqueda requiere al menos 3 caracteres",
        )

    consulta = (
        select(
            Usuario.id_usuario,
            Usuario.nombres,
            Usuario.apellidos,
            Usuario.correo,
            Usuario.documento_identidad,
            Medico.id_medico,
            Medico.matricula_profesional,
        )
        .outerjoin(Medico, Medico.id_usuario == Usuario.id_usuario)
    )
    if criterio == "correo":
        consulta = consulta.where(Usuario.correo == _normalizar_correo(valor))
    elif criterio == "documento_identidad":
        consulta = consulta.where(
            func.upper(Usuario.documento_identidad) == _normalizar_documento(valor)
        )
    else:
        consulta = consulta.where(
            func.upper(Medico.matricula_profesional) == _normalizar_matricula(valor)
        )

    fila = (await db.execute(consulta.limit(1))).first()
    if fila is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Candidato no encontrado",
        )
    return {
        "id_usuario": fila.id_usuario,
        "nombres": fila.nombres,
        "apellidos": fila.apellidos,
        "correo": fila.correo,
        "documento_identidad": _enmascarar_documento(fila.documento_identidad),
        "matricula_profesional": fila.matricula_profesional,
        "existe_perfil": fila.id_medico is not None,
    }


async def _validar_asignaciones(
    db: AsyncSession, id_clinica: int, datos: AsignacionesInput
) -> Tuple[List[Rol], List[Especialidad], int, List[Sede]]:
    if datos.id_rol_principal not in datos.roles:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El rol principal debe pertenecer a la lista de roles",
        )

    roles = list(
        (
            await db.scalars(select(Rol).where(Rol.id_rol.in_(datos.roles)))
        ).all()
    )
    if len(roles) != len(set(datos.roles)):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Uno o más roles no existen",
        )
    for rol in roles:
        if (rol.estado or "").upper() != "ACTIVO":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"El rol '{rol.nombre}' está inactivo",
            )
        if rol.id_clinica is not None and int(rol.id_clinica) != int(id_clinica):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"El rol '{rol.nombre}' pertenece a otra entidad",
            )

    ids_especialidades = [item.id_especialidad for item in datos.especialidades]
    especialidades: List[Especialidad] = []
    if ids_especialidades:
        especialidades = list(
            (
                await db.scalars(
                    select(Especialidad).where(
                        Especialidad.id_especialidad.in_(ids_especialidades)
                    )
                )
            ).all()
        )
        if len(especialidades) != len(set(ids_especialidades)):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Una o más especialidades no existen",
            )
        for especialidad in especialidades:
            if (especialidad.estado or "").lower() != "activo":
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"La especialidad '{especialidad.nombre}' está inactiva",
                )
        if sum(1 for item in datos.especialidades if item.es_principal) > 1:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Solo una especialidad puede ser principal",
            )

    sedes: List[Sede] = []
    if datos.sedes:
        if len(set(datos.sedes)) != len(datos.sedes):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="La lista de sedes contiene identificadores duplicados",
            )
        sedes = list(
            (await db.scalars(select(Sede).where(Sede.id.in_(datos.sedes)))).all()
        )
        if len(sedes) != len(set(datos.sedes)):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Una o más sedes no existen",
            )
        for sede in sedes:
            if int(sede.id_clinica) != int(id_clinica):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"La sede '{sede.nombre}' pertenece a otra entidad",
                )
            if not bool(sede.activa):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"La sede '{sede.nombre}' está inactiva",
                )

    return roles, especialidades, datos.id_rol_principal, sedes


async def _crear_asignaciones(
    db: AsyncSession,
    id_vinculacion: int,
    roles: List[Rol],
    especialidades: List[Especialidad],
    id_rol_principal: int,
    datos: AsignacionesInput,
    sedes: Optional[List[Sede]] = None,
) -> None:
    for rol in roles:
        db.add(
            VinculacionMedicoRol(
                id_vinculacion=id_vinculacion,
                id_rol=rol.id_rol,
                es_principal=rol.id_rol == id_rol_principal,
            )
        )
    principales = {
        item.id_especialidad: item.es_principal for item in datos.especialidades
    }
    for especialidad in especialidades:
        db.add(
            VinculacionMedicoEspecialidad(
                id_vinculacion=id_vinculacion,
                id_especialidad=especialidad.id_especialidad,
                es_principal=bool(principales.get(especialidad.id_especialidad, False)),
            )
        )
    for sede in sedes or []:
        db.add(
            VinculacionMedicoSede(
                id_vinculacion=id_vinculacion,
                id_sede=sede.id,
            )
        )
    await db.flush()


def _snapshot_asignaciones(
    roles: List[Tuple[Rol, bool]],
    especialidades: List[Tuple[Especialidad, bool]],
    sedes: Optional[List[int]] = None,
) -> Dict[str, Any]:
    return {
        "roles": _serializar_roles(roles),
        "especialidades": _serializar_especialidades(especialidades),
        "sedes": list(sedes or []),
    }


async def _registrar_historial(
    db: AsyncSession,
    *,
    id_vinculacion: int,
    tipo_evento: str,
    actor: Usuario,
    estado_anterior: Optional[str] = None,
    estado_nuevo: Optional[str] = None,
    motivo: Optional[str] = None,
    datos: Optional[Dict[str, Any]] = None,
) -> None:
    db.add(
        HistorialVinculacionMedico(
            id_vinculacion=id_vinculacion,
            tipo_evento=tipo_evento,
            estado_anterior=estado_anterior,
            estado_nuevo=estado_nuevo,
            id_usuario_actor=actor.id_usuario,
            motivo=motivo,
            datos=datos or {},
        )
    )
    await db.flush()


async def _auditar(
    db: AsyncSession,
    *,
    actor: Usuario,
    id_clinica: int,
    accion: str,
    id_vinculacion: int,
    descripcion: str,
    anteriores: Optional[Dict[str, Any]] = None,
    nuevos: Optional[Dict[str, Any]] = None,
    direccion_ip: Optional[str] = None,
) -> None:
    await registrar_auditoria_async(
        db,
        id_usuario=actor.id_usuario,
        id_clinica=id_clinica,
        tabla_afectada=TABLA_VINCULACION,
        registro_id=id_vinculacion,
        accion=accion,
        descripcion=descripcion,
        datos_anteriores=anteriores,
        datos_nuevos=nuevos,
        direccion_ip=direccion_ip,
    )


async def crear_vinculacion(
    db: AsyncSession,
    actor: Usuario,
    datos: VinculacionCreate,
    direccion_ip: Optional[str] = None,
) -> Dict[str, Any]:
    id_clinica = int(actor.id_clinica)
    roles, especialidades, id_rol_principal, sedes = await _validar_asignaciones(
        db, id_clinica, datos.asignaciones
    )

    credencial_plana: Optional[str] = None
    expira_credencial: Optional[datetime] = None
    usuario: Optional[Usuario] = None
    medico: Optional[Medico] = None

    try:
        if datos.modo == "EXISTENTE":
            if datos.id_usuario is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="id_usuario es obligatorio en modo EXISTENTE",
                )
            usuario = await db.scalar(
                select(Usuario)
                .where(Usuario.id_usuario == datos.id_usuario)
                .options(undefer(Usuario.documento_identidad))
            )
            if usuario is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="La cuenta indicada no existe o no es elegible",
                )
            if (usuario.estado or "").lower() != "activo":
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="La cuenta indicada está inactiva o suspendida",
                )

            medico = await db.scalar(
                select(Medico).where(Medico.id_usuario == usuario.id_usuario)
            )
            vínculo_previo = await db.scalar(
                select(VinculacionMedicoEntidad.id_vinculacion).where(
                    VinculacionMedicoEntidad.id_usuario == usuario.id_usuario
                )
            )
            elegible = (
                medico is not None
                or vínculo_previo is not None
                or _nombre_rol(usuario) == "MEDICO"
            )
            if not elegible:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="La cuenta no tiene perfil, rol ni vínculo médico",
                )
        else:
            nuevo = datos.usuario
            if nuevo is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="usuario es obligatorio en modo NUEVO",
                )
            correo = _normalizar_correo(nuevo.correo)
            documento = (
                _normalizar_documento(nuevo.documento_identidad)
                if nuevo.documento_identidad
                else None
            )
            existente = await db.scalar(
                select(Usuario.id_usuario).where(func.lower(Usuario.correo) == correo)
            )
            if existente is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Ya existe una cuenta con ese correo electrónico",
                )
            if documento:
                existente_doc = await db.scalar(
                    select(Usuario.id_usuario).where(
                        func.upper(Usuario.documento_identidad) == documento
                    )
                )
                if existente_doc is not None:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Ya existe una cuenta con ese documento de identidad",
                    )

            credencial_plana = generate_temporary_password()
            expira_credencial = _ahora() + timedelta(hours=HORAS_VIGENCIA_CREDENCIAL)
            usuario = Usuario(
                id_clinica=None,
                id_rol=None,
                nombres=nuevo.nombres.strip(),
                apellidos=nuevo.apellidos.strip(),
                correo=correo,
                documento_identidad=documento,
                telefono=(nuevo.telefono or "").strip() or None,
                password_hash=hash_password(credencial_plana),
                estado="ACTIVO",
            )
            db.add(usuario)
            await db.flush()

        duplicado = await db.scalar(
            select(VinculacionMedicoEntidad.id_vinculacion).where(
                VinculacionMedicoEntidad.id_clinica == id_clinica,
                VinculacionMedicoEntidad.id_usuario == usuario.id_usuario,
            )
        )
        if duplicado is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Ya existe una vinculación para este médico en la entidad actual",
            )

        link = VinculacionMedicoEntidad(
            id_clinica=id_clinica,
            id_usuario=usuario.id_usuario,
            id_medico=medico.id_medico if medico is not None else None,
            estado="INVITADO",
            invitado_por=actor.id_usuario,
            usuario_estado=actor.id_usuario,
        )
        db.add(link)
        await db.flush()

        await _crear_asignaciones(
            db,
            link.id_vinculacion,
            roles,
            especialidades,
            id_rol_principal,
            datos.asignaciones,
            sedes,
        )

        if credencial_plana is not None:
            db.add(
                CredencialTemporalMedico(
                    id_usuario=usuario.id_usuario,
                    id_vinculacion=link.id_vinculacion,
                    expira_en=expira_credencial,
                )
            )
            await db.flush()

        snapshot = {
            "roles": _serializar_roles([(rol, rol.id_rol == id_rol_principal) for rol in roles]),
            "especialidades": [
                {
                    "id_especialidad": especialidad.id_especialidad,
                    "nombre": especialidad.nombre,
                    "es_principal": bool(
                        next(
                            (
                                item.es_principal
                                for item in datos.asignaciones.especialidades
                                if item.id_especialidad == especialidad.id_especialidad
                            ),
                            False,
                        )
                    ),
                }
                for especialidad in especialidades
            ],
            "sedes": [int(sede.id) for sede in sedes],
        }
        await _registrar_historial(
            db,
            id_vinculacion=link.id_vinculacion,
            tipo_evento="CREACION",
            actor=actor,
            estado_anterior=None,
            estado_nuevo="INVITADO",
            datos=snapshot,
        )
        await _auditar(
            db,
            actor=actor,
            id_clinica=id_clinica,
            accion="CREAR_VINCULACION_MEDICO",
            id_vinculacion=link.id_vinculacion,
            descripcion="Invitación de médico a la entidad",
            nuevos=snapshot,
            direccion_ip=direccion_ip,
        )

        await db.commit()

        respuesta = {
            "vinculacion": {
                "id_vinculacion": link.id_vinculacion,
                "id_usuario": link.id_usuario,
                "id_medico": link.id_medico,
                "estado": link.estado,
            },
            "perfil_pendiente": link.id_medico is None,
            "credencial_temporal": None,
        }
        if credencial_plana is not None:
            respuesta["credencial_temporal"] = {
                "correo": usuario.correo,
                "password_temporal": credencial_plana,
                "expira_en": expira_credencial,
            }
        return respuesta
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="La cuenta o la vinculación ya existen",
        )
    except HTTPException:
        await db.rollback()
        raise
    except Exception:
        await db.rollback()
        raise


async def listar_vinculaciones(
    db: AsyncSession,
    id_clinica: int,
    page: int,
    per_page: int,
    estado: Optional[str] = None,
    q: Optional[str] = None,
) -> Dict[str, Any]:
    base = (
        select(VinculacionMedicoEntidad.id_vinculacion)
        .join(Usuario, Usuario.id_usuario == VinculacionMedicoEntidad.id_usuario)
        .where(VinculacionMedicoEntidad.id_clinica == id_clinica)
    )
    if estado:
        base = base.where(VinculacionMedicoEntidad.estado == estado)
    if q:
        patron = f"%{q.strip()}%"
        base = base.where(
            or_(
                Usuario.nombres.ilike(patron),
                Usuario.apellidos.ilike(patron),
                Usuario.correo.ilike(patron),
            )
        )

    total = (
        await db.scalar(select(func.count()).select_from(base.subquery()))
    ) or 0
    ids = list(
        (
            await db.scalars(
                base.order_by(VinculacionMedicoEntidad.id_vinculacion)
                .offset((page - 1) * per_page)
                .limit(per_page)
            )
        ).all()
    )
    if not ids:
        return {"total": total, "page": page, "per_page": per_page, "items": []}

    links = list(
        (
            await db.scalars(
                select(VinculacionMedicoEntidad)
                .where(VinculacionMedicoEntidad.id_vinculacion.in_(ids))
                .order_by(VinculacionMedicoEntidad.id_vinculacion)
            )
        ).all()
    )
    usuarios = await _cargar_usuarios(db, [link.id_usuario for link in links])
    medicos = await _cargar_medicos(db, [link.id_usuario for link in links])
    asignaciones = await _asignaciones_por_vinculacion(db, ids)
    sedes_asignadas = await _sedes_por_vinculacion(db, ids)

    items = []
    for link in links:
        roles, especialidades = asignaciones.get(link.id_vinculacion, ([], []))
        items.append(
            _respuesta_vinculacion(
                link,
                usuarios.get(link.id_usuario),
                medicos.get(link.id_usuario),
                roles,
                especialidades,
                sedes_asignadas.get(link.id_vinculacion, []),
            )
        )
    return {"total": total, "page": page, "per_page": per_page, "items": items}


async def _obtener_link(
    db: AsyncSession, id_clinica: int, id_vinculacion: int, bloquear: bool = False
) -> VinculacionMedicoEntidad:
    consulta = select(VinculacionMedicoEntidad).where(
        VinculacionMedicoEntidad.id_vinculacion == id_vinculacion,
        VinculacionMedicoEntidad.id_clinica == id_clinica,
    )
    if bloquear:
        consulta = consulta.with_for_update()
    link = await db.scalar(consulta)
    if link is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Vinculación no encontrada",
        )
    return link


async def obtener_detalle(
    db: AsyncSession, id_clinica: int, id_vinculacion: int
) -> Dict[str, Any]:
    link = await _obtener_link(db, id_clinica, id_vinculacion)
    usuarios = await _cargar_usuarios(db, [link.id_usuario])
    medicos = await _cargar_medicos(db, [link.id_usuario])
    roles = await _roles_asignados(db, link.id_vinculacion)
    especialidades = await _especialidades_asignadas(db, link.id_vinculacion)
    sedes = await _sedes_asignadas(db, link.id_vinculacion)

    filas_historial = await db.execute(
        select(HistorialVinculacionMedico, Usuario)
        .join(Usuario, Usuario.id_usuario == HistorialVinculacionMedico.id_usuario_actor)
        .where(HistorialVinculacionMedico.id_vinculacion == link.id_vinculacion)
        .order_by(HistorialVinculacionMedico.fecha_cambio, HistorialVinculacionMedico.id_historial)
    )
    historial = []
    for evento, actor in filas_historial.all():
        historial.append(
            {
                "id_historial": evento.id_historial,
                "tipo_evento": evento.tipo_evento,
                "estado_anterior": evento.estado_anterior,
                "estado_nuevo": evento.estado_nuevo,
                "id_usuario_actor": evento.id_usuario_actor,
                "nombre_actor": f"{actor.nombres} {actor.apellidos}".strip(),
                "motivo": evento.motivo,
                "datos": evento.datos or {},
                "fecha_cambio": evento.fecha_cambio,
            }
        )

    return {
        "vinculacion": _respuesta_vinculacion(
            link,
            usuarios.get(link.id_usuario),
            medicos.get(link.id_usuario),
            roles,
            especialidades,
            sedes,
        ),
        "historial": historial,
    }


async def reemplazar_asignaciones(
    db: AsyncSession,
    actor: Usuario,
    id_vinculacion: int,
    datos: AsignacionesVinculacion,
    direccion_ip: Optional[str] = None,
) -> Dict[str, Any]:
    id_clinica = int(actor.id_clinica)
    roles, especialidades, id_rol_principal, sedes = await _validar_asignaciones(
        db, id_clinica, datos
    )
    try:
        link = await _obtener_link(db, id_clinica, id_vinculacion, bloquear=True)
        if link.estado in ESTADOS_TERMINALES:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="No se pueden modificar asignaciones de un vínculo terminal",
            )
        if int(link.row_version) != int(datos.row_version):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="La versión del vínculo está desactualizada",
            )

        roles_antes = await _roles_asignados(db, link.id_vinculacion)
        especialidades_antes = await _especialidades_asignadas(db, link.id_vinculacion)
        sedes_antes = await _sedes_asignadas(db, link.id_vinculacion)
        antes = _snapshot_asignaciones(roles_antes, especialidades_antes, sedes_antes)

        await db.execute(
            delete(VinculacionMedicoRol).where(
                VinculacionMedicoRol.id_vinculacion == link.id_vinculacion
            )
        )
        await db.execute(
            delete(VinculacionMedicoEspecialidad).where(
                VinculacionMedicoEspecialidad.id_vinculacion == link.id_vinculacion
            )
        )
        await db.execute(
            delete(VinculacionMedicoSede).where(
                VinculacionMedicoSede.id_vinculacion == link.id_vinculacion
            )
        )
        await _crear_asignaciones(
            db,
            link.id_vinculacion,
            roles,
            especialidades,
            id_rol_principal,
            datos,
            sedes,
        )
        link.row_version = int(link.row_version) + 1

        roles_despues = await _roles_asignados(db, link.id_vinculacion)
        especialidades_despues = await _especialidades_asignadas(db, link.id_vinculacion)
        sedes_despues = await _sedes_asignadas(db, link.id_vinculacion)
        despues = _snapshot_asignaciones(
            roles_despues, especialidades_despues, sedes_despues
        )

        await _registrar_historial(
            db,
            id_vinculacion=link.id_vinculacion,
            tipo_evento="ASIGNACIONES",
            actor=actor,
            motivo=None,
            datos={"antes": antes, "despues": despues},
        )
        await _auditar(
            db,
            actor=actor,
            id_clinica=id_clinica,
            accion="ACTUALIZAR_ASIGNACIONES_VINCULO",
            id_vinculacion=link.id_vinculacion,
            descripcion="Reemplazo atómico de roles, especialidades y sedes del vínculo",
            anteriores=antes,
            nuevos=despues,
            direccion_ip=direccion_ip,
        )
        await db.commit()

        usuarios = await _cargar_usuarios(db, [link.id_usuario])
        medicos = await _cargar_medicos(db, [link.id_usuario])
        return _respuesta_vinculacion(
            link,
            usuarios.get(link.id_usuario),
            medicos.get(link.id_usuario),
            roles_despues,
            especialidades_despues,
            sedes_despues,
        )
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Conflicto al reemplazar las asignaciones",
        )
    except HTTPException:
        await db.rollback()
        raise
    except Exception:
        await db.rollback()
        raise


async def cambiar_estado(
    db: AsyncSession,
    actor: Usuario,
    id_vinculacion: int,
    datos: VinculacionEstadoUpdate,
    direccion_ip: Optional[str] = None,
) -> Dict[str, Any]:
    id_clinica = int(actor.id_clinica)
    try:
        link = await _obtener_link(db, id_clinica, id_vinculacion, bloquear=True)
        if int(link.row_version) != int(datos.row_version):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="La versión del vínculo está desactualizada",
            )

        actual = link.estado
        destino = datos.estado
        transiciones = {
            "ACTIVO": {"SUSPENDIDO"},
            "SUSPENDIDO": {"ACTIVO", "BAJA"},
        }
        permitido = (
            destino in transiciones.get(actual, set())
            if destino != "BAJA"
            else actual in ("ACTIVO", "SUSPENDIDO")
        )
        if not permitido:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Transición inválida de {actual} a {destino}",
            )

        anterior = {
            "estado": actual,
            "row_version": link.row_version,
            "motivo_estado": link.motivo_estado,
        }
        link.estado = destino
        link.fecha_estado = _ahora()
        link.usuario_estado = actor.id_usuario
        link.motivo_estado = datos.motivo
        link.row_version = int(link.row_version) + 1

        await _registrar_historial(
            db,
            id_vinculacion=link.id_vinculacion,
            tipo_evento="CAMBIO_ESTADO",
            actor=actor,
            estado_anterior=actual,
            estado_nuevo=destino,
            motivo=datos.motivo,
            datos={},
        )
        await _auditar(
            db,
            actor=actor,
            id_clinica=id_clinica,
            accion="CAMBIAR_ESTADO_VINCULO",
            id_vinculacion=link.id_vinculacion,
            descripcion=f"Cambio de estado del vínculo a {destino}",
            anteriores=anterior,
            nuevos={"estado": destino, "motivo_estado": datos.motivo},
            direccion_ip=direccion_ip,
        )
        await db.commit()

        usuarios = await _cargar_usuarios(db, [link.id_usuario])
        medicos = await _cargar_medicos(db, [link.id_usuario])
        roles = await _roles_asignados(db, link.id_vinculacion)
        especialidades = await _especialidades_asignadas(db, link.id_vinculacion)
        sedes = await _sedes_asignadas(db, link.id_vinculacion)
        return _respuesta_vinculacion(
            link,
            usuarios.get(link.id_usuario),
            medicos.get(link.id_usuario),
            roles,
            especialidades,
            sedes,
        )
    except HTTPException:
        await db.rollback()
        raise
    except Exception:
        await db.rollback()
        raise


async def listar_mias_entidades(
    db: AsyncSession, usuario: Usuario
) -> Dict[str, Any]:
    filas = (
        await db.execute(
            select(Clinica.id_clinica, Clinica.nombre)
            .join(
                VinculacionMedicoEntidad,
                VinculacionMedicoEntidad.id_clinica == Clinica.id_clinica,
            )
            .where(
                VinculacionMedicoEntidad.id_usuario == usuario.id_usuario,
                VinculacionMedicoEntidad.estado == "ACTIVO",
                Clinica.estado == "ACTIVO",
            )
            .distinct()
            .order_by(Clinica.id_clinica)
        )
    ).all()
    return {
        "items": [
            {"id_clinica": id_clinica, "nombre": nombre}
            for id_clinica, nombre in filas
        ]
    }


async def listar_mias(
    db: AsyncSession,
    usuario: Usuario,
    page: int,
    per_page: int,
    estado: Optional[str] = None,
) -> Dict[str, Any]:
    base = select(VinculacionMedicoEntidad.id_vinculacion).where(
        VinculacionMedicoEntidad.id_usuario == usuario.id_usuario
    )
    if estado:
        base = base.where(VinculacionMedicoEntidad.estado == estado)

    total = (
        await db.scalar(select(func.count()).select_from(base.subquery()))
    ) or 0
    ids = list(
        (
            await db.scalars(
                base.order_by(VinculacionMedicoEntidad.id_vinculacion)
                .offset((page - 1) * per_page)
                .limit(per_page)
            )
        ).all()
    )
    if not ids:
        return {"total": total, "page": page, "per_page": per_page, "items": []}

    links = list(
        (
            await db.scalars(
                select(VinculacionMedicoEntidad)
                .where(VinculacionMedicoEntidad.id_vinculacion.in_(ids))
                .order_by(VinculacionMedicoEntidad.id_vinculacion)
            )
        ).all()
    )
    usuarios = await _cargar_usuarios(db, [usuario.id_usuario])
    usuario_db = usuarios.get(usuario.id_usuario)
    medicos = await _cargar_medicos(db, [usuario.id_usuario])
    asignaciones = await _asignaciones_por_vinculacion(db, ids)
    sedes_asignadas = await _sedes_por_vinculacion(db, ids)
    medico = medicos.get(usuario.id_usuario)
    items = []
    for link in links:
        roles, especialidades = asignaciones.get(link.id_vinculacion, ([], []))
        items.append(
            _respuesta_vinculacion(
                link,
                usuario_db or usuario,
                medico,
                roles,
                especialidades,
                sedes_asignadas.get(link.id_vinculacion, []),
            )
        )
    return {"total": total, "page": page, "per_page": per_page, "items": items}


async def _responder_invitacion(
    db: AsyncSession,
    usuario: Usuario,
    id_vinculacion: int,
    nuevo_estado: str,
    motivo: Optional[str],
    direccion_ip: Optional[str],
) -> Dict[str, Any]:
    try:
        link = await db.scalar(
            select(VinculacionMedicoEntidad)
            .where(VinculacionMedicoEntidad.id_vinculacion == id_vinculacion)
            .with_for_update()
        )
        if link is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Vinculación no encontrada",
            )
        if int(link.id_usuario) != int(usuario.id_usuario):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="La invitación pertenece a otro médico",
            )
        if link.estado != "INVITADO":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="La invitación ya fue respondida",
            )

        usuarios = await _cargar_usuarios(db, [usuario.id_usuario])
        actor = usuarios.get(usuario.id_usuario) or usuario

        anterior = link.estado
        link.estado = nuevo_estado
        link.respondido_en = _ahora()
        link.fecha_estado = _ahora()
        link.usuario_estado = actor.id_usuario
        link.motivo_estado = motivo
        link.row_version = int(link.row_version) + 1

        await _registrar_historial(
            db,
            id_vinculacion=link.id_vinculacion,
            tipo_evento="RESPUESTA_INVITACION",
            actor=actor,
            estado_anterior=anterior,
            estado_nuevo=nuevo_estado,
            motivo=motivo,
            datos={},
        )
        await _auditar(
            db,
            actor=actor,
            id_clinica=int(link.id_clinica),
            accion=f"RESPUESTA_INVITACION_{nuevo_estado}",
            id_vinculacion=link.id_vinculacion,
            descripcion=f"Respuesta del médico a la invitación: {nuevo_estado}",
            anteriores={"estado": anterior},
            nuevos={"estado": nuevo_estado, "motivo": motivo},
            direccion_ip=direccion_ip,
        )
        await db.commit()

        medicos = await _cargar_medicos(db, [actor.id_usuario])
        roles = await _roles_asignados(db, link.id_vinculacion)
        especialidades = await _especialidades_asignadas(db, link.id_vinculacion)
        sedes = await _sedes_asignadas(db, link.id_vinculacion)
        return _respuesta_vinculacion(
            link,
            actor,
            medicos.get(actor.id_usuario),
            roles,
            especialidades,
            sedes,
        )
    except HTTPException:
        await db.rollback()
        raise
    except Exception:
        await db.rollback()
        raise


async def aceptar_invitacion(
    db: AsyncSession,
    usuario: Usuario,
    id_vinculacion: int,
    direccion_ip: Optional[str] = None,
) -> Dict[str, Any]:
    return await _responder_invitacion(
        db, usuario, id_vinculacion, "ACTIVO", None, direccion_ip
    )


async def rechazar_invitacion(
    db: AsyncSession,
    usuario: Usuario,
    id_vinculacion: int,
    datos: VinculacionRechazo,
    direccion_ip: Optional[str] = None,
) -> Dict[str, Any]:
    return await _responder_invitacion(
        db, usuario, id_vinculacion, "RECHAZADO", datos.motivo, direccion_ip
    )


async def obtener_permisos_efectivos(
    db: AsyncSession, id_vinculacion: int
) -> Dict[str, Any]:
    roles = await _roles_asignados(db, id_vinculacion)
    principal = next((rol.nombre for rol, es_principal in roles if es_principal), None)
    permisos: List[str] = []
    if roles:
        filas = await db.execute(
            select(Permiso)
            .join(RolPermiso, RolPermiso.id_permiso == Permiso.id_permiso)
            .where(RolPermiso.id_rol.in_([rol.id_rol for rol, _ in roles]))
            .order_by(Permiso.nombre)
        )
        for permiso in filas.scalars().all():
            if (permiso.estado or "ACTIVO").upper() != "ACTIVO":
                continue
            if permiso.nombre and permiso.nombre not in permisos:
                permisos.append(permiso.nombre)
            codigo = f"{permiso.modulo}.{permiso.accion}"
            if codigo not in permisos:
                permisos.append(codigo)
    return {
        "roles": [rol.nombre for rol, _ in roles],
        "rol_principal": principal,
        "permisos": permisos,
    }
