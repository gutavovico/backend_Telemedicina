import sys
import os

sys.path.insert(0, os.path.realpath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def run_tests():
    print("========================================")
    print(" INICIANDO PRUEBAS DE ENDPOINTS")
    print("========================================")

    # 1. Health check
    print("\n1. Probando GET / (Health check)...")
    res = client.get("/")
    print(f"   Status: {res.status_code}, Response: {res.json()}")
    assert res.status_code == 200

    # 2. Login con usuario seed
    print("\n2. Probando POST /auth/login con usuario seed (admin@telemedicina.com)...")
    login_data = {
        "correo": "admin@telemedicina.com",
        "password": "admin123"
    }
    res = client.post("/auth/login", json=login_data)
    print(f"   Status: {res.status_code}")
    data = res.json()
    assert res.status_code == 200
    assert "access_token" in data
    assert "refresh_token" in data
    print(f"   Access Token recibido (primeros 30 chars): {data['access_token'][:30]}...")
    print(f"   Refresh Token recibido (primeros 30 chars): {data['refresh_token'][:30]}...")

    access_token = data["access_token"]
    refresh_token = data["refresh_token"]

    # 3. GET /auth/me con token
    print("\n3. Probando GET /auth/me con token Bearer...")
    headers = {"Authorization": f"Bearer {access_token}"}
    res = client.get("/auth/me", headers=headers)
    print(f"   Status: {res.status_code}, Response: {res.json()}")
    assert res.status_code == 200
    me_data = res.json()
    assert me_data["correo"] == "admin@telemedicina.com"
    assert me_data["nombres"] == "Admin"

    # 4. POST /auth/refresh
    print("\n4. Probando POST /auth/refresh con refresh_token...")
    res = client.post("/auth/refresh", json={"refresh_token": refresh_token})
    print(f"   Status: {res.status_code}")
    new_tokens = res.json()
    assert res.status_code == 200
    assert "access_token" in new_tokens
    print(f"   Nuevo Access Token (primeros 30 chars): {new_tokens['access_token'][:30]}...")

    # 5. Registro de nuevo usuario
    import time
    timestamp = int(time.time())
    nuevo_correo = f"paciente_{timestamp}@telemedicina.com"
    print(f"\n5. Probando POST /auth/register con nuevo usuario ({nuevo_correo})...")
    registro_data = {
        "nombres": "María",
        "apellidos": "López",
        "correo": nuevo_correo,
        "password": "PasswordPaciente456!",
        "telefono": "+591 72222222",
        "foto_perfil": "https://example.com/maria.png",
        "notificaciones_push": True,
        "notificaciones_email": True,
        "notificaciones_sms": True
    }
    res = client.post("/auth/register", json=registro_data)
    print(f"   Status: {res.status_code}, Response: {res.json()}")
    assert res.status_code == 201
    user_created = res.json()
    assert user_created["correo"] == nuevo_correo
    assert "id_usuario" in user_created

    # 6. Login con nuevo usuario registrado
    print(f"\n6. Probando POST /auth/login con nuevo usuario ({nuevo_correo})...")
    res = client.post("/auth/login", json={"correo": nuevo_correo, "password": "PasswordPaciente456!"})
    print(f"   Status: {res.status_code}")
    assert res.status_code == 200

    # 7. Error cases
    print("\n7. Probando validacion de errores...")
    # Credenciales incorrectas
    res = client.post("/auth/login", json={"correo": "admin@telemedicina.com", "password": "wrongpassword"})
    print(f"   Login con pass errónea -> Status: {res.status_code} ({res.json()['detail']})")
    assert res.status_code == 401

    # Correo duplicado
    res = client.post("/auth/register", json=registro_data)
    print(f"   Registro duplicado -> Status: {res.status_code} ({res.json()['detail']})")
    assert res.status_code == 400

    # Token inválido
    res = client.get("/auth/me", headers={"Authorization": "Bearer token_falso_123"})
    print(f"   GET /auth/me con token inválido -> Status: {res.status_code} ({res.json()['detail']})")
    assert res.status_code == 401

    print("\n========================================")
    print(" [EXITO] TODOS LOS TESTS PASARON (7/7)")
    print("========================================")


if __name__ == "__main__":
    run_tests()
