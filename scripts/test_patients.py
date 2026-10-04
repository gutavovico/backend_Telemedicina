import sys
import os
import time

sys.path.insert(0, os.path.realpath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.core.database import Base, get_db
# Importar todos los modelos para que Base los registre
from app.modules.auth.models import Usuario
from app.modules.medical_records.models import Paciente

# Usar SQLite en memoria para tests aislados
TEST_DATABASE_URL = "sqlite:///:memory:"
test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


def run_patient_tests():
    print("========================================")
    print(" INICIANDO PRUEBAS DE SDD: CU03 PACIENTES")
    print("========================================")

    # Crear todas las tablas en la BD de pruebas
    Base.metadata.create_all(bind=test_engine)

    # 1. Registrar y autenticar usuario Admin
    print("\n1. Creando y autenticando usuario Admin...")
    admin_data = {
        "nombres": "Admin",
        "apellidos": "Sistema",
        "correo": "admin@telemedicina.com",
        "password": "adminpassword123",
        "telefono": "+591 70000000"
    }
    reg_res = client.post("/auth/register", json=admin_data)
    assert reg_res.status_code == 201, f"Fallo al registrar admin: {reg_res.text}"

    login_res = client.post("/auth/login", json={
        "correo": "admin@telemedicina.com",
        "password": "adminpassword123"
    })
    assert login_res.status_code == 200, f"Fallo en login de admin: {login_res.text}"
    admin_token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {admin_token}"}
    print("   -> PASS: Admin autenticado con Token Bearer.")

    timestamp = int(time.time())
    ci_test = f"CI{timestamp}"

    # 2. [AC-01] Registro exitoso de paciente
    print(f"\n2. Probando POST /api/v1/pacientes (Registro exitoso CI: {ci_test})...")
    paciente_payload = {
        "nombres": "Carlos Alberto",
        "apellidos": "Mamani Terrazas",
        "ci": ci_test,
        "complemento": "LP",
        "fecha_nacimiento": "1990-05-15",
        "genero": "M",
        "telefono": "+591 71234567",
        "correo": f"carlos_{timestamp}@email.com",
        "direccion": "Av. Banzer 4to Anillo",
        "ciudad": "Santa Cruz de la Sierra",
        "tipo_sangre": "O+",
        "alergias": "Penicilina, AINEs",
        "antecedentes_patologicos": "Asma en la infancia",
        "contacto_emergencia_nombre": "Maria Terrazas",
        "contacto_emergencia_telefono": "+591 79876543",
        "contacto_emergencia_parentesco": "Madre",
        "seguro_medico": "Seguro Universitario",
        "numero_seguro": "SU-98765"
    }
    res = client.post("/api/v1/pacientes", json=paciente_payload, headers=headers)
    print(f"   Status: {res.status_code}, Response: {res.json()}")
    assert res.status_code == 201, f"Esperado 201 pero fue {res.status_code}"
    data_created = res.json()
    id_paciente = data_created["id_paciente"]
    assert data_created["ci"] == ci_test
    assert data_created["estado"] == "ACTIVO"
    assert "created_at" in data_created
    print("   -> PASS: Paciente creado exitosamente con ID:", id_paciente)

    # 3. [AC-02] Conflicto por C.I. Duplicado (409 Conflict)
    print("\n3. Probando POST /api/v1/pacientes con C.I. duplicado (409 Conflict)...")
    res_dup = client.post("/api/v1/pacientes", json=paciente_payload, headers=headers)
    print(f"   Status: {res_dup.status_code}, Detail: {res_dup.json().get('detail')}")
    assert res_dup.status_code == 409
    print("   -> PASS: Conflicto 409 validado.")

    # 4. [AC-03] Validación de error: Fecha de nacimiento futura (422)
    print("\n4. Probando POST /api/v1/pacientes con fecha futura (422 Unprocessable Entity)...")
    invalido_payload = dict(paciente_payload)
    invalido_payload["ci"] = f"INV{timestamp}"
    invalido_payload["fecha_nacimiento"] = "2099-01-01"
    res_inv = client.post("/api/v1/pacientes", json=invalido_payload, headers=headers)
    print(f"   Status: {res_inv.status_code}")
    assert res_inv.status_code == 422
    print("   -> PASS: Validación de fecha futura rechazada con 422.")

    # 5. [AC-04] Listado paginado y búsqueda
    print("\n5. Probando GET /api/v1/pacientes con paginación y búsqueda...")
    res_list = client.get("/api/v1/pacientes?page=1&page_size=10&q=Mamani&estado=ACTIVO", headers=headers)
    print(f"   Status: {res_list.status_code}")
    assert res_list.status_code == 200
    list_data = res_list.json()
    assert "items" in list_data
    assert list_data["total"] >= 1
    assert list_data["page"] == 1
    print(f"   -> PASS: Listado paginado obtenido. Total registros: {list_data['total']}.")

    # 6. [AC-05] Consulta de detalle por ID
    print(f"\n6. Probando GET /api/v1/pacientes/{id_paciente}...")
    res_det = client.get(f"/api/v1/pacientes/{id_paciente}", headers=headers)
    print(f"   Status: {res_det.status_code}, Nombres: {res_det.json().get('nombres')}")
    assert res_det.status_code == 200
    assert res_det.json()["id_paciente"] == id_paciente
    print("   -> PASS: Detalle consultado correctamente.")

    # 7. [AC-06] Actualización completa por ID (PUT)
    print(f"\n7. Probando PUT /api/v1/pacientes/{id_paciente}...")
    update_payload = {
        "telefono": "+591 78899000",
        "direccion": "Av. San Martín Calle 7",
        "alergias": "Penicilina, Sulfas",
        "antecedentes_patologicos": "Hipertensión arterial controlada"
    }
    res_upd = client.put(f"/api/v1/pacientes/{id_paciente}", json=update_payload, headers=headers)
    print(f"   Status: {res_upd.status_code}, Alergias actualizadas: {res_upd.json().get('alergias')}")
    assert res_upd.status_code == 200
    assert res_upd.json()["telefono"] == "+591 78899000"
    assert res_upd.json()["alergias"] == "Penicilina, Sulfas"
    print("   -> PASS: Expediente actualizado exitosamente.")

    # 8. [AC-07] Desactivación lógica (DELETE / Soft Delete)
    print(f"\n8. Probando DELETE /api/v1/pacientes/{id_paciente} (Soft Delete)...")
    res_del = client.delete(f"/api/v1/pacientes/{id_paciente}", headers=headers)
    print(f"   Status: {res_del.status_code}, Response: {res_del.json()}")
    assert res_del.status_code == 200
    assert res_del.json()["estado"] == "INACTIVO"

    # Verificar que el estado ahora sea INACTIVO
    res_check = client.get(f"/api/v1/pacientes/{id_paciente}", headers=headers)
    assert res_check.json()["estado"] == "INACTIVO"
    print("   -> PASS: Baja lógica verificada.")

    # 9. [AC-08] Consulta con ID inexistente (404 Not Found)
    print("\n9. Probando GET /api/v1/pacientes/999999 (404 Not Found)...")
    res_404 = client.get("/api/v1/pacientes/999999", headers=headers)
    print(f"   Status: {res_404.status_code}")
    assert res_404.status_code == 404
    print("   -> PASS: 404 Not Found validado.")

    # 10. [AC-09] Perfil propio del paciente (/me y PATCH /me)
    print("\n10. Probando GET/PATCH /api/v1/pacientes/me...")
    # Crear usuario paciente
    user_paciente_data = {
        "nombres": "Ana",
        "apellidos": "Gutiérrez",
        "correo": f"ana_{timestamp}@paciente.com",
        "password": "PasswordAna123!",
        "telefono": "+591 71112222"
    }
    client.post("/auth/register", json=user_paciente_data)
    login_ana = client.post("/auth/login", json={
        "correo": f"ana_{timestamp}@paciente.com",
        "password": "PasswordAna123!"
    })
    ana_token = login_ana.json()["access_token"]
    ana_headers = {"Authorization": f"Bearer {ana_token}"}
    ana_user_id = client.get("/auth/me", headers=ana_headers).json()["id_usuario"]

    # Crear expediente vinculado a Ana
    client.post("/api/v1/pacientes", json={
        "id_usuario": ana_user_id,
        "nombres": "Ana",
        "apellidos": "Gutiérrez",
        "ci": f"ANA{timestamp}",
        "fecha_nacimiento": "1995-08-20",
        "genero": "F",
        "telefono": "+591 71112222",
        "correo": f"ana_{timestamp}@paciente.com"
    }, headers=headers)

    # Ana consulta su perfil
    res_ana_me = client.get("/api/v1/pacientes/me", headers=ana_headers)
    assert res_ana_me.status_code == 200
    assert res_ana_me.json()["ci"] == f"ANA{timestamp}"

    # Ana actualiza su contacto de emergencia
    patch_res = client.patch("/api/v1/pacientes/me", json={
        "contacto_emergencia_nombre": "Carlos Gutiérrez",
        "contacto_emergencia_telefono": "+591 79998888",
        "contacto_emergencia_parentesco": "Padre"
    }, headers=ana_headers)
    assert patch_res.status_code == 200
    assert patch_res.json()["contacto_emergencia_nombre"] == "Carlos Gutiérrez"
    print("   -> PASS: Perfil /me y PATCH /me validado exitosamente.")

    print("\n========================================")
    print(" ¡TODAS LAS PRUEBAS DE CU03 PASARON EXITOSAMENTE (10/10)!")
    print("========================================")


if __name__ == "__main__":
    run_patient_tests()
