"""Script de diagnóstico para verificar la conexión a Cloudflare R2 / S3.

Prueba el ciclo de vida completo:
1. Conexión y lectura de configuración activa.
2. Escritura (storage.store).
3. Lectura y validación de integridad SHA-256 (storage.read).
4. Eliminación de archivo de prueba (storage.delete).
"""
import sys
import hashlib
import uuid
from pathlib import Path

# Agregar raíz del backend al path
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import settings
from app.modules.medical_records.clinical_documents.storage import storage, StorageError


def test_storage():
    print("=" * 60)
    print(" Verificación de Almacenamiento (Cloudflare R2 / S3 / Local)")
    print("=" * 60)
    print(f"Backend activo:       {settings.STORAGE_BACKEND}")
    print(f"Endpoint configurado: {settings.MINIO_ENDPOINT}")
    print(f"Bucket configurado:   {settings.MINIO_BUCKET}")
    print(f"Directorio local:     {settings.STORAGE_LOCAL_DIR}")
    print("-" * 60)

    if settings.STORAGE_BACKEND.lower() != "r2":
        raise RuntimeError("Esta verificación requiere STORAGE_BACKEND=r2")

    test_content = f"%PDF-1.4\nTest R2 {uuid.uuid4()}".encode()
    test_sha = hashlib.sha256(test_content).hexdigest()
    test_filename = f"test_conexion_r2_{uuid.uuid4().hex}.pdf"

    print("[1/4] Probando almacenamiento (store)...")
    try:
        key, sha = storage.store(test_filename, test_content, content_type="application/pdf")
        print(f"      OK -> Clave asignada: {key}")
        print(f"      OK -> SHA-256:        {sha}")
    except Exception as exc:
        print(f"\n[ERROR] Falló la subida al storage:\n{exc}")
        print("\nVerifica que:")
        print("  1. MINIO_ENDPOINT sea https://<account_id>.r2.cloudflarestorage.com")
        print("  2. MINIO_ACCESS_KEY y MINIO_SECRET_KEY sean correctos.")
        print("  3. MINIO_BUCKET coincida exactamente con el nombre de tu bucket en Cloudflare.")
        sys.exit(1)

    try:
        print("[2/4] Probando lectura y comprobación de integridad (read)...")
        leido = storage.read(key)
        if leido is None:
            raise RuntimeError("El archivo no fue encontrado tras guardarlo")
        leido_sha = hashlib.sha256(leido).hexdigest()
        if leido_sha != test_sha:
            raise RuntimeError(f"Discrepancia de integridad SHA-256: {leido_sha} != {test_sha}")
        print("      OK -> Bytes leídos correctamente e integridad SHA-256 verificada.")
        print("[3/4] Probando generación de URL firmada...")
        url, exp = storage.generate_download_url(key, test_filename)
        if not url:
            raise RuntimeError("No se generó URL de descarga")
        print(f"      OK -> URL generada (expira en {exp}s)")
    finally:
        print("[4/4] Probando eliminación y compensación (delete)...")
        eliminado = storage.delete(key)
        if not eliminado:
            raise RuntimeError(f"No se pudo eliminar el archivo de prueba: {key}")
        print("      OK -> Archivo de prueba eliminado limpiamente.")

    print("=" * 60)
    print(" Escritura, lectura, URL y limpieza verificadas en Cloudflare R2.")
    print("=" * 60)


if __name__ == "__main__":
    test_storage()
