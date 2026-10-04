import os
import sys
import uuid
import hashlib
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

# Agregar directorio raíz al PYTHONPATH
sys.path.insert(0, os.path.realpath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import func
from sqlalchemy.orm import Session
from app.core.database import SessionLocal, engine
from app.core.security import hash_password
from app.modules.auth.models import Clinica, Rol, Usuario, Auditoria, Permiso, RolPermiso
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
from app.modules.communications.models import MensajeChatCita


def _pdf_placeholder_bytes(titulo: str, lineas: list | None = None) -> bytes:
    """PDF demo con cabecera + datos del documento (no es un clínico real).

    NOTA: documento ilustrativo para demo/seed. El documento formal se genera
    desde la API autenticada cuando el médico lo emite.
    """
    def _esc(texto: str) -> str:
        return texto.replace("\\", "").replace("(", "[").replace(")", "]")

    y = 720
    ops = [f"BT /F1 18 Tf 72 {y} Td ({_esc(titulo)}) Tj ET"]
    y -= 30
    for linea in (lineas or []):
        ops.append(f"BT /F1 11 Tf 72 {y} Td ({_esc(linea)}) Tj ET")
        y -= 18
    stream = "\n".join(ops).encode("latin-1", "replace")
    return (
        b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R"
        b"/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
        b"4 0 obj<</Length " + str(len(stream)).encode() + b">>stream\n" + stream +
        b"\nendstream\nendobj\n"
        b"5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\n"
        b"trailer<</Root 1 0 R>>\n%%EOF"
    )


def _ensure_seed_pdf(slug: str, titulo: str, lineas: list | None = None) -> tuple:
    """Crea (si falta) el PDF demo en storage_documents/seed y devuelve (key, sha256)."""
    base = Path(__file__).resolve().parent.parent / "storage_documents" / "seed"
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"{slug}.pdf"
    if not path.is_file():
        path.write_bytes(_pdf_placeholder_bytes(titulo, lineas))
    contenido = path.read_bytes()
    return f"seed/{slug}.pdf", hashlib.sha256(contenido).hexdigest()


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
                razon_social="Clínica Central San Juan de Dios S.R.L.",
                nit="1020304050",
                telefono="+591 33450001",
                correo="contacto@clinicacentral.com",
                direccion="Av. Cañoto esq. México #450, Santa Cruz",
                estado="ACTIVO",
            )
            db.add(c1)
            print("  [+] Creada Clínica Central (id_clinica=1)")
        else:
            c1.nombre = "Clínica Central San Juan de Dios"
            if not c1.razon_social:
                c1.razon_social = "Clínica Central San Juan de Dios S.R.L."
            if not c1.nit:
                c1.nit = "1020304050"
            if not c1.telefono:
                c1.telefono = "+591 33450001"
            if not c1.correo:
                c1.correo = "contacto@clinicacentral.com"
            c1.direccion = "Av. Cañoto esq. México #450, Santa Cruz"
            c1.estado = "ACTIVO"
            print("  [=] Clínica Central actualizada")

        c2 = db.query(Clinica).filter(Clinica.id_clinica == 2).first()
        if not c2:
            c2 = Clinica(
                id_clinica=2,
                nombre="Red Médica del Norte",
                razon_social="Red Médica del Norte S.R.L.",
                nit="1020304060",
                telefono="+591 33450002",
                correo="contacto@redmedicanorte.com",
                direccion="Av. Banzer Km 5.5 #120, Santa Cruz",
                estado="ACTIVO",
            )
            db.add(c2)
            print("  [+] Creada Clínica Norte (id_clinica=2)")
        else:
            c2.nombre = "Red Médica del Norte"
            if not c2.razon_social:
                c2.razon_social = "Red Médica del Norte S.R.L."
            if not c2.nit:
                c2.nit = "1020304060"
            if not c2.telefono:
                c2.telefono = "+591 33450002"
            if not c2.correo:
                c2.correo = "contacto@redmedicanorte.com"
            c2.direccion = "Av. Banzer Km 5.5 #120, Santa Cruz"
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

        # Rol global Super Administrador (SaaS, id_clinica=None). Upsert por
        # (lower(nombre), id_clinica IS NULL) para no colisionar con la
        # migración 010 ni con roles de tenant. No se toca en el loop de ids.
        rol_super = db.query(Rol).filter(
            func.lower(Rol.nombre) == func.lower("Super Administrador"),
            Rol.id_clinica.is_(None),
        ).first()
        if not rol_super:
            rol_super = Rol(
                id_clinica=None,
                nombre="Super Administrador",
                descripcion="Acceso total y administración de la plataforma SaaS",
                estado="ACTIVO",
            )
            db.add(rol_super)
            print("  [+] Creado Rol Super Administrador (global)")
        else:
            rol_super.descripcion = "Acceso total y administración de la plataforma SaaS"
            rol_super.estado = "ACTIVO"
            print("  [=] Rol Super Administrador verificado")
        db.flush()

        # -------------------------------------------------------------
        # 2b. Permisos y asignación Rol -> Permisos (CU26)
        # -------------------------------------------------------------
        print("\n[2b/10] Verificando Permisos del Sistema...")
        seed_permisos = [
            ("users", "read", "VER_USUARIOS", "Ver usuarios"),
            ("users", "write", "EDITAR_USUARIOS", "Crear y editar usuarios"),
            ("roles", "read", "VER_ROLES", "Ver roles y sus permisos"),
            ("roles", "write", "EDITAR_ROLES", "Crear roles y asignar permisos"),
            ("appointments", "read", "VER_CITAS", "Ver citas"),
            ("appointments", "write", "EDITAR_CITAS", "Crear, reprogramar y cancelar citas"),
            ("medical_records", "read", "VER_HISTORIAS", "Ver historias clínicas"),
            ("medical_records", "write", "EDITAR_HISTORIAS", "Crear y editar historias clínicas"),
            ("patients", "read", "VER_PACIENTES", "Ver pacientes"),
            ("patients", "write", "EDITAR_PACIENTES", "Crear y editar pacientes"),
            ("specialties", "read", "VER_ESPECIALIDADES", "Ver especialidades médicas"),
            ("analytics", "read", "VER_REPORTES", "Ver reportes y analítica"),
        ]
        permiso_map = {}
        for modulo, accion, nombre, desc in seed_permisos:
            perm = db.query(Permiso).filter(
                Permiso.modulo == modulo, Permiso.accion == accion
            ).first()
            if not perm:
                perm = Permiso(
                    nombre=nombre, descripcion=desc,
                    modulo=modulo, accion=accion, estado="ACTIVO",
                )
                db.add(perm)
                db.flush()
            permiso_map[f"{modulo}.{accion}"] = perm

        # Todos los códigos para roles administradores (global y de tenant).
        todos = list(permiso_map.keys())
        seed_rol_permisos = {
            "Super Administrador": todos,
            "ADMIN": todos,
            "MEDICO": [
                "appointments.read", "appointments.write",
                "medical_records.read", "medical_records.write",
                "patients.read", "specialties.read",
            ],
            "RECEPCION": [
                "appointments.read", "appointments.write",
                "patients.read", "patients.write", "users.read",
            ],
            "PACIENTE": ["appointments.read", "medical_records.read"],
        }
        for rol_nombre, codigos in seed_rol_permisos.items():
            rol = db.query(Rol).filter(Rol.nombre == rol_nombre).first()
            # Super Administrador es global; el resto son los canónicos (id 1-4).
            if rol_nombre == "Super Administrador":
                rol = rol_super
            if not rol:
                continue
            for codigo in codigos:
                perm = permiso_map.get(codigo)
                if not perm:
                    continue
                ya = db.query(RolPermiso).filter(
                    RolPermiso.id_rol == rol.id_rol,
                    RolPermiso.id_permiso == perm.id_permiso,
                ).first()
                if not ya:
                    db.add(RolPermiso(id_rol=rol.id_rol, id_permiso=perm.id_permiso))
        db.flush()
        print("  [=] Permisos y asignaciones verificados")

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
                "correo": "admin.norte@telemedicina.com",
                "password": "admin123",
                "nombres": "Administrador",
                "apellidos": "Norte",
                "id_rol": 1,
                "id_clinica": 2,
                "telefono": "+591 70000002",
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
            # Super Administrador global SaaS (sin clínica)
            {
                "correo": "superadmin@telemedicina.com",
                "password": "superadmin123",
                "nombres": "Super",
                "apellidos": "Admin SaaS",
                "id_rol": None,
                "rol_nombre": "Super Administrador",
                "id_clinica": None,
                "telefono": "+591 70000000",
            },
        ]

        user_map = {}
        for u_data in usuarios_seed:
            # Resolver rol por nombre (caso Super Administrador global).
            id_rol = u_data["id_rol"]
            if id_rol is None and u_data.get("rol_nombre"):
                rol_obj = db.query(Rol).filter(
                    func.lower(Rol.nombre) == func.lower(u_data["rol_nombre"]),
                    Rol.id_clinica.is_(None),
                ).first()
                id_rol = rol_obj.id_rol if rol_obj else None
            user = db.query(Usuario).filter(Usuario.correo == u_data["correo"]).first()
            if not user:
                user = Usuario(
                    correo=u_data["correo"],
                    password_hash=hash_password(u_data["password"]),
                    nombres=u_data["nombres"],
                    apellidos=u_data["apellidos"],
                    id_rol=id_rol,
                    id_clinica=u_data["id_clinica"],
                    telefono=u_data["telefono"],
                    estado="activo",
                )
                db.add(user)
                print(f"  [+] Creado Usuario: {u_data['correo']} (Rol: {id_rol})")
            else:
                user.password_hash = hash_password(u_data["password"])
                user.nombres = u_data["nombres"]
                user.apellidos = u_data["apellidos"]
                user.id_rol = id_rol
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
            # --- Tenant 2: Red Médica del Norte (demo de aislamiento) ---
            {
                "id_usuario": user_map["paciente.luis@telemedicina.com"].id_usuario,
                "nombres": "Luis",
                "apellidos": "Gómez Ardaya",
                "ci": "6666666",
                "complemento": "",
                "fecha_nacimiento": date(1990, 12, 3),
                "genero": "M",
                "telefono": "+591 76555666",
                "correo": "paciente.luis@telemedicina.com",
                "direccion": "Av. Banzer Km 6 #210",
                "ciudad": "Santa Cruz de la Sierra",
                "tipo_sangre": "O+",
                "alergias": "Ninguna conocida",
                "antecedentes_patologicos": "Rinitis alérgica estacional",
                "contacto_emergencia_nombre": "Carmen Ardaya",
                "contacto_emergencia_telefono": "+591 76666777",
                "contacto_emergencia_parentesco": "Madre",
                "id_clinica": 2,
            },
            {
                "id_usuario": None,
                "nombres": "Paola",
                "apellidos": "Justiniano Ribera",
                "ci": "7777777",
                "complemento": "",
                "fecha_nacimiento": date(2015, 4, 18),
                "genero": "F",
                "telefono": "+591 77666777",
                "correo": "paola.justiniano@gmail.com",
                "direccion": "Calle Warnes #88",
                "ciudad": "Santa Cruz de la Sierra",
                "tipo_sangre": "A+",
                "id_clinica": 2,
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
                id_clinica=1,
                matricula_profesional="MAT-10492",
                descripcion_profesional="Médico internista y cardiólogo preventivo con 12 años de trayectoria.",
                experiencia="Hospital San Juan de Dios (2014-actualidad), Clínica Central.",
                estado="activo",
            )
            db.add(medico_roberto)
            print("  [+] Creado perfil médico Dr. Roberto Gómez")
        else:
            medico_roberto.id_clinica = 1
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
                id_clinica=2,
                matricula_profesional="MAT-20381",
                descripcion_profesional="Pediatra con especialidad en neonatología y desarrollo infantil.",
                experiencia="Hospital de Niños y Red Norte.",
                estado="activo",
            )
            db.add(medico_elena)
            print("  [+] Creado perfil médico Dra. Elena Ríos")
        else:
            medico_elena.id_clinica = 2
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
                "id_clinica": 1,
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
                "id_clinica": 1,
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
                "id_clinica": 1,
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
                "id_clinica": 1,
                "fecha_cita": date.today() + timedelta(days=3),
                "hora_inicio": "10:00",
                "hora_fin": "10:30",
                "modalidad": "PRESENCIAL",
                "motivo": "Molestias lumbares agudas tras levantamiento de peso",
                "estado": "PENDIENTE",
                "tipo_consulta": "GENERAL",
            },
            # --- Tenant 2: Dra. Elena + pacientes del Norte ---
            {
                "id_paciente": paciente_map["6666666"].id_paciente,
                "id_medico": medico_elena.id_medico,
                "id_especialidad": esp_map["Pediatría"].id_especialidad,
                "id_servicio": 2,
                "id_clinica": 2,
                "fecha_cita": date.today() + timedelta(days=2),
                "hora_inicio": "14:00",
                "hora_fin": "14:45",
                "modalidad": "TELEMEDICINA",
                "motivo": "Control de rinitis alérgica y revisión de tratamiento",
                "estado": "CONFIRMADA",
                "tipo_consulta": "TELEMEDICINA",
                "notas": "Enviar enlace de sala virtual con 15 minutos de anticipación",
            },
            {
                "id_paciente": paciente_map["7777777"].id_paciente,
                "id_medico": medico_elena.id_medico,
                "id_especialidad": esp_map["Pediatría"].id_especialidad,
                "id_servicio": 1,
                "id_clinica": 2,
                "fecha_cita": date.today() + timedelta(days=4),
                "hora_inicio": "09:00",
                "hora_fin": "09:30",
                "modalidad": "PRESENCIAL",
                "motivo": "Control de niño sano y esquema de vacunación",
                "estado": "PENDIENTE",
                "tipo_consulta": "GENERAL",
            },
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
            # --- Tenant 2: ficha de teleconsulta (Dra. Elena / Luis) ---
            {
                "correlativo": "FICH-20260910-0003",
                "id_clinica": 2,
                "id_paciente": paciente_map["6666666"].id_paciente,
                "id_medico": medico_elena.id_medico,
                "id_servicio": 2,
                "id_especialidad": esp_map["Pediatría"].id_especialidad,
                "id_cita": citas_creadas[4].id_cita if len(citas_creadas) > 4 else None,
                "fecha_atencion": date.today() + timedelta(days=2),
                "hora_inicio": "14:00",
                "hora_fin": "14:45",
                "motivo_consulta": "Teleconsulta de seguimiento por rinitis alérgica estacional",
                "signos_vitales": {
                    "presion_arterial": "118/76",
                    "frecuencia_cardiaca": 68,
                    "frecuencia_respiratoria": 15,
                    "temperatura": 36.4,
                    "saturacion_oxigeno": 99,
                },
                "secciones_dinamicas": {
                    "modalidad": "Virtual Telemedicina",
                    "sala_videollamada": "https://meet.telemedicina.com/room-6666666",
                },
                "codigo_cie10": "J30.2",
                "diagnostico_descripcion": "Rinitis alérgica estacional",
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

        # Documentos Clínicos (CU12) para Mateo Valdez.
        # archivo_url es CLAVE de storage (storage_documents/<key>), no ruta web.
        _pdf_receta = _ensure_seed_pdf(
            "receta-losartan-8472910", "Receta Medica - Losartan Potasico 50mg", [
                "Paciente: Mateo Valdez Quiroga (CI 8472910)",
                "Medico: Dr. Roberto Gomez Flores - Mat. MAT-10492",
                "Indicacion: 1 tableta cada 24 horas por la manana, 30 dias",
                "Presentacion: Comprimidos 50mg - Cantidad: 30",
            ])
        _pdf_cert = _ensure_seed_pdf(
            "certificado-aptitud-8472910", "Certificado Medico de Aptitud Fisica", [
                "Paciente: Mateo Valdez Quiroga (CI 8472910)",
                "Medico: Dr. Roberto Gomez Flores - Mat. MAT-10492",
                "Vigencia: 6 meses - Deportes recreativos y gimnasio",
                "Observacion: Apto sin restricciones cardiorrespiratorias",
            ])
        _pdf_lab1 = _ensure_seed_pdf(
            "orden-laboratorio-8472910", "Orden de Laboratorio - Perfil Lipidico", [
                "Paciente: Mateo Valdez Quiroga (CI 8472910)",
                "Medico: Dr. Roberto Gomez Flores - Mat. MAT-10492",
                "Examenes: Colesterol Total, HDL, LDL, Trigliceridos, Glucemia, Hemograma",
                "Laboratorio: Laboratorio Clinico Central - Ayuno: 12 horas",
            ])
        _pdf_lab2 = _ensure_seed_pdf(
            "orden-laboratorio-6666666", "Orden de Laboratorio - Hemograma", [
                "Paciente: Luis Gomez Ardaya (CI 6666666)",
                "Medico: Dra. Elena Rios Vargas - Mat. MAT-20381",
                "Examenes: Hemograma completo e IgE total",
                "Laboratorio: Laboratorio Red Norte - Ayuno: 8 horas",
            ])
        docs_seed = [
            {
                "id_clinica": 1,
                "id_paciente": pac_mateo.id_paciente,
                "tipo_documento": "RECETA",
                "titulo": "Receta Médica - Losartán Potásico 50mg",
                "descripcion": "Tratamiento antihipertensivo oral. Tomar 1 tableta cada mañana con agua.",
                "archivo_url": _pdf_receta[0],
                "hash_archivo": _pdf_receta[1],
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
                "archivo_url": _pdf_cert[0],
                "hash_archivo": _pdf_cert[1],
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
                "archivo_url": _pdf_lab1[0],
                "hash_archivo": _pdf_lab1[1],
                "firmado_por": medico_roberto.id_usuario,
                "fecha_documento": date.today() - timedelta(days=2),
                "metadatos": {
                    "laboratorio": "Laboratorio Clínico Central",
                    "ayuno_horas": 12,
                },
                "estado": "ACTIVO",
            },
            # --- Tenant 2: orden de laboratorio (Dra. Elena / Luis) ---
            {
                "id_clinica": 2,
                "id_paciente": paciente_map["6666666"].id_paciente,
                "tipo_documento": "ORDEN_LAB",
                "titulo": "Orden de Laboratorio - Hemograma y Pruebas de Alergia",
                "descripcion": "Exámenes de control: Hemograma completo e IgE total.",
                "archivo_url": _pdf_lab2[0],
                "hash_archivo": _pdf_lab2[1],
                "firmado_por": medico_elena.id_usuario,
                "fecha_documento": date.today() - timedelta(days=1),
                "metadatos": {
                    "laboratorio": "Laboratorio Red Norte",
                    "ayuno_horas": 8,
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
        db.flush()

        # Chat de teleconsulta (CU15): mensajes en la cita virtual de Mateo.
        print("\n[10b/10] Generando mensajes de chat de teleconsulta (CU15)...")
        cita_virtual = citas_creadas[0] if len(citas_creadas) > 0 else None
        if cita_virtual is not None and cita_virtual.id_cita is not None:
            chat_seed = [
                (
                    user_map["paciente@telemedicina.com"].id_usuario,
                    "PACIENTE",
                    "Buenos días doctor, desde ayer siento palpitaciones al subir las gradas.",
                ),
                (
                    doc_user.id_usuario,
                    "MEDICO",
                    "Buenos días Mateo, ¿las palpitaciones vienen con mareo o dolor en el pecho?",
                ),
                (
                    user_map["paciente@telemedicina.com"].id_usuario,
                    "PACIENTE",
                    "Solo fatiga leve, sin dolor. Tomé la presión y estaba en 128/82.",
                ),
            ]
            for id_rem, rol_rem, texto in chat_seed:
                ya = db.query(MensajeChatCita).filter(
                    MensajeChatCita.id_cita == cita_virtual.id_cita,
                    MensajeChatCita.id_remitente == id_rem,
                    MensajeChatCita.contenido == texto,
                ).first()
                if not ya:
                    db.add(MensajeChatCita(
                        id_clinica=1,
                        id_cita=cita_virtual.id_cita,
                        id_remitente=id_rem,
                        rol_remitente=rol_rem,
                        contenido=texto,
                        leido=True,
                    ))
                    print(f"  [+] Mensaje de chat ({rol_rem}): {texto[:45]}...")
        db.flush()

        # Fila virtual de hoy (CU08): citas PENDIENTE/CONFIRMADA con
        # fecha_cita = hoy para probar la cola en vivo. Idempotente por
        # (paciente, médico, fecha, hora): si existen se resetean a su estado
        # demo (las pausas/notificaciones se generan en vivo desde la API).
        print("\n[10c/10] Generando fila virtual de hoy (CU08)...")
        hoy = date.today()
        cola_seed = [
            {
                "id_paciente": pac_ana.id_paciente,
                "id_medico": medico_roberto.id_medico,
                "id_especialidad": esp_map["Medicina General"].id_especialidad,
                "id_servicio": 1,
                "id_clinica": 1,
                "fecha_cita": hoy,
                "hora_inicio": "09:00",
                "hora_fin": "09:30",
                "modalidad": "PRESENCIAL",
                "motivo": "Control de presión arterial en fila virtual demo",
                "estado": "PENDIENTE",
                "tipo_consulta": "GENERAL",
            },
            {
                "id_paciente": pac_mateo.id_paciente,
                "id_medico": medico_roberto.id_medico,
                "id_especialidad": esp_map["Medicina General"].id_especialidad,
                "id_servicio": 1,
                "id_clinica": 1,
                "fecha_cita": hoy,
                "hora_inicio": "09:20",
                "hora_fin": "09:50",
                "modalidad": "PRESENCIAL",
                "motivo": "Seguimiento de hipertensión en fila virtual demo",
                "estado": "PENDIENTE",
                "tipo_consulta": "GENERAL",
            },
            {
                "id_paciente": pac_carlos.id_paciente,
                "id_medico": medico_roberto.id_medico,
                "id_especialidad": esp_map["Medicina General"].id_especialidad,
                "id_servicio": 1,
                "id_clinica": 1,
                "fecha_cita": hoy,
                "hora_inicio": "09:40",
                "hora_fin": "10:10",
                "modalidad": "PRESENCIAL",
                "motivo": "Control de glucemia en fila virtual demo",
                "estado": "CONFIRMADA",
                "tipo_consulta": "GENERAL",
            },
            # --- Tenant 2: Dra. Elena + Luis (demo de aislamiento) ---
            {
                "id_paciente": paciente_map["6666666"].id_paciente,
                "id_medico": medico_elena.id_medico,
                "id_especialidad": esp_map["Pediatría"].id_especialidad,
                "id_servicio": 1,
                "id_clinica": 2,
                "fecha_cita": hoy,
                "hora_inicio": "09:15",
                "hora_fin": "09:45",
                "modalidad": "PRESENCIAL",
                "motivo": "Control pediátrico en fila virtual demo",
                "estado": "PENDIENTE",
                "tipo_consulta": "GENERAL",
            },
        ]

        for c_data in cola_seed:
            existente = db.query(Cita).filter(
                Cita.id_paciente == c_data["id_paciente"],
                Cita.id_medico == c_data["id_medico"],
                Cita.fecha_cita == c_data["fecha_cita"],
                Cita.hora_inicio == c_data["hora_inicio"],
            ).first()
            if not existente:
                db.add(Cita(**c_data))
                print(f"  [+] Creada Cita CU08 para paciente {c_data['id_paciente']} hoy {c_data['hora_inicio']}")
            else:
                for k, v in c_data.items():
                    setattr(existente, k, v)
                existente.check_in = None
                print(f"  [=] Cita CU08 reseteada para paciente {c_data['id_paciente']} hoy {c_data['hora_inicio']}")
        db.flush()

        # NOTA CU16: no se siembran recetas firmadas. Receta exige
        # id_consulta FK + firma Ed25519 válida (firma_digital/key_id/hash_pdf
        # NOT NULL verificables contra PRESCRIPTION_* del .env). Sembrar firmas
        # dummy rompería la verificación pública; generarlas aquí acoplaría el
        # seed al anillo de claves. Crear recetas demo desde la API autenticada.

        # Bitácora de Auditoría (CU21)
        # NOTA: auditoria.id_clinica es NOT NULL en este backend, por eso no
        # hay eventos globales (id_clinica=None) como en Sprint 1. El evento
        # del superadmin se registra bajo la clínica 1 (plataforma).
        audit_events = [
            ("LOGIN", "usuarios", user_map["admin@telemedicina.com"].id_usuario, "Inicio de sesión administrativo exitoso"),
            ("CREATE", "fichas_clinicas", user_map["recepcion@telemedicina.com"].id_usuario, "Emisión de Ficha Clínica FICH-20260910-0001"),
            ("CREATE", "citas", user_map["paciente@telemedicina.com"].id_usuario, "Reserva de cita médica virtual"),
            ("UPDATE", "historias_clinicas", user_map["doctor@telemedicina.com"].id_usuario, "Actualización de antecedentes en HCE-2026-0001"),
            ("CREATE", "clinicas", user_map["superadmin@telemedicina.com"].id_usuario, "Alta de la Red Médica del Norte como tenant SaaS"),
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
