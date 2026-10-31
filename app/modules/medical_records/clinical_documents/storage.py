"""Servicio de almacenamiento para documentos clínicos (CU12).

Abstrae dos backends:
- ``local`` (default): guarda los archivos bajo ``STORAGE_LOCAL_DIR`` y genera
  URLs firmadas locales que se sirven vía el endpoint autenticado
  ``GET /api/v1/documentos/{id}/file``.
- ``minio``: almacenamiento S3-compatible con presigned URLs reales
  (expiración configurada en ``DOCUMENTO_URL_EXPIRACION``, máx 900 s).
"""
import hashlib
import os
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import quote

from app.core.config import settings


def _sha256_hex(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


class StorageError(Exception):
    """Error genérico del servicio de almacenamiento."""


def _sanitize_key(key: str) -> str:
    if not key or not key.strip():
        raise StorageError("Clave de archivo vacía")
    cleaned = key.strip()
    if cleaned.startswith("/"):
        cleaned = cleaned[1:]
    if (
        cleaned.startswith("api/")
        or cleaned.startswith("http://")
        or cleaned.startswith("https://")
        or "\\" in cleaned
        or ".." in cleaned
    ):
        raise StorageError(f"Ruta de archivo no permitida: {key}")
    return cleaned


class DocumentStorage:
    """Abstracción de almacenamiento de archivos para documentos clínicos."""

    def __init__(self) -> None:
        self.backend = settings.STORAGE_BACKEND.lower()
        if self.backend == "minio":
            self._minio_client = self._build_minio_client()
        self.local_dir = Path(settings.STORAGE_LOCAL_DIR).resolve()
        self.local_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ #
    # Backends
    # ------------------------------------------------------------------ #
    def _build_minio_client(self):
        try:
            import boto3
        except ImportError as exc:  # pragma: no cover - depende del entorno
            raise StorageError(
                "Backend de almacenamiento 'minio' requiere el paquete 'boto3'. "
                "Instale con: pip install boto3 o use STORAGE_BACKEND=local."
            ) from exc

        endpoint = settings.MINIO_ENDPOINT
        if not endpoint.startswith(("http://", "https://")):
            scheme = "https" if settings.MINIO_SECURE else "http"
            endpoint = f"{scheme}://{endpoint}"

        return boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=settings.MINIO_ACCESS_KEY,
            aws_secret_access_key=settings.MINIO_SECRET_KEY,
            region_name="us-east-1",
        )

    # ------------------------------------------------------------------ #
    # API pública
    # ------------------------------------------------------------------ #
    def store(self, name: str, content: bytes, content_type: str = "application/pdf") -> Tuple[str, str]:
        """Almacena un archivo y devuelve (object_key, sha256)."""
        sha = _sha256_hex(content)
        safe_name = str(name).replace("\\", "_").replace("/", "_")
        key = f"documentos/{sha[:2]}/{sha[2:4]}/{safe_name}"
        if self.backend == "minio":
            self._minio_client.put_object(
                Bucket=settings.MINIO_BUCKET,
                Key=key,
                Body=content,
                ContentType=content_type,
            )
        else:
            base_dir = self.local_dir.resolve()
            dest = base_dir / key
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(content)
        return key, sha

    def generate_download_url(self, key: str, file_name: str, content_type: str = "application/pdf") -> Tuple[str, int]:
        """Genera una URL de descarga temporal. Devuelve (url, expira_en_segundos)."""
        expires = min(max(settings.DOCUMENTO_URL_EXPIRACION, 60), 900)

        if self.backend == "minio":
            url = self._minio_client.generate_presigned_url(
                "get_object",
                Params={"Bucket": settings.MINIO_BUCKET, "Key": key},
                ExpiresIn=expires,
            )
            return url, expires

        # Backend local: URL del servicio FastAPI autenticado (sin criterios de expiración real;
        # el acceso se controla con JWT). El `expira_en` conserva el contracto.
        base = settings.STORAGE_PUBLIC_BASE_URL.rstrip("/")
        safe_name = quote(file_name)
        url = f"{base}/api/v1/documentos/file/{quote(key, safe='')}?nombre={safe_name}"
        return url, expires

    def read(self, key: str) -> Optional[bytes]:
        """Lee el contenido de un archivo (usado por el backend local)."""
        if self.backend == "minio":
            resp = self._minio_client.get_object(Bucket=settings.MINIO_BUCKET, Key=key)
            return resp["Body"].read()

        base_dir = self.local_dir.resolve()
        file_path = (base_dir / Path(key)).resolve()
        if not file_path.is_relative_to(base_dir) or not file_path.is_file():
            return None
        return file_path.read_bytes()

    def delete(self, key: str) -> bool:
        """Elimina un archivo almacenado (usado para compensación transaccional)."""
        if self.backend == "minio":
            try:
                self._minio_client.delete_object(Bucket=settings.MINIO_BUCKET, Key=key)
                return True
            except Exception:
                return False

        base_dir = self.local_dir.resolve()
        file_path = (base_dir / Path(key)).resolve()
        if not file_path.is_relative_to(base_dir) or not file_path.is_file():
            return False
        try:
            file_path.unlink()
            return True
        except Exception:
            return False


storage = DocumentStorage()