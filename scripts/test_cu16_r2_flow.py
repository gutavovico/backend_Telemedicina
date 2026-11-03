"""Prueba de flujo completo CU16 con Cloudflare R2:
1. Emisión de receta simulada usando `build_receta_pdf`.
2. Almacenamiento directo en Cloudflare R2 mediante `storage.store`.
3. Verificación de lectura remota con `storage.read` y comparación de hash SHA-256.
4. Consulta remota en R2 mediante API S3 directa para verificar que el objeto existe en Cloudflare.
5. Limpieza del archivo de prueba en Cloudflare R2 con `storage.delete`.
"""
import sys
import hashlib
import uuid
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import boto3
from app.core.config import settings
from app.modules.medical_records.clinical_documents.storage import storage
from app.modules.medical_records.prescriptions.pdfgen import (
    RecetaPdfData,
    RecetaPdfDetalle,
    build_receta_pdf,
)
from app.modules.medical_records.prescriptions.qrcodegen import encode_qr_matrix


def run_test():
    if settings.STORAGE_BACKEND.lower() != "r2":
        raise RuntimeError("Esta prueba requiere STORAGE_BACKEND=r2")
    print("=" * 65)
    print(" PRUEBA INTEGRAL CU16 -> CLOUDFLARE R2")
    print("=" * 65)
    print(f"Backend activo: {settings.STORAGE_BACKEND}")
    print(f"Bucket R2:      {settings.MINIO_BUCKET}")
    print(f"Endpoint R2:    {settings.MINIO_ENDPOINT}")
    print("-" * 65)

    # 1. Simular generación del PDF determinista con QR vectorial (CU16)
    folio_prueba = f"REC-R2TEST-{uuid.uuid4().hex[:12]}"
    val_url = f"{settings.PRESCRIPTION_PUBLIC_BASE_URL}/api/v1/recetas/validar/token-test-r2"
    qr_matrix, _ = encode_qr_matrix(val_url)

    pdf_data = RecetaPdfData(
        clinica_nombre="Hospital San Juan de Dios (Prueba R2)",
        folio=folio_prueba,
        fecha_emision="2026-10-06",
        fecha_vencimiento="2026-11-06",
        paciente_nombre="Paciente Prueba R2",
        medico_nombre="Dr. Especialista Telemedicina",
        medico_matricula="MED-9988-R2",
        medico_especialidad="Medicina General",
        id_consulta=999,
        indicaciones_generales="Tomar medicamentos según horario establecido.",
        detalles=[
            RecetaPdfDetalle(
                nombre="Paracetamol",
                principio_activo="Paracetamol",
                concentracion="500 mg",
                forma_farmaceutica="Comprimidos",
                dosis="1 comprimido",
                frecuencia="cada 8 horas",
                duracion="3 dias",
                via_administracion="ORAL",
                cantidad=10,
                indicaciones="Despues de alimentos",
            )
        ],
        algoritmo_firma="ED25519",
        key_id=settings.PRESCRIPTION_SIGNING_KEY_ID or "key-r2-test",
        firma_digital="firma_simulada_ed25519_base64_r2_test",
        validation_url=val_url,
        qr_matrix=qr_matrix,
    )

    print("[1/5] Generando PDF determinista vectorial CU16...")
    pdf_bytes = build_receta_pdf(pdf_data)
    expected_sha = hashlib.sha256(pdf_bytes).hexdigest()
    print(f"      OK -> PDF generado en memoria ({len(pdf_bytes)} bytes)")
    print(f"      OK -> Hash SHA-256 local: {expected_sha}")

    # 2. Almacenar en Cloudflare R2 usando DocumentStorage
    print("[2/5] Almacenando receta en Cloudflare R2 vía storage.store...")
    filename = f"receta_{folio_prueba}.pdf"
    key, stored_sha = storage.store(filename, pdf_bytes, "application/pdf")
    print(f"      OK -> Guardado con object_key: {key}")
    try:
        if stored_sha != expected_sha:
            raise RuntimeError("El hash devuelto no coincide")
        # 3. Comprobar existencia directa en Cloudflare R2 usando cliente S3
        print("[3/5] Verificando objeto físicamente en Cloudflare R2...")
        s3 = boto3.client(
            "s3",
            endpoint_url=settings.MINIO_ENDPOINT,
            aws_access_key_id=settings.MINIO_ACCESS_KEY,
            aws_secret_access_key=settings.MINIO_SECRET_KEY,
            region_name="auto",
        )
        head = s3.head_object(Bucket=settings.MINIO_BUCKET, Key=key)
        print(f"      OK -> Cloudflare R2 confirma existencia: Tamaño={head['ContentLength']} bytes, Type={head['ContentType']}")

        # 4. Descargar y validar integridad (como lo hace el endpoint GET /api/v1/recetas/{id}/pdf)
        print("[4/5] Simulando descarga de receta con verificación criptográfica...")
        descargado = storage.read(key)
        if descargado is None or hashlib.sha256(descargado).hexdigest() != expected_sha:
            raise RuntimeError("Fallo de integridad SHA-256 en descarga")
        print(f"      OK -> Descargado de R2 y verificado íntegramente ({len(descargado)} bytes).")
    finally:
        print("[5/5] Limpiando archivo de prueba en R2 con storage.delete...")
        if not storage.delete(key):
            raise RuntimeError(f"Fallo al eliminar archivo de prueba en R2: {key}")
        print("      OK -> Archivo de prueba eliminado correctamente de Cloudflare R2.")

    print("=" * 65)
    print(" RESULTADO: escritura, lectura, integridad y limpieza verificadas en R2")
    print("=" * 65)


if __name__ == "__main__":
    run_test()
