import sys
import os
from datetime import date, datetime

# Asegurar que la raíz del proyecto esté en el PYTHONPATH
sys.path.insert(0, os.path.realpath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import func, text

from app.core.database import SessionLocal
from app.core.security import hash_password, verify_password
from app.modules.auth.models import Auditoria, Clinica, Permiso, Rol, RolPermiso, Usuario
from app.modules.appointments.models import Especialidad, Medico, MedicoEspecialidad
from app.modules.medical_records.models import Paciente

# ── 1. Clínicas Iniciales ──────────────────────────────────────────────────
SEED_CLINICAS = [
    {
        "id_clinica": 1,
        "nombre": "Hospital San Juan de Dios",
        "razon_social": "Hospital San Juan de Dios S.A.",
        "nit": "1020304050",
        "telefono": "+591 3 3344556",
        "correo": "contacto@sanjuandedios.com",
        "direccion": "Av. Cañoto esq. Rafael Peña, Santa Cruz",
        "estado": "ACTIVO",
    },
    {
        "id_clinica": 2,
        "nombre": "Centro Médico Santa María",
        "razon_social": "Santa María Salud S.R.L.",
        "nit": "2030405060",
        "telefono": "+591 2 2445566",
        "correo": "contacto@santamaria.com",
        "direccion": "Av. 6 de Agosto #123, La Paz",
        "estado": "ACTIVO",
    },
]

# ── 2. Roles Base del Sistema (CU26) ──────────────────────────────────────
# id_clinica=None => roles globales del SaaS
SEED_ROLES = [
    {"nombre": "Super Administrador", "descripcion": "Acceso total y administración de la plataforma SaaS", "estado": "ACTIVO"},
    {"nombre": "Administrador", "descripcion": "Acceso total al sistema y gestión de usuarios/roles de la clínica", "estado": "ACTIVO"},
    {"nombre": "Médico", "descripcion": "Gestión de citas, consultas e historias clínicas", "estado": "ACTIVO"},
    {"nombre": "Recepción", "descripcion": "Gestión de agenda de citas y registro de pacientes", "estado": "ACTIVO"},
    {"nombre": "Paciente", "descripcion": "Acceso autogestionado del paciente", "estado": "ACTIVO"},
]

# ── 3. Catálogo Base de Permisos (CU26) ──────────────────────────────────
PERMISO_ESTADO_ACTIVO = "ACTIVO"
SEED_PERMISOS = [
    {"codigo": "users.read", "modulo": "users", "accion": "read", "nombre": "VER_USUARIOS", "descripcion": "Ver usuarios", "estado": PERMISO_ESTADO_ACTIVO},
    {"codigo": "users.write", "modulo": "users", "accion": "write", "nombre": "EDITAR_USUARIOS", "descripcion": "Crear y editar usuarios", "estado": PERMISO_ESTADO_ACTIVO},
    {"codigo": "roles.read", "modulo": "roles", "accion": "read", "nombre": "VER_ROLES", "descripcion": "Ver roles y sus permisos", "estado": PERMISO_ESTADO_ACTIVO},
    {"codigo": "roles.write", "modulo": "roles", "accion": "write", "nombre": "EDITAR_ROLES", "descripcion": "Crear roles y asignar permisos", "estado": PERMISO_ESTADO_ACTIVO},
    {"codigo": "appointments.read", "modulo": "appointments", "accion": "read", "nombre": "VER_CITAS", "descripcion": "Ver citas", "estado": PERMISO_ESTADO_ACTIVO},
    {"codigo": "appointments.write", "modulo": "appointments", "accion": "write", "nombre": "EDITAR_CITAS", "descripcion": "Crear, reprogramar y cancelar citas", "estado": PERMISO_ESTADO_ACTIVO},
    {"codigo": "medical_records.read", "modulo": "medical_records", "accion": "read", "nombre": "VER_HISTORIAS", "descripcion": "Ver historias clínicas", "estado": PERMISO_ESTADO_ACTIVO},
    {"codigo": "medical_records.write", "modulo": "medical_records", "accion": "write", "nombre": "EDITAR_HISTORIAS", "descripcion": "Crear y editar historias clínicas", "estado": PERMISO_ESTADO_ACTIVO},
    {"codigo": "patients.read", "modulo": "patients", "accion": "read", "nombre": "VER_PACIENTES", "descripcion": "Ver pacientes", "estado": PERMISO_ESTADO_ACTIVO},
    {"codigo": "patients.write", "modulo": "patients", "accion": "write", "nombre": "EDITAR_PACIENTES", "descripcion": "Crear y editar pacientes", "estado": PERMISO_ESTADO_ACTIVO},
    {"codigo": "specialties.read", "modulo": "specialties", "accion": "read", "nombre": "VER_ESPECIALIDADES", "descripcion": "Ver especialidades médicas", "estado": PERMISO_ESTADO_ACTIVO},
    {"codigo": "analytics.read", "modulo": "analytics", "accion": "read", "nombre": "VER_REPORTES", "descripcion": "Ver reportes y analítica", "estado": PERMISO_ESTADO_ACTIVO},
]

SEED_ROLE_PERMISOS = {
    "Super Administrador": [p["codigo"] for p in SEED_PERMISOS],  # todos los permisos
    "Administrador": [p["codigo"] for p in SEED_PERMISOS],        # todos los permisos de clínica
    "Médico": [
        "appointments.read",
        "appointments.write",
        "medical_records.read",
        "medical_records.write",
        "patients.read",
        "specialties.read",
    ],
    "Recepción": [
        "appointments.read",
        "appointments.write",
        "patients.read",
        "patients.write",
        "users.read",
    ],
    "Paciente": [
        "appointments.read",
        "medical_records.read",
    ],
}

# ── 4. Usuarios Iniciales del Seed (SaaS y Clínicas) ──────────────────────
SEED_USERS = [
    # ── SUPERADMINISTRADORES GLOBALES SAAS (id_clinica = None) ────────────
    {
        "rol": "Super Administrador",
        "nombres": "Super",
        "apellidos": "Admin SaaS",
        "correo": "superadmin@telemedicina.com",
        "password": "superadmin123",
        "telefono": "+591 70000000",
        "foto_perfil": None,
        "estado": "activo",
        "id_clinica": None,
        "notificaciones_push": True,
        "notificaciones_email": True,
        "notificaciones_sms": False,
    },
    {
        "rol": "Super Administrador",
        "nombres": "Admin",
        "apellidos": "Global SaaS",
        "correo": "admin@telemedicina.com",
        "password": "admin123",
        "telefono": "+591 70000001",
        "foto_perfil": None,
        "estado": "activo",
        "id_clinica": None,
        "notificaciones_push": True,
        "notificaciones_email": True,
        "notificaciones_sms": False,
    },

    # ── CLÍNICA 1: Hospital San Juan de Dios (id_clinica = 1) ─────────────
    {
        "rol": "Administrador",
        "nombres": "Admin",
        "apellidos": "San Juan de Dios",
        "correo": "admin@sanjuandedios.com",
        "password": "admin123",
        "telefono": "+591 71000001",
        "foto_perfil": None,
        "estado": "activo",
        "id_clinica": 1,
        "notificaciones_push": True,
        "notificaciones_email": True,
        "notificaciones_sms": False,
    },
    {
        "rol": "Médico",
        "nombres": "Dr. Carlos",
        "apellidos": "Mendoza",
        "correo": "doctor@sanjuandedios.com",
        "password": "doctor123",
        "telefono": "+591 71000002",
        "foto_perfil": None,
        "estado": "activo",
        "id_clinica": 1,
        "notificaciones_push": True,
        "notificaciones_email": True,
        "notificaciones_sms": False,
    },
    {
        "rol": "Médico",
        "nombres": "Dra. Elena",
        "apellidos": "Vargas",
        "correo": "pediatra@sanjuandedios.com",
        "password": "doctor123",
        "telefono": "+591 71000005",
        "foto_perfil": None,
        "estado": "activo",
        "id_clinica": 1,
        "notificaciones_push": True,
        "notificaciones_email": True,
        "notificaciones_sms": False,
    },
    {
        "rol": "Recepción",
        "nombres": "Lucía",
        "apellidos": "Vaca",
        "correo": "recep@sanjuandedios.com",
        "password": "recep123",
        "telefono": "+591 71000003",
        "foto_perfil": None,
        "estado": "activo",
        "id_clinica": 1,
        "notificaciones_push": True,
        "notificaciones_email": True,
        "notificaciones_sms": False,
    },
    {
        "rol": "Paciente",
        "nombres": "Juan",
        "apellidos": "Pérez",
        "correo": "paciente@sanjuandedios.com",
        "password": "paciente123",
        "telefono": "+591 71000004",
        "foto_perfil": None,
        "estado": "activo",
        "id_clinica": 1,
        "notificaciones_push": True,
        "notificaciones_email": True,
        "notificaciones_sms": False,
    },
    {
        "rol": "Paciente",
        "nombres": "María",
        "apellidos": "López",
        "correo": "maria.lopez@sanjuandedios.com",
        "password": "paciente123",
        "telefono": "+591 71000006",
        "foto_perfil": None,
        "estado": "activo",
        "id_clinica": 1,
        "notificaciones_push": True,
        "notificaciones_email": True,
        "notificaciones_sms": False,
    },

    # ── CLÍNICA 2: Centro Médico Santa María (id_clinica = 2) ──────────────
    {
        "rol": "Administrador",
        "nombres": "Admin",
        "apellidos": "Santa María",
        "correo": "admin@santamaria.com",
        "password": "admin123",
        "telefono": "+591 72000001",
        "foto_perfil": None,
        "estado": "activo",
        "id_clinica": 2,
        "notificaciones_push": True,
        "notificaciones_email": True,
        "notificaciones_sms": False,
    },
    {
        "rol": "Médico",
        "nombres": "Dra. Valeria",
        "apellidos": "Rojas",
        "correo": "doctor@santamaria.com",
        "password": "doctor123",
        "telefono": "+591 72000002",
        "foto_perfil": None,
        "estado": "activo",
        "id_clinica": 2,
        "notificaciones_push": True,
        "notificaciones_email": True,
        "notificaciones_sms": False,
    },
    {
        "rol": "Médico",
        "nombres": "Dr. Roberto",
        "apellidos": "Silva",
        "correo": "dermatologo@santamaria.com",
        "password": "doctor123",
        "telefono": "+591 72000005",
        "foto_perfil": None,
        "estado": "activo",
        "id_clinica": 2,
        "notificaciones_push": True,
        "notificaciones_email": True,
        "notificaciones_sms": False,
    },
    {
        "rol": "Recepción",
        "nombres": "Marcos",
        "apellidos": "Quiroga",
        "correo": "recep@santamaria.com",
        "password": "recep123",
        "telefono": "+591 72000003",
        "foto_perfil": None,
        "estado": "activo",
        "id_clinica": 2,
        "notificaciones_push": True,
        "notificaciones_email": True,
        "notificaciones_sms": False,
    },
    {
        "rol": "Paciente",
        "nombres": "Ana",
        "apellidos": "Flores",
        "correo": "paciente@santamaria.com",
        "password": "paciente123",
        "telefono": "+591 72000004",
        "foto_perfil": None,
        "estado": "activo",
        "id_clinica": 2,
        "notificaciones_push": True,
        "notificaciones_email": True,
        "notificaciones_sms": False,
    },
    {
        "rol": "Paciente",
        "nombres": "Carlos",
        "apellidos": "Gutiérrez",
        "correo": "carlos.gutierrez@santamaria.com",
        "password": "paciente123",
        "telefono": "+591 72000006",
        "foto_perfil": None,
        "estado": "activo",
        "id_clinica": 2,
        "notificaciones_push": True,
        "notificaciones_email": True,
        "notificaciones_sms": False,
    },
]

# ── 5. Catálogo Base de Especialidades (CU04) ──────────────────────────────
SEED_ESPECIALIDADES = [
    {"nombre": "Medicina General", "descripcion": "Atención primaria y consulta general"},
    {"nombre": "Cardiología", "descripcion": "Diagnóstico y tratamiento de enfermedades del corazón"},
    {"nombre": "Pediatría", "descripcion": "Atención médica de niños y adolescentes"},
    {"nombre": "Dermatología", "descripcion": "Tratamiento de enfermedades de la piel"},
    {"nombre": "Ginecología", "descripcion": "Salud de la mujer y obstetricia"},
    {"nombre": "Traumatología", "descripcion": "Lesiones y enfermedades del sistema musculoesquelético"},
    {"nombre": "Neurología", "descripcion": "Trastornos del sistema nervioso"},
    {"nombre": "Psiquiatría", "descripcion": "Salud mental y trastornos psiquiátricos"},
]

# ── 6. Perfiles Médicos para los Doctores Seed ─────────────────────────────
SEED_MEDICOS = [
    {
        "correo_usuario": "doctor@sanjuandedios.com",
        "matricula_profesional": "MAT-SJD-001",
        "descripcion_profesional": "Médico generalista y cirujano con 8 años de experiencia en emergencias.",
        "experiencia": "Hospital San Juan de Dios, 2018-2026. Urgencias y consulta externa.",
        "especialidad_principal": "Medicina General",
    },
    {
        "correo_usuario": "pediatra@sanjuandedios.com",
        "matricula_profesional": "MAT-SJD-002",
        "descripcion_profesional": "Especialista en pediatría y neonatología con enfoque integral.",
        "experiencia": "Hospital San Juan de Dios, 2019-2026. Consulta externa y cuidados pediátricos.",
        "especialidad_principal": "Pediatría",
    },
    {
        "correo_usuario": "doctor@santamaria.com",
        "matricula_profesional": "MAT-STM-001",
        "descripcion_profesional": "Especialista en Cardiología clínica y prevención cardiovascular.",
        "experiencia": "Centro Médico Santa María, 2020-2026. Cardiopatías e hipertensión.",
        "especialidad_principal": "Cardiología",
    },
    {
        "correo_usuario": "dermatologo@santamaria.com",
        "matricula_profesional": "MAT-STM-002",
        "descripcion_profesional": "Dermatólogo clínico y estético, especialista en patologías cutáneas.",
        "experiencia": "Centro Médico Santa María, 2021-2026. Dermatología clínica y tratamientos láser.",
        "especialidad_principal": "Dermatología",
    },
]

# ── 7. Pacientes Seed por Clínica ───────────────────────────────────────────
SEED_PACIENTES = [
    # Pacientes Clínica 1 (Hospital San Juan de Dios)
    {
        "correo_usuario": "paciente@sanjuandedios.com",
        "id_clinica": 1,
        "nombres": "Juan",
        "apellidos": "Pérez",
        "ci": "1234567",
        "complemento": "",
        "fecha_nacimiento": date(1990, 5, 15),
        "genero": "M",
        "telefono": "+591 71000004",
        "correo": "paciente@sanjuandedios.com",
        "direccion": "Av. San Martín #450, Santa Cruz",
        "ciudad": "Santa Cruz de la Sierra",
        "tipo_sangre": "O+",
        "alergias": "Penicilina",
        "antecedentes_patologicos": "Hipertensión arterial leve",
        "contacto_emergencia_nombre": "Rosa Pérez",
        "contacto_emergencia_telefono": "+591 71000099",
        "contacto_emergencia_parentesco": "Madre",
        "seguro_medico": "Seguro Nacional de Salud",
        "numero_seguro": "SNS-12345",
        "estado": "ACTIVO",
    },
    {
        "correo_usuario": "maria.lopez@sanjuandedios.com",
        "id_clinica": 1,
        "nombres": "María",
        "apellidos": "López",
        "ci": "2345678",
        "complemento": "",
        "fecha_nacimiento": date(1995, 8, 20),
        "genero": "F",
        "telefono": "+591 71000006",
        "correo": "maria.lopez@sanjuandedios.com",
        "direccion": "Calle Beni #120, Santa Cruz",
        "ciudad": "Santa Cruz de la Sierra",
        "tipo_sangre": "A+",
        "alergias": "Ninguna conocida",
        "antecedentes_patologicos": "Asma bronquial en infancia",
        "contacto_emergencia_nombre": "Carlos López",
        "contacto_emergencia_telefono": "+591 71000098",
        "contacto_emergencia_parentesco": "Hermano",
        "seguro_medico": "Caja Nacional de Salud",
        "numero_seguro": "CNS-98765",
        "estado": "ACTIVO",
    },

    # Pacientes Clínica 2 (Centro Médico Santa María)
    {
        "correo_usuario": "paciente@santamaria.com",
        "id_clinica": 2,
        "nombres": "Ana",
        "apellidos": "Flores",
        "ci": "3456789",
        "complemento": "",
        "fecha_nacimiento": date(1988, 11, 30),
        "genero": "F",
        "telefono": "+591 72000004",
        "correo": "paciente@santamaria.com",
        "direccion": "Av. Arce #789, La Paz",
        "ciudad": "La Paz",
        "tipo_sangre": "B+",
        "alergias": "Ibuprofeno",
        "antecedentes_patologicos": "Gastritis crónica",
        "contacto_emergencia_nombre": "Jorge Flores",
        "contacto_emergencia_telefono": "+591 72000099",
        "contacto_emergencia_parentesco": "Esposo",
        "seguro_medico": "Seguro Privado Bisa",
        "numero_seguro": "BIS-44332",
        "estado": "ACTIVO",
    },
    {
        "correo_usuario": "carlos.gutierrez@santamaria.com",
        "id_clinica": 2,
        "nombres": "Carlos",
        "apellidos": "Gutiérrez",
        "ci": "4567890",
        "complemento": "",
        "fecha_nacimiento": date(1975, 3, 10),
        "genero": "M",
        "telefono": "+591 72000006",
        "correo": "carlos.gutierrez@santamaria.com",
        "direccion": "Calle 21 de Calacoto #55, La Paz",
        "ciudad": "La Paz",
        "tipo_sangre": "O-",
        "alergias": "Sulfas",
        "antecedentes_patologicos": "Diabetes Mellitus Tipo 2",
        "contacto_emergencia_nombre": "Patricia Gutiérrez",
        "contacto_emergencia_telefono": "+591 72000098",
        "contacto_emergencia_parentesco": "Hija",
        "seguro_medico": "Seguro Privado Alianza",
        "numero_seguro": "ALZ-77889",
        "estado": "ACTIVO",
    },
]

# ── 8. Registros Iniciales de Auditoría ──────────────────────────────────────
SEED_AUDITORIA = [
    {
        "correo_usuario": "superadmin@telemedicina.com",
        "id_clinica": None,
        "tabla_afectada": "clinicas",
        "accion": "CREAR",
        "descripcion": "Registro y alta inicial de la clínica 'Hospital San Juan de Dios' en el SaaS.",
    },
    {
        "correo_usuario": "superadmin@telemedicina.com",
        "id_clinica": None,
        "tabla_afectada": "clinicas",
        "accion": "CREAR",
        "descripcion": "Registro y alta inicial de la clínica 'Centro Médico Santa María' en el SaaS.",
    },
    {
        "correo_usuario": "admin@sanjuandedios.com",
        "id_clinica": 1,
        "tabla_afectada": "usuarios",
        "accion": "CREAR",
        "descripcion": "Alta de personal médico y recepcionistas en Hospital San Juan de Dios.",
    },
    {
        "correo_usuario": "admin@santamaria.com",
        "id_clinica": 2,
        "tabla_afectada": "usuarios",
        "accion": "CREAR",
        "descripcion": "Alta de personal médico y recepcionistas en Centro Médico Santa María.",
    },
]


def seed_database():
    """Ejecuta el seed principal de datos multitenant de forma idempotente (upsert):
    Clínicas -> Roles -> Permisos -> RolPermisos -> Usuarios -> Especialidades -> Médicos -> Pacientes -> Auditoría."""
    db = SessionLocal()
    print("==================================================================")
    print("      INICIANDO SEED PRINCIPAL MULTITENANT (SAAS TELEMEDICINA)    ")
    print("==================================================================")

    try:
        # ── Ajuste de seguridad: Auditoría con id_clinica nullable ──────────
        try:
            db.execute(text("ALTER TABLE auditoria ALTER COLUMN id_clinica DROP NOT NULL;"))
            db.commit()
        except Exception:
            db.rollback()

        # ── Fase 0: Clínicas ────────────────────────────────────────────────
        print("\n[FASE 0] Sembrando Clínicas...")
        clinicas_map: dict[int, Clinica] = {}
        for clinica_data in SEED_CLINICAS:
            c_id = clinica_data["id_clinica"]
            clinica = db.query(Clinica).filter(Clinica.id_clinica == c_id).first()
            if not clinica:
                clinica = db.query(Clinica).filter(Clinica.nombre == clinica_data["nombre"]).first()

            if clinica:
                clinica.nombre = clinica_data["nombre"]
                clinica.razon_social = clinica_data["razon_social"]
                clinica.nit = clinica_data["nit"]
                clinica.telefono = clinica_data["telefono"]
                clinica.correo = clinica_data["correo"]
                clinica.direccion = clinica_data["direccion"]
                clinica.estado = clinica_data["estado"]
                print(f"  [ACTUALIZADA] Clínica ID={clinica.id_clinica}: {clinica.nombre}")
            else:
                clinica = Clinica(
                    id_clinica=c_id,
                    nombre=clinica_data["nombre"],
                    razon_social=clinica_data["razon_social"],
                    nit=clinica_data["nit"],
                    telefono=clinica_data["telefono"],
                    correo=clinica_data["correo"],
                    direccion=clinica_data["direccion"],
                    estado=clinica_data["estado"],
                )
                db.add(clinica)
                print(f"  [CREADA] Nueva Clínica ID={c_id}: {clinica_data['nombre']}")
            db.flush()
            clinicas_map[clinica.id_clinica] = clinica

        # ── Fase 1: Roles Base (CU26) ───────────────────────────────────────
        print("\n[FASE 1] Sembrando Roles...")
        roles_por_nombre: dict[str, Rol] = {}
        for rol_data in SEED_ROLES:
            nombre = rol_data["nombre"].strip()
            rol = (
                db.query(Rol)
                .filter(func.lower(Rol.nombre) == nombre.lower(), Rol.id_clinica.is_(None))
                .first()
            )
            if rol:
                rol.descripcion = rol_data["descripcion"]
                rol.estado = rol_data["estado"]
                print(f"  [ACTUALIZADO] Rol: {nombre}")
            else:
                rol = Rol(
                    nombre=nombre,
                    descripcion=rol_data["descripcion"],
                    estado=rol_data["estado"],
                    id_clinica=None,  # rol global del SaaS
                )
                db.add(rol)
                print(f"  [CREADO] Nuevo rol: {nombre}")
            db.flush()
            roles_por_nombre[nombre] = rol

        # ── Fase 2: Catálogo de Permisos (CU26) ─────────────────────────────
        print("\n[FASE 2] Sembrando Permisos...")
        permisos_por_codigo: dict[str, Permiso] = {}
        for permiso_data in SEED_PERMISOS:
            permiso = (
                db.query(Permiso)
                .filter(
                    Permiso.modulo == permiso_data["modulo"],
                    Permiso.accion == permiso_data["accion"],
                )
                .first()
            )
            if permiso:
                permiso.nombre = permiso_data["nombre"]
                permiso.descripcion = permiso_data["descripcion"]
                permiso.estado = permiso_data["estado"]
                print(f"  [ACTUALIZADO] Permiso: [{permiso_data['modulo']}.{permiso_data['accion']}]")
            else:
                permiso = Permiso(
                    nombre=permiso_data["nombre"],
                    descripcion=permiso_data["descripcion"],
                    modulo=permiso_data["modulo"],
                    accion=permiso_data["accion"],
                    estado=permiso_data["estado"],
                )
                db.add(permiso)
                print(f"  [CREADO] Nuevo permiso: [{permiso_data['modulo']}.{permiso_data['accion']}]")
            db.flush()
            permisos_por_codigo[permiso_data["codigo"]] = permiso

        # ── Fase 3: Asignación Rol -> Permisos (CU26) ───────────────────────
        print("\n[FASE 3] Asignando Permisos a Roles...")
        for nombre_rol, codigos in SEED_ROLE_PERMISOS.items():
            rol = roles_por_nombre.get(nombre_rol)
            if not rol:
                continue
            for codigo in codigos:
                permiso = permisos_por_codigo.get(codigo)
                if not permiso:
                    continue
                asignacion = (
                    db.query(RolPermiso)
                    .filter(
                        RolPermiso.id_rol == rol.id_rol,
                        RolPermiso.id_permiso == permiso.id_permiso,
                    )
                    .first()
                )
                if not asignacion:
                    db.add(RolPermiso(id_rol=rol.id_rol, id_permiso=permiso.id_permiso))
                    print(f"  [CREADA] Permiso '{codigo}' -> rol '{nombre_rol}'")
        db.flush()

        # ── Fase 4: Usuarios (Superadmin y Usuarios de Clínica) ─────────────
        print("\n[FASE 4] Sembrando Usuarios...")
        usuarios_por_correo: dict[str, Usuario] = {}
        for user_data in SEED_USERS:
            correo = user_data["correo"].lower().strip()
            rol_asignado = roles_por_nombre.get(user_data.get("rol"))
            if rol_asignado is None:
                rol_asignado = roles_por_nombre.get("Administrador")

            existing_user = db.query(Usuario).filter(Usuario.correo == correo).first()

            if existing_user:
                existing_user.nombres = user_data["nombres"]
                existing_user.apellidos = user_data["apellidos"]
                existing_user.telefono = user_data["telefono"]
                existing_user.foto_perfil = user_data["foto_perfil"]
                existing_user.estado = user_data["estado"]
                existing_user.id_clinica = user_data["id_clinica"]  # None para Superadmin, 1 o 2 para clínica
                if rol_asignado:
                    existing_user.id_rol = rol_asignado.id_rol

                if not verify_password(user_data["password"], existing_user.password_hash):
                    existing_user.password_hash = hash_password(user_data["password"])

                tenant_str = f"Clínica {existing_user.id_clinica}" if existing_user.id_clinica else "GLOBAL (Super Admin)"
                print(f"  [ACTUALIZADO] {correo} -> Rol: '{user_data['rol']}', Tenant: {tenant_str}")
                usuarios_por_correo[correo] = existing_user
            else:
                new_user = Usuario(
                    nombres=user_data["nombres"],
                    apellidos=user_data["apellidos"],
                    correo=correo,
                    password_hash=hash_password(user_data["password"]),
                    telefono=user_data["telefono"],
                    foto_perfil=user_data["foto_perfil"],
                    estado=user_data["estado"],
                    id_clinica=user_data["id_clinica"],
                    notificaciones_push=user_data["notificaciones_push"],
                    notificaciones_email=user_data["notificaciones_email"],
                    notificaciones_sms=user_data["notificaciones_sms"],
                )
                if rol_asignado is not None:
                    new_user.id_rol = rol_asignado.id_rol
                db.add(new_user)
                tenant_str = f"Clínica {new_user.id_clinica}" if new_user.id_clinica else "GLOBAL (Super Admin)"
                print(f"  [CREADO] {correo} -> Rol: '{user_data['rol']}', Tenant: {tenant_str}")
                db.flush()
                usuarios_por_correo[correo] = new_user

        db.flush()

        # ── Fase 5: Especialidades Médicas (CU04) ───────────────────────────
        print("\n[FASE 5] Sembrando Especialidades Médicas...")
        for esp_data in SEED_ESPECIALIDADES:
            existing_esp = (
                db.query(Especialidad)
                .filter(Especialidad.nombre.ilike(esp_data["nombre"]))
                .first()
            )
            if existing_esp:
                existing_esp.descripcion = esp_data["descripcion"]
                existing_esp.estado = "activo"
                print(f"  [ACTUALIZADO] Especialidad: {esp_data['nombre']}")
            else:
                db.add(Especialidad(nombre=esp_data["nombre"], descripcion=esp_data["descripcion"], estado="activo"))
                print(f"  [CREADA] Especialidad: {esp_data['nombre']}")

        db.flush()

        # ── Fase 6: Perfiles Médicos (CU04) ─────────────────────────────────
        print("\n[FASE 6] Asignando Perfiles Médicos y Especialidades...")
        for med_data in SEED_MEDICOS:
            doctor_user = usuarios_por_correo.get(med_data["correo_usuario"]) or (
                db.query(Usuario).filter(Usuario.correo == med_data["correo_usuario"]).first()
            )
            if doctor_user:
                medico = db.query(Medico).filter(Medico.id_usuario == doctor_user.id_usuario).first()
                if not medico:
                    medico = Medico(
                        id_usuario=doctor_user.id_usuario,
                        matricula_profesional=med_data["matricula_profesional"],
                        descripcion_profesional=med_data["descripcion_profesional"],
                        experiencia=med_data["experiencia"],
                        estado="activo",
                    )
                    db.add(medico)
                    print(f"  [CREADO] Perfil médico: {med_data['correo_usuario']}")
                else:
                    medico.matricula_profesional = med_data["matricula_profesional"]
                    medico.descripcion_profesional = med_data["descripcion_profesional"]
                    medico.experiencia = med_data["experiencia"]
                    medico.estado = "activo"
                    print(f"  [ACTUALIZADO] Perfil médico: {med_data['correo_usuario']}")

                db.flush()

                especialidad_ppal = (
                    db.query(Especialidad)
                    .filter(Especialidad.nombre.ilike(med_data["especialidad_principal"]))
                    .first()
                )
                if especialidad_ppal:
                    asociacion = (
                        db.query(MedicoEspecialidad)
                        .filter(
                            MedicoEspecialidad.id_medico == medico.id_medico,
                            MedicoEspecialidad.id_especialidad == especialidad_ppal.id_especialidad,
                        )
                        .first()
                    )
                    if not asociacion:
                        db.query(MedicoEspecialidad).filter(
                            MedicoEspecialidad.id_medico == medico.id_medico,
                            MedicoEspecialidad.es_principal.is_(True),
                        ).update({"es_principal": False}, synchronize_session=False)
                        db.add(
                            MedicoEspecialidad(
                                id_medico=medico.id_medico,
                                id_especialidad=especialidad_ppal.id_especialidad,
                                es_principal=True,
                            )
                        )
                        print(f"  [ASIGNADA] {med_data['especialidad_principal']} -> {med_data['correo_usuario']}")
                    else:
                        asociacion.es_principal = True

        db.flush()

        # ── Fase 7: Pacientes (Expediente Clínico por Tenant) ───────────────
        print("\n[FASE 7] Sembrando Pacientes...")
        for pac_data in SEED_PACIENTES:
            pac_user = usuarios_por_correo.get(pac_data["correo_usuario"]) or (
                db.query(Usuario).filter(Usuario.correo == pac_data["correo_usuario"]).first()
            )
            pac_id_usuario = pac_user.id_usuario if pac_user else None

            existing_paciente = (
                db.query(Paciente)
                .filter(Paciente.ci == pac_data["ci"], Paciente.complemento == pac_data["complemento"])
                .first()
            )

            if existing_paciente:
                existing_paciente.id_clinica = pac_data["id_clinica"]
                existing_paciente.id_usuario = pac_id_usuario
                existing_paciente.nombres = pac_data["nombres"]
                existing_paciente.apellidos = pac_data["apellidos"]
                existing_paciente.fecha_nacimiento = pac_data["fecha_nacimiento"]
                existing_paciente.genero = pac_data["genero"]
                existing_paciente.telefono = pac_data["telefono"]
                existing_paciente.correo = pac_data["correo"]
                existing_paciente.direccion = pac_data["direccion"]
                existing_paciente.ciudad = pac_data["ciudad"]
                existing_paciente.tipo_sangre = pac_data["tipo_sangre"]
                existing_paciente.alergias = pac_data["alergias"]
                existing_paciente.antecedentes_patologicos = pac_data["antecedentes_patologicos"]
                existing_paciente.contacto_emergencia_nombre = pac_data["contacto_emergencia_nombre"]
                existing_paciente.contacto_emergencia_telefono = pac_data["contacto_emergencia_telefono"]
                existing_paciente.contacto_emergencia_parentesco = pac_data["contacto_emergencia_parentesco"]
                existing_paciente.seguro_medico = pac_data["seguro_medico"]
                existing_paciente.numero_seguro = pac_data["numero_seguro"]
                existing_paciente.estado = pac_data["estado"]
                print(f"  [ACTUALIZADO] Paciente: {pac_data['nombres']} {pac_data['apellidos']} (CI: {pac_data['ci']}) -> Clínica {pac_data['id_clinica']}")
            else:
                new_paciente = Paciente(
                    id_clinica=pac_data["id_clinica"],
                    id_usuario=pac_id_usuario,
                    nombres=pac_data["nombres"],
                    apellidos=pac_data["apellidos"],
                    ci=pac_data["ci"],
                    complemento=pac_data["complemento"],
                    fecha_nacimiento=pac_data["fecha_nacimiento"],
                    genero=pac_data["genero"],
                    telefono=pac_data["telefono"],
                    correo=pac_data["correo"],
                    direccion=pac_data["direccion"],
                    ciudad=pac_data["ciudad"],
                    tipo_sangre=pac_data["tipo_sangre"],
                    alergias=pac_data["alergias"],
                    antecedentes_patologicos=pac_data["antecedentes_patologicos"],
                    contacto_emergencia_nombre=pac_data["contacto_emergencia_nombre"],
                    contacto_emergencia_telefono=pac_data["contacto_emergencia_telefono"],
                    contacto_emergencia_parentesco=pac_data["contacto_emergencia_parentesco"],
                    seguro_medico=pac_data["seguro_medico"],
                    numero_seguro=pac_data["numero_seguro"],
                    estado=pac_data["estado"],
                )
                db.add(new_paciente)
                print(f"  [CREADO] Paciente: {pac_data['nombres']} {pac_data['apellidos']} (CI: {pac_data['ci']}) -> Clínica {pac_data['id_clinica']}")

        db.flush()

        # ── Fase 8: Bitácora de Auditoría Inicial ───────────────────────────
        print("\n[FASE 8] Sembrando Registros de Auditoría...")
        for aud_data in SEED_AUDITORIA:
            aud_user = usuarios_por_correo.get(aud_data["correo_usuario"]) or (
                db.query(Usuario).filter(Usuario.correo == aud_data["correo_usuario"]).first()
            )
            if aud_user:
                existing_log = (
                    db.query(Auditoria)
                    .filter(
                        Auditoria.id_usuario == aud_user.id_usuario,
                        Auditoria.descripcion == aud_data["descripcion"]
                    )
                    .first()
                )
                if not existing_log:
                    db.add(
                        Auditoria(
                            id_clinica=aud_data["id_clinica"],
                            id_usuario=aud_user.id_usuario,
                            tabla_afectada=aud_data["tabla_afectada"],
                            accion=aud_data["accion"],
                            descripcion=aud_data["descripcion"],
                            direccion_ip="127.0.0.1",
                            fecha_hora=datetime.now(),
                        )
                    )
                    print(f"  [CREADO] Log auditoría: {aud_data['accion']} por {aud_data['correo_usuario']}")

        db.commit()

        # Resumen
        total_clinicas = db.query(Clinica).count()
        total_usuarios = db.query(Usuario).count()
        total_superadmins = db.query(Usuario).filter(Usuario.id_clinica.is_(None)).count()
        total_roles = db.query(Rol).count()
        total_permisos = db.query(Permiso).count()
        total_medicos = db.query(Medico).count()
        total_pacientes = db.query(Paciente).count()
        total_auditoria = db.query(Auditoria).count()
        
        print("\n==================================================================")
        print("                        RESUMEN DE SEED                           ")
        print("==================================================================")
        print(f"  Total Clínicas     : {total_clinicas}")
        print(f"  Total Usuarios     : {total_usuarios} (Super Admins Globales: {total_superadmins})")
        print(f"  Total Roles        : {total_roles}")
        print(f"  Total Permisos     : {total_permisos}")
        print(f"  Total Médicos      : {total_medicos}")
        print(f"  Total Pacientes    : {total_pacientes}")
        print(f"  Total Auditoría    : {total_auditoria}")
        print("==================================================================")
        print("[EXITO] ¡Seed principal multitenant ejecutado satisfactoriamente!\n")

    except Exception as e:
        db.rollback()
        print(f"\n[ERROR] Error durante la ejecución del seed: {e}")
        raise e
    finally:
        db.close()


if __name__ == "__main__":
    seed_database()
