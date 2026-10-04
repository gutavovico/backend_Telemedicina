"""Verificación CU05 contra Neon con datos exclusivamente CU05NEONVERIFYV1.

Ejecutar desde backend_Telemedicina: ../.venv/Scripts/python.exe -m scripts.run_cu05_neon_verify
No usa SQLite, no altera .env y nunca imprime tokens ni claves de configuración.
"""
from datetime import timedelta, date

from fastapi.testclient import TestClient
from sqlalchemy import func, select, text

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.main import app
from app.modules.appointments.agenda.service import hoy_agenda
from app.modules.appointments.models import BloqueoAgenda, Cita, HorarioMedico, Medico, ServicioMedico
from app.modules.auth.login.schemas import LoginRequest
from app.modules.auth.models import Auditoria, Clinica, Rol, Usuario
from app.modules.communications.models import Notificacion
from app.modules.medical_records.models import Paciente


MARKER = "CU05NEONVERIFYV1"
PASSWORD = "Cu05-Neon-2026!"  # Solo cuentas sintéticas de este fixture.
PREFIX = "/appointments/agenda"
ACCOUNTS = {
    "admin_a": ("A", "ADMIN"),
    "medico_a": ("A", "MEDICO"),
    "recepcion_a": ("A", "RECEPCION"),
    "paciente_a": ("A", "PACIENTE"),
    "admin_b": ("B", "ADMIN"),
    "medico_b": ("B", "MEDICO"),
}


def email(key: str) -> str:
    return f"cu05neonverifyv1-{key.replace('_', '-')}@example.com"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def marker_counts(db) -> dict[str, int]:
    return {
        "clinicas": db.scalar(select(func.count()).select_from(Clinica).where(Clinica.nit.like(MARKER + "%"))),
        "roles": db.scalar(select(func.count()).select_from(Rol).where(Rol.descripcion == MARKER)),
        "usuarios": db.scalar(select(func.count()).select_from(Usuario).where(
            Usuario.correo.in_([email(k) for k in ACCOUNTS]))),
        "medicos": db.scalar(select(func.count()).select_from(Medico).where(
            Medico.matricula_profesional.like(MARKER + "%"))),
        "pacientes": db.scalar(select(func.count()).select_from(Paciente).where(Paciente.ci.like(MARKER + "%"))),
        "citas": db.scalar(select(func.count()).select_from(Cita).where(Cita.notas.like(MARKER + "%"))),
        "bloqueos": db.scalar(select(func.count()).select_from(BloqueoAgenda).where(
            BloqueoAgenda.motivo.like(MARKER + "%"))),
    }


def fixture(db):
    counts = marker_counts(db)
    if all(value == 0 for value in counts.values()):
        tomorrow = hoy_agenda() + timedelta(days=1)
        digest = hash_password(PASSWORD)
        clinics = {}
        roles = {}
        users = {}
        doctors = {}
        patients = {}
        for code in ("A", "B"):
            clinic = Clinica(nombre=f"{MARKER} Clínica {code}", razon_social="Verificación sintética CU05",
                             nit=f"{MARKER}-{code}", estado="ACTIVO")
            db.add(clinic)
            db.flush()
            clinics[code] = clinic
            for key, (clinic_code, role_name) in ACCOUNTS.items():
                if clinic_code != code:
                    continue
                role = Rol(id_clinica=clinic.id_clinica, nombre=role_name,
                           descripcion=MARKER, estado="ACTIVO")
                db.add(role)
                db.flush()
                roles[key] = role
                user = Usuario(id_clinica=clinic.id_clinica, id_rol=role.id_rol,
                               nombres="Verificación", apellidos=f"CU05 {key}",
                               correo=email(key), password_hash=digest, estado="activo",
                               notificaciones_push=True, notificaciones_email=False,
                               notificaciones_sms=False)
                db.add(user)
                db.flush()
                users[key] = user
            doctor = Medico(id_usuario=users[f"medico_{code.lower()}"].id_usuario,
                            id_clinica=clinic.id_clinica,
                            matricula_profesional=f"{MARKER}-{code}", estado="activo")
            db.add(doctor)
            db.flush()
            doctors[code] = doctor
            patient = Paciente(id_clinica=clinic.id_clinica,
                               id_usuario=users["paciente_a"].id_usuario if code == "A" else None,
                               nombres="Paciente", apellidos=f"Sintético CU05 {code}",
                               ci=f"{MARKER}-{code}", complemento="",
                               fecha_nacimiento=date(1990, 1, 1), genero="F", telefono="000000000",
                               estado="ACTIVO")
            db.add(patient)
            db.flush()
            patients[code] = patient
        for label, offset, state, end in (("CANCELADA", 7, "CANCELADA", None),
                                           ("SIN_FIN", 14, "CONFIRMADA", None)):
            db.execute(text("""INSERT INTO citas
                (id_clinica,id_medico,id_paciente,id_servicio,fecha_cita,hora_inicio,hora_fin,
                 estado,tipo_consulta,modalidad,motivo,notas)
                VALUES (:clinic,:doctor,:patient,1,:day,'10:00',:end,:state,
                        'PRESENCIAL','PRESENCIAL','Verificación sintética CU05',:notes)"""),
                {"clinic": clinics["A"].id_clinica, "doctor": doctors["A"].id_medico,
                 "patient": patients["A"].id_paciente, "day": tomorrow + timedelta(days=offset),
                 "end": end, "state": state, "notes": f"{MARKER}:{label}"})
        db.flush()
        print("fixture_creado=2 clinicas, 6 roles, 6 usuarios, 2 medicos, 2 pacientes, 2 citas")
    else:
        require({k: v for k, v in counts.items() if k != "bloqueos"} ==
                {"clinicas": 2, "roles": 6, "usuarios": 6, "medicos": 2,
                 "pacientes": 2, "citas": 2} and counts["bloqueos"] in (0, 1, 2),
                f"Marcador existente incompleto o inesperado: {counts}; no se reutiliza")
        print("fixture_existente=cantidades comprobadas; no se duplican registros")


def scope(db):
    clinics = {c.nit[-1]: c for c in db.scalars(select(Clinica).where(
        Clinica.nit.in_([f"{MARKER}-A", f"{MARKER}-B"]))).all()}
    users = {key: db.scalar(select(Usuario).where(Usuario.correo == email(key))) for key in ACCOUNTS}
    doctors = {code: db.scalar(select(Medico).where(
        Medico.matricula_profesional == f"{MARKER}-{code}")) for code in ("A", "B")}
    patients = {code: db.scalar(select(Paciente).where(Paciente.ci == f"{MARKER}-{code}"))
                for code in ("A", "B")}
    citas = {label: db.scalar(select(Cita).where(Cita.notas == f"{MARKER}:{label}"))
             for label in ("CANCELADA", "SIN_FIN")}
    require(len(clinics) == 2 and all(users.values()) and all(doctors.values())
            and all(patients.values()) and all(citas.values()), "Fixture incompleto")
    for key, (code, role) in ACCOUNTS.items():
        user = users[key]
        require(user.id_clinica == clinics[code].id_clinica and user.rol.nombre == role
                and user.rol.id_clinica == user.id_clinica and user.rol.descripcion == MARKER,
                f"Relación usuario/rol/clínica inesperada: {key}")
    for code in ("A", "B"):
        require(doctors[code].id_usuario == users[f"medico_{code.lower()}"].id_usuario
                and doctors[code].id_clinica == clinics[code].id_clinica
                and patients[code].id_clinica == clinics[code].id_clinica,
                f"Relación médico/paciente/clínica inesperada: {code}")
    tomorrow = citas["CANCELADA"].fecha_cita - timedelta(days=7)
    require(citas["SIN_FIN"].fecha_cita == tomorrow + timedelta(days=14)
            and citas["CANCELADA"].estado == "CANCELADA"
            and citas["SIN_FIN"].estado == "CONFIRMADA"
            and all(c.id_medico == doctors["A"].id_medico and c.id_paciente == patients["A"].id_paciente
                    and c.hora_inicio == "10:00" and c.hora_fin is None for c in citas.values()),
            "Citas sintéticas inesperadas")
    require(db.scalar(select(func.count()).select_from(ServicioMedico).where(
        ServicioMedico.id_servicio == 1, ServicioMedico.estado == "activo",
        ServicioMedico.duracion_minutos == 30)) == 1, "Servicio 1 inesperado")
    return clinics, users, doctors, patients, citas, tomorrow


def request(client, method, path, token=None, expected=200, **kwargs):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    response = client.request(method, path, headers=headers, **kwargs)
    payload = response.json()
    require(response.status_code == expected,
            f"{method} {path}: HTTP {response.status_code}, esperado {expected}")
    return payload


def available(client, token, doctor_id, service_id, day):
    return request(client, "GET", PREFIX + "/disponibilidad", token,
                   params={"id_medico": doctor_id, "id_servicio": service_id,
                           "fecha": day.isoformat()})


def free(data):
    return sum(bool(slot["disponible"]) for slot in data["slots"])


def main():
    require(settings.DB_HOST.lower().endswith(".neon.tech"), "Destino no Neon; detener")
    require("http://localhost:4200" in settings.cors_origins_list, "CORS local no habilitado")
    LoginRequest(correo=email("admin_a"), password=PASSWORD)
    with SessionLocal.begin() as db:
        counts = marker_counts(db)
        existing = any(counts.values())
        fixture(db)
    with SessionLocal() as db:
        clinics, users, doctors, patients, citas, day = scope(db)
        ids = {"clinics": {k: v.id_clinica for k, v in clinics.items()},
               "users": {k: v.id_usuario for k, v in users.items()},
               "doctors": {k: v.id_medico for k, v in doctors.items()},
               "patients": {k: v.id_paciente for k, v in patients.items()},
               "citas": {k: v.id_cita for k, v in citas.items()}}
        require(ids["users"]["medico_a"] != ids["doctors"]["A"],
                "Fixture no distingue id_usuario de id_medico")
        print("ids_sinteticos=", ids)
        print("fechas=", {"flujo": day.isoformat(), "cancelada": (day + timedelta(days=7)).isoformat(),
                           "sin_fin": (day + timedelta(days=14)).isoformat()})
    if existing:
        print("Marcador existente validado; se reanuda sin duplicar el horario ya creado.")
    if not existing or counts["bloqueos"] < 2:
        require(day == hoy_agenda() + timedelta(days=1),
                "El flujo parcial ya no corresponde a mañana en Bolivia")
    with TestClient(app) as client:
        tokens = {}
        for key in ACCOUNTS:
            result = request(client, "POST", "/auth/login", expected=200,
                             json={"correo": email(key), "password": PASSWORD})
            tokens[key] = result["access_token"]
            me = request(client, "GET", "/auth/me", tokens[key])
            require(me["id_usuario"] == ids["users"][key]
                    and me["id_clinica"] == ids["clinics"][ACCOUNTS[key][0]],
                    f"/auth/me inesperado: {key}")
        print("login_me=6/6; médico id_usuario distinto de id_medico")
        da, db = ids["doctors"]["A"], ids["doctors"]["B"]
        token = tokens["medico_a"]
        baseline = available(client, token, da, 1, day)
        require(baseline["citas_verificadas"] and free(baseline) in (0, 10),
                "Estado inicial de agenda inesperado")
        if free(baseline) == 0:
            schedule = request(client, "POST", PREFIX + "/horarios", token, expected=201,
                               json={"id_servicio": 1, "dia_semana": day.isoweekday()})
            require(schedule["id_medico"] == da, "El horario no resolvió id_medico del usuario")
        else:
            with SessionLocal() as check:
                schedules = check.scalars(select(HorarioMedico).where(
                    HorarioMedico.id_medico == da, HorarioMedico.id_servicio == 1,
                    HorarioMedico.dia_semana == day.isoweekday())).all()
                require(len(schedules) == 1 and schedules[0].estado == "activo",
                        "Horario existente inesperado")
        open_day = available(client, token, da, 1, day)
        require(open_day["citas_verificadas"] and free(open_day) == 10, "No se habilitaron 10 slots")
        print("horario=activo; slots_libres=10")
        body = {"id_servicio": 1, "fecha": day.isoformat(), "hora_inicio": "10:00",
                "hora_fin": "11:00", "motivo": f"{MARKER}:FLUJO"}
        with SessionLocal() as check:
            previous_flow = check.scalar(select(BloqueoAgenda).where(BloqueoAgenda.motivo == body["motivo"]))
            if previous_flow:
                require(previous_flow.id_medico == da and previous_flow.id_servicio == 1
                        and previous_flow.fecha == day and previous_flow.estado == "LIBERADO",
                        "Bloqueo de flujo existente inesperado")
        if previous_flow is None:
            request(client, "POST", PREFIX + "/bloqueos", token, expected=422,
                    json={**body, "hora_inicio": "10:15", "hora_fin": "10:45"})
            block = request(client, "POST", PREFIX + "/bloqueos", token, expected=201, json=body)
            require(block["estado"] == "PENDIENTE", "Bloqueo no pendiente")
            request(client, "POST", PREFIX + "/bloqueos", token, expected=409,
                    json={**body, "hora_inicio": "10:30", "hora_fin": "11:30"})
            require(free(available(client, token, da, 1, day)) == 8, "Pendiente no bloqueó 2 slots")
            request(client, "PATCH", f"{PREFIX}/bloqueos/{block['id_bloqueo']}/aprobar",
                    tokens["admin_b"], expected=404)
            approved = request(client, "PATCH", f"{PREFIX}/bloqueos/{block['id_bloqueo']}/aprobar",
                               tokens["admin_a"])
            require(approved["estado"] == "APROBADO" and approved["citas_afectadas"] == [],
                    "Aprobación inesperada")
            require(free(available(client, token, da, 1, day)) == 8, "Aprobado no bloqueó 2 slots")
            released = request(client, "PATCH", f"{PREFIX}/bloqueos/{block['id_bloqueo']}/liberar", token)
            require(released["estado"] == "LIBERADO" and free(available(client, token, da, 1, day)) == 10,
                    "Liberación no recuperó slots")
            print("bloqueo=201 PENDIENTE/APROBADO/LIBERADO; slots=8/8/10; solape=409, desalineado=422")
        else:
            print("bloqueo_flujo=LIBERADO existente; disponibilidad recuperada=10")
        cancel_day = day + timedelta(days=7)
        canceled = available(client, token, da, 1, cancel_day)
        require(canceled["citas_verificadas"] and canceled["advertencias"] == [] and free(canceled) == 10,
                "CANCELADA ocupó slots o produjo aviso")
        with SessionLocal() as check:
            previous_cancel = check.scalar(select(BloqueoAgenda).where(
                BloqueoAgenda.motivo == f"{MARKER}:CANCELADA"))
            if previous_cancel:
                require(previous_cancel.id_medico == da and previous_cancel.id_servicio == 1
                        and previous_cancel.fecha == cancel_day
                        and previous_cancel.estado in ("PENDIENTE", "APROBADO", "LIBERADO"),
                        "Bloqueo de cancelación existente inesperado")
                cancel_id, cancel_state = previous_cancel.id_bloqueo, previous_cancel.estado
            else:
                cancel_id, cancel_state = None, None
        if cancel_id is None:
            request(client, "POST", PREFIX + "/bloqueos", token, expected=422,
                    json={**body, "fecha": cancel_day.isoformat(), "hora_fin": "10:30"})
            cancel_block = request(client, "POST", PREFIX + "/bloqueos", tokens["recepcion_a"], expected=201,
                                   json={**body, "id_medico": da, "fecha": cancel_day.isoformat(),
                                         "hora_fin": "10:30", "motivo": f"{MARKER}:CANCELADA"})
            cancel_id, cancel_state = cancel_block["id_bloqueo"], "PENDIENTE"
        if cancel_state == "PENDIENTE":
            cancel_approval = request(client, "PATCH", f"{PREFIX}/bloqueos/{cancel_id}/aprobar",
                                      tokens["admin_a"])
            require(cancel_approval["citas_afectadas"] == []
                    and cancel_approval["notificaciones_creadas"] == 0,
                    "CANCELADA recibió aviso de reprogramación")
            cancel_state = "APROBADO"
        if cancel_state == "APROBADO":
            request(client, "PATCH", f"{PREFIX}/bloqueos/{cancel_id}/liberar", token)
        require(free(available(client, token, da, 1, cancel_day)) == 10,
                "CANCELADA no recuperó los slots")
        missing = available(client, token, da, 1, day + timedelta(days=14))
        require(not missing["citas_verificadas"] and free(missing) == 0
                and any(str(ids["citas"]["SIN_FIN"]) in warning and "hora_fin" in warning
                        for warning in missing["advertencias"]),
                "Cita sin hora_fin no cerró disponibilidad con aviso")
        print("CANCELADA=10 slots libres, 0 avisos; sin_hora_fin=0 libres y advertencia específica")
        request(client, "GET", PREFIX + "/servicios", tokens["paciente_a"], expected=403)
        request(client, "POST", PREFIX + "/horarios", tokens["admin_a"], expected=403,
                json={"id_servicio": 1, "dia_semana": day.isoweekday()})
        request(client, "POST", PREFIX + "/horarios", tokens["medico_b"], expected=403,
                json={"id_servicio": 1, "dia_semana": day.isoweekday(), "id_medico": da})
        request(client, "GET", PREFIX + "/disponibilidad", tokens["recepcion_a"], expected=404,
                params={"id_medico": db, "id_servicio": 1, "fecha": day.isoformat()})
        own_b = available(client, tokens["medico_b"], db, 1, day)
        require(free(own_b) in (0, 10), "Clínica B mostró un estado inesperado")
        if free(own_b) == 0:
            request(client, "POST", PREFIX + "/horarios", tokens["medico_b"], expected=201,
                    json={"id_servicio": 1, "dia_semana": day.isoweekday()})
        else:
            with SessionLocal() as check:
                require(check.scalar(select(func.count()).select_from(HorarioMedico).where(
                    HorarioMedico.id_medico == db, HorarioMedico.id_servicio == 1,
                    HorarioMedico.dia_semana == day.isoweekday(),
                    HorarioMedico.estado == "activo")) == 1, "Horario B existente inesperado")
        require(free(available(client, tokens["medico_b"], db, 1, day)) == 10,
                "Clínica B no obtuvo su propia agenda")
        print("permisos=403 paciente/admin/otro médico; clínica ajena=404; B conserva agenda independiente")
    with SessionLocal() as dbs:
        require(marker_counts(dbs)["bloqueos"] == 2, "Bloqueos reales no persistidos")
        require(all(b.estado == "LIBERADO" for b in dbs.scalars(select(BloqueoAgenda).where(
            BloqueoAgenda.motivo.like(MARKER + "%"))).all()), "Bloqueos no liberados")
        require(dbs.scalar(select(func.count()).select_from(HorarioMedico).where(
            HorarioMedico.id_medico.in_([da, db]))) == 2, "Horarios reales no persistidos")
        require(dbs.scalar(select(func.count()).select_from(Notificacion).where(
            Notificacion.id_usuario == ids["users"]["paciente_a"])) == 0,
            "Notificación sintética inesperada")
        print("neon_filas=2 horarios activos, 2 bloqueos LIBERADO, 2 citas intactas, 0 notificaciones al paciente")
    print("cuentas=", ', '.join(email(k) for k in ACCOUNTS))
    print("contraseña_sintética=", PASSWORD)


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as exc:
        print("verificacion_detenida=", exc)
        raise SystemExit(1) from None
    except Exception as exc:
        import traceback
        frames = traceback.extract_tb(exc.__traceback__)
        print("verificacion_detenida_tipo=", type(exc).__name__,
              "sqlstate=", getattr(getattr(exc, "orig", None), "pgcode", None),
              "ubicacion=", [(frame.name, frame.lineno) for frame in frames
                             if frame.filename.endswith("run_cu05_neon_verify.py")])
        raise SystemExit(1) from None
