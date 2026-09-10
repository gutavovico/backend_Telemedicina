import os
import sys
import uuid
from datetime import date, datetime, timedelta, timezone

# Agregar directorio raíz al PYTHONPATH
sys.path.insert(0, os.path.realpath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy.orm import Session
from app.core.database import SessionLocal, engine
from app.core.security import hash_password
from app.modules.auth.models import Clinica, Rol, Usuario, Auditoria
from app.modules.medical_records.models import Paciente
from app.modules.appointments.models import (
    Especialidad,
    Medico,
    MedicoEspecialidad,
    ServicioMedico,
    HorarioMedico,
    BloqueoAgenda,
    Cita,
)
from app.modules.medical_records.fichas.models import FichaClinica
from app.modules.medical_records.hce.models import HistoriaClinica, Consulta, Diagnostico
from app.modules.medical_records.clinical_documents.models import DocumentoClinico


def seed_all():
    db: Session = SessionLocal()
    print("==================================================================")
    print("  INICIANDO SEMBRADO DE DATOS DEMO (CANÓNICO Y MULTITENANT)      ")
    print("==================================================================")

    try:
        # -------------------------------------------------------------
        # 1. Clínicas (Tenants)
        # -------------------------------------------------------------
        print("\n[1/10] Verificando y Poblando Clínicas (Tenants)...")
        c1 = db.query(Clinica).filter(Clinica.id_clinica == 1).first()
        if not c1:
            c1 = Clinica(
                id_clinica=1,
                nombre="Clínica Central San Juan de Dios",
                direccion="Av. Cañoto esq. México #450, Santa Cruz",
                estado="ACTIVO",
            )
            db.add(c1)
            print("  [+] Creada Clínica Central (id_clinica=1)")
        else:
            c1.nombre = "Clínica Central San Juan de Dios"
            c1.direccion = "Av. Cañoto esq. México #450, Santa Cruz"
            c1.estado = "ACTIVO"
            print("  [=] Clínica Central actualizada")

        c2 = db.query(Clinica).filter(Clinica.id_clinica == 2).first()
        if not c2:
            c2 = Clinica(
                id_clinica=2,
                nombre="Red Médica del Norte",
                direccion="Av. Banzer Km 5.5 #120, Santa Cruz",
                estado="ACTIVO",
            )
            db.add(c2)
            print("  [+] Creada Clínica Norte (id_clinica=2)")
        else:
            c2.nombre = "Red Médica del Norte"
            c2.estado = "ACTIVO"
            print("  [=] Clínica Norte verificada")

        db.flush()

        # -------------------------------------------------------------
        # 2. Roles Canónicos
        # -------------------------------------------------------------
        print("\n[2/10] Verificando Roles del Sistema...")
        roles_data = [
            (1, "ADMIN", "Administrador del Sistema y Tenant"),
            (2, "MEDICO", "Personal Médico y Especialistas"),
            (3, "RECEPCION", "Personal de Admisión y Recepción"),
            (4, "PACIENTE", "Paciente y Usuario de la Plataforma"),
        ]
        for r_id, r_name, r_desc in roles_data:
            rol = db.query(Rol).filter(Rol.id_rol == r_id).first()
            if not rol:
                rol = Rol(id_rol=r_id, nombre=r_name, descripcion=r_desc, estado="ACTIVO")
                db.add(rol)
                print(f"  [+] Creado Rol {r_name} (id={r_id})")
            else:
                rol.nombre = r_name
                rol.descripcion = r_desc
                rol.estado = "ACTIVO"

        db.flush()

        # -------------------------------------------------------------
        # 3. Usuarios de Prueba
        # -------------------------------------------------------------
        print("\n[3/10] Poblando Usuarios de Acceso...")
        usuarios_seed = [
            {
                "correo": "admin@telemedicina.com",
                "password": "admin123",
                "nombres": "Administrador",
                "apellidos": "Central",
                "id_rol": 1,
                "id_clinica": 1,
                "telefono": "+591 70000001",
            },
            {
                "correo": "doctor@telemedicina.com",
                "password": "medico123",
                "nombres": "Dr. Roberto",
                "apellidos": "Gómez Flores",
                "id_rol": 2,
                "id_clinica": 1,
                "telefono": "+591 71111111",
            },
            {
                "correo": "medico.norte@telemedicina.com",
                "password": "medico123",
                "nombres": "Dra. Elena",
                "apellidos": "Ríos Vargas",
                "id_rol": 2,
                "id_clinica": 2,
                "telefono": "+591 71222222",
            },
            {
                "correo": "recepcion@telemedicina.com",
                "password": "recepcion123",
                "nombres": "Patricia",
                "apellidos": "Morales Sánchez",
                "id_rol": 3,
                "id_clinica": 1,
                "telefono": "+591 72333333",
            },
            # Usuario de Tipo Paciente Solicitado
            {
                "correo": "paciente@telemedicina.com",
                "password": "paciente123",
                "nombres": "Mateo",
                "apellidos": "Valdez Quiroga",
                "id_rol": 4,
                "id_clinica": 1,
                "telefono": "+591 76543210",
            },
            {
                "correo": "paciente.carlos@telemedicina.com",
                "password": "paciente123",
                "nombres": "Carlos",
                "apellidos": "Mamani Choque",
                "id_rol": 4,
                "id_clinica": 1,
                "telefono": "+591 76111222",
            },
            {
                "correo": "paciente.ana@telemedicina.com",
                "password": "paciente123",
                "nombres": "Ana",
                "apellidos": "Pérez Gutiérrez",
                "id_rol": 4,
                "id_clinica": 1,
                "telefono": "+591 76333444",
            },
            {
                "correo": "paciente.luis@telemedicina.com",
                "password": "paciente123",
                "nombres": "Luis",
                "apellidos": "Gómez Ardaya",
                "id_rol": 4,
                "id_clinica": 2,
                "telefono": "+591 76555666",
            },
        ]

        user_map = {}
        for u_data in usuarios_seed:
            user = db.query(Usuario).filter(Usuario.correo == u_data["correo"]).first()
            if not user:
                user = Usuario(
                    correo=u_data["correo"],
                    password_hash=hash_password(u_data["password"]),
                    nombres=u_data["nombres"],
                    apellidos=u_data["apellidos"],
                    id_rol=u_data["id_rol"],
                    id_clinica=u_data["id_clinica"],
                    telefono=u_data["telefono"],
                    estado="activo",
                )
                db.add(user)
                print(f"  [+] Creado Usuario: {u_data['correo']} (Rol: {u_data['id_rol']})")
            else:
                user.password_hash = hash_password(u_data["password"])
                user.nombres = u_data["nombres"]
                user.apellidos = u_data["apellidos"]
                user.id_rol = u_data["id_rol"]
                user.id_clinica = u_data["id_clinica"]
                user.telefono = u_data["telefono"]
                user.estado = "activo"
                print(f"  [=] Usuario actualizado: {u_data['correo']}")
            db.flush()
            user_map[u_data["correo"]] = user

        # -------------------------------------------------------------
        # 4. Pacientes Clínicos
        # -------------------------------------------------------------
        print("\n[4/10] Poblando Perfiles de Pacientes...")
        pacientes_seed = [
            {
                "id_usuario": user_map["paciente@telemedicina.com"].id_usuario,
                "nombres": "Mateo",
                "apellidos": "Valdez Quiroga",
                "ci": "8472910",
                "complemento": "",
                "fecha_nacimiento": date(1992, 5, 14),
                "genero": "M",
                "telefono": "+591 76543210",
                "correo": "paciente@telemedicina.com",
                "direccion": "Calle Los Pinos #124, Barrio Las Palmas",
                "ciudad": "Santa Cruz de la Sierra",
                "tipo_sangre": "O+",
                "alergias": "Penicilina, Sulfamidas",
                "antecedentes_patologicos": "Hipertensión arterial leve en seguimiento",
                "contacto_emergencia_nombre": "Lucía Valdez",
                "contacto_emergencia_telefono": "+591 71234567",
                "contacto_emergencia_parentesco": "Hermana",
                "seguro_medico": "Seguro Social Universitario",
                "numero_seguro": "SSU-8472910-A",
                "id_clinica": 1,
            },
            {
                "id_usuario": user_map["paciente.carlos@telemedicina.com"].id_usuario,
                "nombres": "Carlos",
                "apellidos": "Mamani Choque",
                "ci": "1111111",
                "complemento": "",
                "fecha_nacimiento": date(1985, 11, 20),
                "genero": "M",
                "telefono": "+591 76111222",
                "correo": "paciente.carlos@telemedicina.com",
                "direccion": "Av. Grigotá #567",
                "ciudad": "Santa Cruz de la Sierra",
                "tipo_sangre": "A+",
                "alergias": "Ninguna conocida",
                "antecedentes_patologicos": "Diabetes mellitus tipo 2 diagnosticada en 2021",
                "contacto_emergencia_nombre": "Rosa Choque",
                "contacto_emergencia_telefono": "+591 71112233",
                "contacto_emergencia_parentesco": "Esposa",
                "id_clinica": 1,
            },
            {
                "id_usuario": user_map["paciente.ana@telemedicina.com"].id_usuario,
                "nombres": "Ana",
                "apellidos": "Pérez Gutiérrez",
                "ci": "2222222",
                "complemento": "",
                "fecha_nacimiento": date(1998, 3, 8),
                "genero": "F",
                "telefono": "+591 76333444",
                "correo": "paciente.ana@telemedicina.com",
                "direccion": "Av. Santos Dumont #890",
                "ciudad": "Santa Cruz de la Sierra",
                "tipo_sangre": "B+",
                "alergias": "Polvo y ácaros",
                "antecedentes_patologicos": "Asma bronquial intermitente",
                "contacto_emergencia_nombre": "Mario Pérez",
                "contacto_emergencia_telefono": "+591 73334455",
                "contacto_emergencia_parentesco": "Padre",
                "id_clinica": 1,
            },
            {
                "id_usuario": None,
                "nombres": "Sofía",
                "apellidos": "Mendoza Roca",
                "ci": "4444444",
                "complemento": "",
                "fecha_nacimiento": date(2000, 7, 22),
                "genero": "F",
                "telefono": "+591 77444555",
                "correo": "sofia.mendoza@gmail.com",
                "direccion": "Calle Sucre #231",
                "ciudad": "Santa Cruz de la Sierra",
                "tipo_sangre": "O-",
                "id_clinica": 1,
            },
            {
                "id_usuario": None,
                "nombres": "Alejandro",
                "apellidos": "Torrez Vargas",
                "ci": "5555555",
                "complemento": "",
                "fecha_nacimiento": date(1978, 9, 12),
                "genero": "M",
                "telefono": "+591 77555666",
                "correo": "atorrez.vargas@gmail.com",
                "direccion": "Calle Arenales #112",
                "ciudad": "Santa Cruz de la Sierra",
                "tipo_sangre": "A-",
                "id_clinica": 1,
            },
        ]

        paciente_map = {}
        for p_data in pacientes_seed:
            pac = db.query(Paciente).filter(Paciente.ci == p_data["ci"]).first()
            if not pac:
                pac = Paciente(**p_data)
                db.add(pac)
                print(f"  [+] Creado Paciente: {p_data['nombres']} {p_data['apellidos']} (CI: {p_data['ci']})")
            else:
                for k, v in p_data.items():
                    setattr(pac, k, v)
                pac.estado = "ACTIVO"
                print(f"  [=] Paciente actualizado: {p_data['nombres']} {p_data['apellidos']} (CI: {p_data['ci']})")
            db.flush()
            paciente_map[p_data["ci"]] = pac

        # -------------------------------------------------------------
        # 5. Especialidades Médicas
        # -------------------------------------------------------------
        print("\n[5/10] Poblando Especialidades...")
        especialidades_seed = [
            ("Medicina General", "Atención primaria, triaje y medicina preventiva"),
            ("Cardiología", "Salud cardiovascular, hipertensión y electrocardiografía"),
            ("Pediatría", "Atención integral de neonatos, niños y adolescentes"),
            ("Dermatología", "Patologías cutáneas y cuidados dermatológicos"),
            ("Ginecología", "Salud de la mujer y obstetricia"),
            ("Traumatología", "Lesiones musculoesqueléticas y ortopedia"),
            ("Neurología", "Enfermedades del sistema nervioso central y periférico"),
            ("Oftalmología", "Salud visual y optometría clínica"),
        ]

        esp_map = {}
        for nombre, desc in especialidades_seed:
            esp = db.query(Especialidad).filter(Especialidad.nombre == nombre).first()
            if not esp:
                esp = Especialidad(nombre=nombre, descripcion=desc, estado="activo")
                db.add(esp)
                print(f"  [+] Especialidad creada: {nombre}")
            else:
                esp.descripcion = desc
                esp.estado = "activo"
            db.flush()
            esp_map[nombre] = esp

        # -------------------------------------------------------------
        # 6. Perfiles Médicos y Asignación de Especialidades
        # -------------------------------------------------------------
        print("\n[6/10] Configurando Perfiles Médicos...")
        doc_user = user_map["doctor@telemedicina.com"]
        medico_roberto = db.query(Medico).filter(Medico.id_usuario == doc_user.id_usuario).first()
        if not medico_roberto:
            medico_roberto = Medico(
                id_usuario=doc_user.id_usuario,
                matricula_profesional="MAT-10492",
                descripcion_profesional="Médico internista y cardiólogo preventivo con 12 años de trayectoria.",
                experiencia="Hospital San Juan de Dios (2014-actualidad), Clínica Central.",
                estado="activo",
            )
            db.add(medico_roberto)
            print("  [+] Creado perfil médico Dr. Roberto Gómez")
        else:
            medico_roberto.matricula_profesional = "MAT-10492"
            medico_roberto.descripcion_profesional = "Médico internista y cardiólogo preventivo con 12 años de trayectoria."
            medico_roberto.estado = "activo"
            print("  [=] Perfil médico Dr. Roberto Gómez actualizado")
        db.flush()

        # Asignar Cardiología (principal) y Medicina General
        for idx, esp_name in enumerate(["Cardiología", "Medicina General"]):
            esp = esp_map[esp_name]
            asoc = db.query(MedicoEspecialidad).filter(
                MedicoEspecialidad.id_medico == medico_roberto.id_medico,
                MedicoEspecialidad.id_especialidad == esp.id_especialidad,
            ).first()
            if not asoc:
                db.add(MedicoEspecialidad(
                    id_medico=medico_roberto.id_medico,
                    id_especialidad=esp.id_especialidad,
                    es_principal=(idx == 0)
                ))
            else:
                asoc.es_principal = (idx == 0)

        # Médico Norte (Dra. Elena)
        elena_user = user_map["medico.norte@telemedicina.com"]
        medico_elena = db.query(Medico).filter(Medico.id_usuario == elena_user.id_usuario).first()
        if not medico_elena:
            medico_elena = Medico(
                id_usuario=elena_user.id_usuario,
                matricula_profesional="MAT-20381",
                descripcion_profesional="Pediatra con especialidad en neonatología y desarrollo infantil.",
                experiencia="Hospital de Niños y Red Norte.",
                estado="activo",
            )
            db.add(medico_elena)
            print("  [+] Creado perfil médico Dra. Elena Ríos")
        else:
            medico_elena.matricula_profesional = "MAT-20381"
            medico_elena.estado = "activo"
        db.flush()

        # Asignar Pediatría (principal)
        esp_ped = esp_map["Pediatría"]
        asoc_ped = db.query(MedicoEspecialidad).filter(
            MedicoEspecialidad.id_medico == medico_elena.id_medico,
            MedicoEspecialidad.id_especialidad == esp_ped.id_especialidad,
        ).first()
        if not asoc_ped:
            db.add(MedicoEspecialidad(
                id_medico=medico_elena.id_medico,
                id_especialidad=esp_ped.id_especialidad,
                es_principal=True
            ))

        db.flush()

        # -------------------------------------------------------------
        # 7. Servicios Médicos y Horarios de Agenda (CU05)
        # -------------------------------------------------------------
        print("\n[7/10] Verificando Catálogo de Servicios y Horarios Médicos...")
        # Los servicios 1, 2 y 3 están definidos por el constraint fijo de CU05:
        # 1: 08:00-13:00, 30 min
        # 2: 13:00-16:00, 45 min
        # 3: 16:00-18:00, 60 min
        srv1 = db.query(ServicioMedico).filter(ServicioMedico.id_servicio == 1).first()
        if not srv1:
            srv1 = ServicioMedico(
                id_servicio=1,
                nombre="Consulta general",
                descripcion="Atención médica general y chequeo preventivo.",
                hora_inicio="08:00:00",
                hora_fin="13:00:00",
                duracion_minutos=30,
                costo=150.00,
                estado="activo",
            )
            db.add(srv1)
        
        srv2 = db.query(ServicioMedico).filter(ServicioMedico.id_servicio == 2).first()
        if not srv2:
            srv2 = ServicioMedico(
                id_servicio=2,
                nombre="Consulta especializada",
                descripcion="Atención médica especializada y teleconsulta.",
                hora_inicio="13:00:00",
                hora_fin="16:00:00",
                duracion_minutos=45,
                costo=220.00,
                estado="activo",
            )
            db.add(srv2)

        srv3 = db.query(ServicioMedico).filter(ServicioMedico.id_servicio == 3).first()
        if not srv3:
            srv3 = ServicioMedico(
                id_servicio=3,
                nombre="Evaluación médica",
                descripcion="Evaluación médica integral y control preventivo.",
                hora_inicio="16:00:00",
                hora_fin="18:00:00",
                duracion_minutos=60,
                costo=180.00,
                estado="activo",
            )
            db.add(srv3)

        db.flush()

        # Horarios para el Dr. Roberto Gómez (Lunes a Viernes)
        for dia in range(1, 6):
            hm = db.query(HorarioMedico).filter(
                HorarioMedico.id_medico == medico_roberto.id_medico,
                HorarioMedico.id_servicio == 1,
                HorarioMedico.dia_semana == dia,
            ).first()
            if not hm:
                db.add(HorarioMedico(
                    id_medico=medico_roberto.id_medico,
                    id_servicio=1,
                    dia_semana=dia,
                    estado="activo",
                ))

        # Teleconsulta (Lunes, Miércoles, Viernes)
        for dia in [1, 3, 5]:
            hm_tel = db.query(HorarioMedico).filter(
                HorarioMedico.id_medico == medico_roberto.id_medico,
                HorarioMedico.id_servicio == 2,
                HorarioMedico.dia_semana == dia,
            ).first()
            if not hm_tel:
                db.add(HorarioMedico(
                    id_medico=medico_roberto.id_medico,
                    id_servicio=2,
                    dia_semana=dia,
                    estado="activo",
                ))

        db.flush()

        # -------------------------------------------------------------
        # 8. Citas Médicas (CU25)
        # -------------------------------------------------------------
        print("\n[8/10] Poblando Citas Médicas de Demostración...")
        pac_mateo = paciente_map["8472910"]
        pac_carlos = paciente_map["1111111"]
        pac_ana = paciente_map["2222222"]

        citas_seed = [
            {
                "id_paciente": pac_mateo.id_paciente,
                "id_medico": medico_roberto.id_medico,
                "id_especialidad": esp_map["Cardiología"].id_especialidad,
                "id_servicio": 2,
                "fecha_cita": date.today() + timedelta(days=2),
                "hora_inicio": "15:00",
                "hora_fin": "15:45",
                "modalidad": "TELEMEDICINA",
                "motivo": "Control de palpitaciones y fatiga post-esfuerzo moderado",
                "estado": "CONFIRMADA",
                "tipo_consulta": "TELEMEDICINA",
                "notas": "Enviar enlace de sala virtual con 15 minutos de anticipación",
            },
            {
                "id_paciente": pac_mateo.id_paciente,
                "id_medico": medico_roberto.id_medico,
                "id_especialidad": esp_map["Medicina General"].id_especialidad,
                "id_servicio": 1,
                "fecha_cita": date.today() - timedelta(days=10),
                "hora_inicio": "09:00",
                "hora_fin": "09:30",
                "modalidad": "PRESENCIAL",
                "motivo": "Consulta inicial por cefalea recurrente y control de presión",
                "estado": "COMPLETADA",
                "tipo_consulta": "GENERAL",
                "notas": "Atención realizada sin incidencias",
            },
            {
                "id_paciente": pac_carlos.id_paciente,
                "id_medico": medico_roberto.id_medico,
                "id_especialidad": esp_map["Medicina General"].id_especialidad,
                "id_servicio": 1,
                "fecha_cita": date.today() + timedelta(days=1),
                "hora_inicio": "08:30",
                "hora_fin": "09:00",
                "modalidad": "PRESENCIAL",
                "motivo": "Revisión de glucemia basal y ajuste de dosis de metformina",
                "estado": "CONFIRMADA",
                "tipo_consulta": "GENERAL",
            },
            {
                "id_paciente": pac_ana.id_paciente,
                "id_medico": medico_roberto.id_medico,
                "id_especialidad": esp_map["Medicina General"].id_especialidad,
                "id_servicio": 1,
                "fecha_cita": date.today() + timedelta(days=3),
                "hora_inicio": "10:00",
                "hora_fin": "10:30",
                "modalidad": "PRESENCIAL",
                "motivo": "Molestias lumbares agudas tras levantamiento de peso",
                "estado": "PENDIENTE",
                "tipo_consulta": "GENERAL",
            }
        ]

        citas_creadas = []
        for c_data in citas_seed:
            existente = db.query(Cita).filter(
                Cita.id_paciente == c_data["id_paciente"],
                Cita.id_medico == c_data["id_medico"],
                Cita.fecha_cita == c_data["fecha_cita"],
                Cita.hora_inicio == c_data["hora_inicio"],
            ).first()
            if not existente:
                cita = Cita(**c_data)
                db.add(cita)
                citas_creadas.append(cita)
                print(f"  [+] Creada Cita para paciente {c_data['id_paciente']} el {c_data['fecha_cita']} {c_data['hora_inicio']}")
            else:
                for k, v in c_data.items():
                    setattr(existente, k, v)
                citas_creadas.append(existente)

        db.flush()

        # -------------------------------------------------------------
        # 9. Fichas Clínicas Dinámicas (CU09)
        # -------------------------------------------------------------
        print("\n[9/10] Generando Fichas Clínicas con Secciones Dinámicas...")
        fichas_seed = [
            {
                "correlativo": "FICH-20260901-0001",
                "id_clinica": 1,
                "id_paciente": pac_mateo.id_paciente,
                "id_medico": medico_roberto.id_medico,
                "id_servicio": 1,
                "id_especialidad": esp_map["Medicina General"].id_especialidad,
                "id_cita": citas_creadas[1].id_cita if len(citas_creadas) > 1 else None,
                "fecha_atencion": date.today() - timedelta(days=10),
                "hora_inicio": "09:00",
                "hora_fin": "09:30",
                "motivo_consulta": "Consulta inicial por cefalea recurrente y control de presión arterial",
                "signos_vitales": {
                    "presion_arterial": "135/88",
                    "frecuencia_cardiaca": 76,
                    "frecuencia_respiratoria": 16,
                    "temperatura": 36.5,
                    "saturacion_oxigeno": 98,
                    "peso_kg": 75.0,
                    "talla_cm": 175.0,
                    "imc": 24.49,
                },
                "secciones_dinamicas": {
                    "anamnesis": "Paciente refiere dolor holocraneal de 2 semanas de evolución agravado por jornadas laborales extensas.",
                    "examen_fisico": "Normocéfalo, sin signos meníngeos. Ruidos cardíacos regulares sin soplos.",
                    "plan_terapeutico": "Monitoreo ambulatorio de presión arterial por 7 días y dieta hiposódica.",
                },
                "codigo_cie10": "G44.2",
                "diagnostico_descripcion": "Cefalea tensional primaria",
                "notas_evolucion": "Buena tolerancia al tratamiento inicial. Se programa teleconsulta de seguimiento.",
                "estado": "FINALIZADA",
            },
            {
                "correlativo": "FICH-20260910-0001",
                "id_clinica": 1,
                "id_paciente": pac_mateo.id_paciente,
                "id_medico": medico_roberto.id_medico,
                "id_servicio": 2,
                "id_especialidad": esp_map["Cardiología"].id_especialidad,
                "id_cita": citas_creadas[0].id_cita if len(citas_creadas) > 0 else None,
                "fecha_atencion": date.today() + timedelta(days=2),
                "hora_inicio": "15:00",
                "hora_fin": "15:45",
                "motivo_consulta": "Teleconsulta de seguimiento por palpitaciones y fatiga post-esfuerzo moderado",
                "signos_vitales": {
                    "presion_arterial": "128/82",
                    "frecuencia_cardiaca": 72,
                    "frecuencia_respiratoria": 16,
                    "temperatura": 36.6,
                    "saturacion_oxigeno": 99,
                },
                "secciones_dinamicas": {
                    "modalidad": "Virtual Telemedicina",
                    "sala_videollamada": "https://meet.telemedicina.com/room-8472910",
                },
                "codigo_cie10": "R00.2",
                "diagnostico_descripcion": "Palpitaciones cardíacas en estudio",
                "estado": "EMITIDA",
            },
            {
                "correlativo": "FICH-20260910-0002",
                "id_clinica": 1,
                "id_paciente": pac_carlos.id_paciente,
                "id_medico": medico_roberto.id_medico,
                "id_servicio": 1,
                "id_especialidad": esp_map["Medicina General"].id_especialidad,
                "id_cita": citas_creadas[2].id_cita if len(citas_creadas) > 2 else None,
                "fecha_atencion": date.today() + timedelta(days=1),
                "hora_inicio": "08:30",
                "hora_fin": "09:00",
                "motivo_consulta": "Control periódico de diabetes y evaluación de glucemia",
                "signos_vitales": {
                    "presion_arterial": "130/84",
                    "frecuencia_cardiaca": 70,
                    "peso_kg": 81.0,
                    "talla_cm": 170.0,
                    "imc": 28.02,
                },
                "codigo_cie10": "E11.9",
                "diagnostico_descripcion": "Diabetes mellitus tipo 2 sin mención de complicación",
                "estado": "EMITIDA",
            },
        ]

        for f_data in fichas_seed:
            f_exist = db.query(FichaClinica).filter(
                FichaClinica.id_clinica == f_data["id_clinica"],
                FichaClinica.correlativo == f_data["correlativo"],
            ).first()
            if not f_exist:
                ficha = FichaClinica(
                    id_ficha=str(uuid.uuid4()),
                    **f_data
                )
                db.add(ficha)
                print(f"  [+] Creada Ficha Clínica {f_data['correlativo']} (Estado: {f_data['estado']})")
            else:
                for k, v in f_data.items():
                    setattr(f_exist, k, v)
                print(f"  [=] Ficha Clínica {f_data['correlativo']} actualizada")

        db.flush()

        # -------------------------------------------------------------
        # 10. HCE, Documentos Clínicos y Auditoría (CU28, CU12, CU21)
        # -------------------------------------------------------------
        print("\n[10/10] Generando Historia Clínica, Documentos Clínicos y Bitácora...")
        # Historia Clínica para Mateo Valdez
        hce_mateo = db.query(HistoriaClinica).filter(
            HistoriaClinica.id_clinica == 1,
            HistoriaClinica.id_paciente == pac_mateo.id_paciente,
        ).first()
        if not hce_mateo:
            hce_mateo = HistoriaClinica(
                id_clinica=1,
                id_paciente=pac_mateo.id_paciente,
                numero_historia="HCE-2026-0001",
                antecedentes_personales="Hipertensión arterial diagnosticada en 2024. Cefalea tensional ocasional.",
                antecedentes_familiares="Padre hipertenso, madre sin patologías relevantes.",
                alergias="Penicilina, Sulfas",
                habitos="No fuma, consumo de alcohol social moderado, caminata 30 min 3 veces por semana.",
                observaciones="Paciente colaborador con excelente adherencia terapéutica.",
            )
            db.add(hce_mateo)
            print("  [+] Creada Historia Clínica Electrónica para Mateo Valdez (HCE-2026-0001)")
            db.flush()

        # Documentos Clínicos (CU12) para Mateo Valdez
        docs_seed = [
            {
                "id_clinica": 1,
                "id_paciente": pac_mateo.id_paciente,
                "tipo_documento": "RECETA",
                "titulo": "Receta Médica - Losartán Potásico 50mg",
                "descripcion": "Tratamiento antihipertensivo oral. Tomar 1 tableta cada mañana con agua.",
                "archivo_url": "/api/v1/documentos/download/receta-losartan-8472910.pdf",
                "hash_archivo": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                "firmado_por": medico_roberto.id_usuario,
                "fecha_documento": date.today() - timedelta(days=10),
                "metadatos": {
                    "medicamento": "Losartán Potásico",
                    "presentacion": "Comprimidos 50mg",
                    "cantidad": "30 comprimidos",
                    "indicaciones": "1 tableta cada 24 horas por la mañana durante 30 días",
                },
                "estado": "ACTIVO",
            },
            {
                "id_clinica": 1,
                "id_paciente": pac_mateo.id_paciente,
                "tipo_documento": "CERTIFICADO",
                "titulo": "Certificado Médico de Aptitud Física Cardiovascular",
                "descripcion": "Certifica aptitud médica para realización de actividades deportivas recreativas.",
                "archivo_url": "/api/v1/documentos/download/certificado-aptitud-8472910.pdf",
                "hash_archivo": "d41d8cd98f00b204e9800998ecf8427e00000000000000000000000000000000",
                "firmado_por": medico_roberto.id_usuario,
                "fecha_documento": date.today() - timedelta(days=5),
                "metadatos": {
                    "vigencia_meses": 6,
                    "actividad": "Deportes recreativos y gimnasio",
                    "observacion": "Apto sin restricciones cardiorrespiratorias",
                },
                "estado": "ACTIVO",
            },
            {
                "id_clinica": 1,
                "id_paciente": pac_mateo.id_paciente,
                "tipo_documento": "ORDEN_LAB",
                "titulo": "Orden de Laboratorio - Perfil Lipídico y Hemograma",
                "descripcion": "Exámenes de control: Colesterol Total, HDL, LDL, Triglicéridos, Glucemia y Hemograma.",
                "archivo_url": "/api/v1/documentos/download/orden-laboratorio-8472910.pdf",
                "hash_archivo": "4b227777d4dd1fc61c6f884f48641d02b4d121d3fd328cb08b5531fcacdabf8a",
                "firmado_por": medico_roberto.id_usuario,
                "fecha_documento": date.today() - timedelta(days=2),
                "metadatos": {
                    "laboratorio": "Laboratorio Clínico Central",
                    "ayuno_horas": 12,
                },
                "estado": "ACTIVO",
            },
        ]

        for doc_data in docs_seed:
            doc_exist = db.query(DocumentoClinico).filter(
                DocumentoClinico.id_clinica == doc_data["id_clinica"],
                DocumentoClinico.id_paciente == doc_data["id_paciente"],
                DocumentoClinico.titulo == doc_data["titulo"],
            ).first()
            if not doc_exist:
                doc = DocumentoClinico(**doc_data)
                db.add(doc)
                print(f"  [+] Creado Documento Clínico: {doc_data['titulo']} ({doc_data['tipo_documento']})")
            else:
                for k, v in doc_data.items():
                    setattr(doc_exist, k, v)

        # Bitácora de Auditoría (CU21)
        audit_events = [
            ("LOGIN", "usuarios", user_map["admin@telemedicina.com"].id_usuario, "Inicio de sesión administrativo exitoso"),
            ("CREATE", "fichas_clinicas", user_map["recepcion@telemedicina.com"].id_usuario, "Emisión de Ficha Clínica FICH-20260910-0001"),
            ("CREATE", "citas", user_map["paciente@telemedicina.com"].id_usuario, "Reserva de cita médica virtual"),
            ("UPDATE", "historias_clinicas", user_map["doctor@telemedicina.com"].id_usuario, "Actualización de antecedentes en HCE-2026-0001"),
        ]

        for accion, tabla, uid, desc in audit_events:
            db.add(Auditoria(
                id_clinica=1,
                id_usuario=uid,
                tabla_afectada=tabla,
                registro_id=1,
                accion=accion,
                descripcion=desc,
                datos_anteriores={},
                datos_nuevos={},
                direccion_ip="190.186.20.45",
                fecha_hora=datetime.now(timezone.utc),
            ))

        db.commit()
        print("\n==================================================================")
        print("  SEMBRADO DE DATOS DEMO FINALIZADO CON ÉXITO                    ")
        print("==================================================================")

    except Exception as e:
        db.rollback()
        print(f"\n[!] ERROR EN EL SEMBRADO: {e}")
        raise e
    finally:
        db.close()


if __name__ == "__main__":
    seed_all()
