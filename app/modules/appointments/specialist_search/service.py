from datetime import date, datetime, time, timedelta
from typing import List, Optional
from fastapi import HTTPException, status
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.modules.appointments.models import (
    BloqueoAgenda,
    Cita,
    Especialidad,
    HorarioMedico,
    Medico,
    MedicoEspecialidad,
    ServicioMedico,
)
from app.modules.auth.models import Usuario
from .schemas import (
    BusquedaEspecialistasResponse,
    DiaDisponibilidad,
    EspecialidadOut,
    EspecialistaDisponibilidadResponse,
    EspecialistaItem,
    ServicioOut,
    SlotDisponibilidad,
)


def _normalizar_hora(val) -> Optional[time]:
    if val is None:
        return None
    if isinstance(val, time):
        return val
    if isinstance(val, str):
        try:
            return time.fromisoformat(val.strip())
        except ValueError:
            return None
    return None


def _intersecta(inicio_a: time, fin_a: time, inicio_b: time, fin_b: time) -> bool:
    if inicio_a is None or fin_a is None or inicio_b is None or fin_b is None:
        return True
    return inicio_a < fin_b and fin_a > inicio_b


def _formatear_hora(t: time) -> str:
    return t.strftime("%H:%M:%S")


def calcular_disponibilidad_medico(
    db: Session,
    medico: Medico,
    fecha_inicio: date,
    fecha_fin: date,
    id_servicio_filtro: Optional[int] = None,
) -> List[DiaDisponibilidad]:
    # Obtener horarios del médico
    query_horarios = db.query(HorarioMedico).filter(
        HorarioMedico.id_medico == medico.id_medico,
        func.lower(HorarioMedico.estado) == "activo",
    )
    if id_servicio_filtro:
        query_horarios = query_horarios.filter(HorarioMedico.id_servicio == id_servicio_filtro)
    horarios = query_horarios.all()

    # Si no tiene horarios configurados, devolver días vacíos
    if not horarios:
        dias_resp = []
        curr = fecha_inicio
        while curr <= fecha_fin:
            dias_resp.append(DiaDisponibilidad(fecha=curr.isoformat(), slots=[]))
            curr += timedelta(days=1)
        return dias_resp

    # Mapear horarios por día de la semana (isoweekday: 1=Lunes, 7=Domingo)
    servicios_ids = list({h.id_servicio for h in horarios})
    servicios_db = db.query(ServicioMedico).filter(
        ServicioMedico.id_servicio.in_(servicios_ids),
        func.lower(ServicioMedico.estado) == "activo",
    ).all()
    servicios_map = {s.id_servicio: s for s in servicios_db}

    # Citas en el rango para este médico (excluyendo CANCELADA)
    citas_db = db.query(Cita).filter(
        Cita.id_medico == medico.id_medico,
        Cita.fecha_cita >= fecha_inicio,
        Cita.fecha_cita <= fecha_fin,
    ).all()
    citas_por_fecha = {}
    for c in citas_db:
        if str(c.estado or "").strip().upper() == "CANCELADA":
            continue
        citas_por_fecha.setdefault(c.fecha_cita, []).append(c)

    # Solo los bloqueos aprobados retiran disponibilidad (spec CU06).
    bloqueos_db = db.query(BloqueoAgenda).filter(
        BloqueoAgenda.id_medico == medico.id_medico,
        BloqueoAgenda.fecha >= fecha_inicio,
        BloqueoAgenda.fecha <= fecha_fin,
        func.upper(BloqueoAgenda.estado) == "APROBADO",
    ).all()
    bloqueos_por_fecha = {}
    for b in bloqueos_db:
        bloqueos_por_fecha.setdefault(b.fecha, []).append(b)

    dias_resp = []
    curr = fecha_inicio
    while curr <= fecha_fin:
        dia_sem = curr.isoweekday()
        horarios_dia = [h for h in horarios if h.dia_semana == dia_sem]
        slots_dia: List[SlotDisponibilidad] = []
        vistos = set()

        for h in horarios_dia:
            servicio = servicios_map.get(h.id_servicio)
            if not servicio or servicio.duracion_minutos <= 0:
                continue

            duracion = timedelta(minutes=servicio.duracion_minutos)
            cursor = datetime.combine(curr, servicio.hora_inicio)
            fin_servicio = datetime.combine(curr, servicio.hora_fin)

            citas_dia = citas_por_fecha.get(curr, [])
            bloqueos_dia = bloqueos_por_fecha.get(curr, [])

            while cursor + duracion <= fin_servicio:
                slot_inicio = cursor.time()
                slot_fin = (cursor + duracion).time()
                slot_key = (_formatear_hora(slot_inicio), _formatear_hora(slot_fin))

                if slot_key not in vistos:
                    vistos.add(slot_key)
                    # Comprobar solapamiento con citas
                    ocupado_cita = False
                    for c in citas_dia:
                        c_inicio = _normalizar_hora(c.hora_inicio)
                        c_fin = _normalizar_hora(c.hora_fin)
                        if _intersecta(slot_inicio, slot_fin, c_inicio, c_fin):
                            ocupado_cita = True
                            break

                    # Comprobar solapamiento con bloqueos
                    ocupado_bloqueo = False
                    for b in bloqueos_dia:
                        b_inicio = _normalizar_hora(b.hora_inicio)
                        b_fin = _normalizar_hora(b.hora_fin)
                        if _intersecta(slot_inicio, slot_fin, b_inicio, b_fin):
                            ocupado_bloqueo = True
                            break

                    disponible = not ocupado_cita and not ocupado_bloqueo
                    slots_dia.append(
                        SlotDisponibilidad(
                            hora_inicio=_formatear_hora(slot_inicio),
                            hora_fin=_formatear_hora(slot_fin),
                            disponible=disponible,
                        )
                    )
                cursor += duracion

        # Ordenar slots por hora de inicio
        slots_dia.sort(key=lambda s: s.hora_inicio)
        dias_resp.append(DiaDisponibilidad(fecha=curr.isoformat(), slots=slots_dia))
        curr += timedelta(days=1)

    return dias_resp


def buscar_especialistas(
    db: Session,
    tenant_id: int,
    nombre: Optional[str] = None,
    especialidad_id: Optional[int] = None,
    modalidad: str = "AMBAS",
    costo_min: Optional[float] = None,
    costo_max: Optional[float] = None,
    fecha_inicio: Optional[date] = None,
    fecha_fin: Optional[date] = None,
    page: int = 1,
    per_page: int = 20,
) -> BusquedaEspecialistasResponse:
    # Validaciones
    if costo_min is not None and costo_max is not None and costo_min > costo_max:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="costo_min no puede ser mayor que costo_max",
        )
    if fecha_inicio and fecha_fin:
        if fecha_inicio > fecha_fin:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="fecha_inicio no puede ser posterior a fecha_fin",
            )
        if (fecha_fin - fecha_inicio).days > 31:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="El rango de fechas no puede exceder 31 días",
            )
    elif not fecha_inicio or not fecha_fin:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="fecha_inicio y fecha_fin son requeridos",
        )

    # Base query: médicos del tenant activo
    query = (
        db.query(Medico)
        .join(Usuario, Medico.id_usuario == Usuario.id_usuario)
        .filter(
            func.lower(Medico.estado) == "activo",
            func.lower(Usuario.estado) == "activo",
            Medico.id_clinica == tenant_id,
        )
    )

    # Filtro por nombre
    if nombre and nombre.strip():
        term = f"%{nombre.strip()}%"
        query = query.filter(
            or_(
                Usuario.nombres.ilike(term),
                Usuario.apellidos.ilike(term),
                func.concat(Usuario.nombres, " ", Usuario.apellidos).ilike(term),
            )
        )

    # Filtro por especialidad
    if especialidad_id:
        query = query.join(
            MedicoEspecialidad,
            Medico.id_medico == MedicoEspecialidad.id_medico,
        ).filter(MedicoEspecialidad.id_especialidad == especialidad_id)

    # Filtro por servicios (modalidad y costo)
    if modalidad != "AMBAS" or costo_min is not None or costo_max is not None:
        servicio_subquery = (
            db.query(HorarioMedico.id_medico)
            .join(ServicioMedico, HorarioMedico.id_servicio == ServicioMedico.id_servicio)
            .filter(
                func.lower(HorarioMedico.estado) == "activo",
                func.lower(ServicioMedico.estado) == "activo",
                ServicioMedico.id_clinica == tenant_id,
            )
        )
        if modalidad != "AMBAS":
            servicio_subquery = servicio_subquery.filter(
                func.upper(ServicioMedico.modalidad) == modalidad.upper()
            )
        if costo_min is not None:
            servicio_subquery = servicio_subquery.filter(ServicioMedico.costo >= costo_min)
        if costo_max is not None:
            servicio_subquery = servicio_subquery.filter(ServicioMedico.costo <= costo_max)

        query = query.filter(Medico.id_medico.in_(servicio_subquery))

    query = query.distinct()
    total = query.count()

    offset = (page - 1) * per_page
    medicos = query.order_by(Medico.id_medico).offset(offset).limit(per_page).all()

    items: List[EspecialistaItem] = []
    for m in medicos:
        u = m.usuario
        nombre_completo = f"{u.nombres} {u.apellidos}".strip() if u else "Sin nombre"

        # Especialidades
        especialidades = []
        for me in m.especialidades:
            if me.especialidad and me.especialidad.estado.lower() == "activo":
                especialidades.append(
                    EspecialidadOut(
                        id_especialidad=me.especialidad.id_especialidad,
                        nombre=me.especialidad.nombre,
                    )
                )

        # Servicios asignados al médico
        servicios_query = (
            db.query(ServicioMedico)
            .join(HorarioMedico, HorarioMedico.id_servicio == ServicioMedico.id_servicio)
            .filter(
                HorarioMedico.id_medico == m.id_medico,
                func.lower(HorarioMedico.estado) == "activo",
                func.lower(ServicioMedico.estado) == "activo",
                ServicioMedico.id_clinica == tenant_id,
            )
        )
        if modalidad != "AMBAS":
            servicios_query = servicios_query.filter(
                func.upper(ServicioMedico.modalidad) == modalidad.upper()
            )
        if costo_min is not None:
            servicios_query = servicios_query.filter(ServicioMedico.costo >= costo_min)
        if costo_max is not None:
            servicios_query = servicios_query.filter(ServicioMedico.costo <= costo_max)

        servicios_db = servicios_query.distinct().all()
        servicios_out = [
            ServicioOut(
                id_servicio=s.id_servicio,
                nombre=s.nombre,
                modalidad=s.modalidad or "PRESENCIAL",
                costo=float(s.costo),
                moneda="BOB",
                duracion_minutos=s.duracion_minutos,
            )
            for s in servicios_db
        ]

        # Disponibilidad calculada
        disp = calcular_disponibilidad_medico(db, m, fecha_inicio, fecha_fin)

        items.append(
            EspecialistaItem(
                id_medico=m.id_medico,
                nombre_completo=nombre_completo,
                foto_url=m.foto_perfil or (u.foto_perfil if u else None),
                matricula_profesional=m.matricula_profesional,
                especialidades=especialidades,
                servicios=servicios_out,
                disponibilidad=disp,
            )
        )

    return BusquedaEspecialistasResponse(
        total=total,
        page=page,
        per_page=per_page,
        items=items,
    )


def obtener_disponibilidad_especialista(
    db: Session,
    tenant_id: int,
    id_medico: int,
    fecha_inicio: date,
    fecha_fin: date,
    id_servicio: Optional[int] = None,
) -> EspecialistaDisponibilidadResponse:
    if fecha_inicio > fecha_fin:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="fecha_inicio no puede ser posterior a fecha_fin",
        )
    if (fecha_fin - fecha_inicio).days > 31:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El rango de fechas no puede exceder 31 días",
        )

    # Verificar que el médico pertenece al tenant
    medico = (
        db.query(Medico)
        .join(Usuario, Medico.id_usuario == Usuario.id_usuario)
        .filter(
            Medico.id_medico == id_medico,
            func.lower(Medico.estado) == "activo",
            Medico.id_clinica == tenant_id,
        )
        .first()
    )
    if not medico:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Especialista no encontrado en este tenant",
        )

    u = medico.usuario
    nombre_completo = f"{u.nombres} {u.apellidos}".strip() if u else "Sin nombre"

    especialidades = [
        EspecialidadOut(
            id_especialidad=me.especialidad.id_especialidad,
            nombre=me.especialidad.nombre,
        )
        for me in medico.especialidades
        if me.especialidad and me.especialidad.estado.lower() == "activo"
    ]

    servicios_query = (
        db.query(ServicioMedico)
        .join(HorarioMedico, HorarioMedico.id_servicio == ServicioMedico.id_servicio)
        .filter(
            HorarioMedico.id_medico == medico.id_medico,
            func.lower(HorarioMedico.estado) == "activo",
            func.lower(ServicioMedico.estado) == "activo",
            ServicioMedico.id_clinica == tenant_id,
        )
    )
    if id_servicio:
        servicios_query = servicios_query.filter(ServicioMedico.id_servicio == id_servicio)

    servicios_db = servicios_query.distinct().all()
    servicios_out = [
        ServicioOut(
            id_servicio=s.id_servicio,
            nombre=s.nombre,
            modalidad=s.modalidad or "PRESENCIAL",
            costo=float(s.costo),
            moneda="BOB",
            duracion_minutos=s.duracion_minutos,
        )
        for s in servicios_db
    ]

    disp = calcular_disponibilidad_medico(
        db, medico, fecha_inicio, fecha_fin, id_servicio_filtro=id_servicio
    )

    return EspecialistaDisponibilidadResponse(
        id_medico=medico.id_medico,
        nombre_completo=nombre_completo,
        foto_url=medico.foto_perfil or (u.foto_perfil if u else None),
        matricula_profesional=medico.matricula_profesional,
        especialidades=especialidades,
        servicios=servicios_out,
        disponibilidad=disp,
    )

