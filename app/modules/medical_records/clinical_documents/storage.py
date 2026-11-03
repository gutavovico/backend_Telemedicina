"""Servicio de almacenamiento para documentos clínicos (CU12) y recetas médicas (CU16).

Abstrae backends:
- ``local`` (default): guarda los archivos bajo ``STORAGE_LOCAL_DIR`` y genera
  URLs autenticadas vía el endpoint ``GET /api/v1/documentos/{id}/file``.
- ``minio`` / ``r2`` / ``s3``: almacenamiento S3-compatible (MinIO, Cloudflare R2, AWS S3)
  con soporte de presigned URLs y operaciones de lectura/escritura deterministas.
"""
import hashlib
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import quote

from app.core.config import settings


def _sha256_hex(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


class StorageError(Exception):
    """Error genérico del servicio de almacenamiento."""


def _sanitize_key(key: str) -> str:
    """Valida y normaliza la clave de almacenamiento evitando traversal o URLs absolutas."""
    if not key or not str(key).strip():
        raise StorageError("Clave de almacenamiento vacía o inválida")
    raw = str(key).strip()
    if "\\" in raw or ".." in raw:
        raise StorageError(f"Ruta con caracteres no permitidos: {key}")
    cleaned = raw.lstrip("/")
    if cleaned.startswith(("http://", "https://", "api/")):
        raise StorageError(f"Ruta absoluta o prefijo no permitido: {key}")
    return cleaned


class DocumentStorage:
    """Abstracción de almacenamiento de archivos para documentos clínicos y recetas."""

    def __init__(self) -> None:
        self.backend = settings.STORAGE_BACKEND.lower()
        if self.backend in ("minio", "r2", "s3"):
            self._s3_client = self._build_s3_client()
        else:
            self._s3_client = None
        self.local_dir = Path(settings.STORAGE_LOCAL_DIR).resolve()
        self.local_dir.mkdir(parents=True, exist_ok=True)

    @property
    def _minio_client(self):
        """Compatibilidad hacia atrás con código o tests que inspeccionen `_minio_client`."""
        return self._s3_client

    # ------------------------------------------------------------------ #
    # Backends
    # ------------------------------------------------------------------ #
    def _build_s3_client(self):
        try:
            import boto3
        except ImportError as exc:  # pragma: no cover - depende del entorno
            raise StorageError(
                f"Backend de almacenamiento '{self.backend}' requiere el paquete 'boto3'. "
                "Instale con: pip install boto3 o use STORAGE_BACKEND=local."
            ) from exc

        endpoint = settings.MINIO_ENDPOINT.strip()
        if not endpoint.startswith(("http://", "https://")):
            scheme = "https" if settings.MINIO_SECURE else "http"
            endpoint = f"{scheme}://{endpoint}"

        # Normalizar si el endpoint contiene la ruta del bucket al final
        if ".r2.cloudflarestorage.com" in endpoint:
            base_r2, sep, _ = endpoint.partition(".r2.cloudflarestorage.com")
            endpoint = f"{base_r2}{sep}"

        region = "auto" if self.backend == "r2" else "us-east-1"

        return boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=settings.MINIO_ACCESS_KEY,
            aws_secret_access_key=settings.MINIO_SECRET_KEY,
            region_name=region,
        )

    # ------------------------------------------------------------------ #
    # API pública
    # ------------------------------------------------------------------ #
    def store(self, name: str, content: bytes, content_type: str = "application/pdf") -> Tuple[str, str]:
        """Almacena un archivo y devuelve (object_key, sha256)."""
        sha = _sha256_hex(content)
        safe_name = str(name).replace("\\", "_").replace("/", "_")
        key = f"documentos/{sha[:2]}/{sha[2:4]}/{safe_name}"
        clean_key = _sanitize_key(key)

        if self.backend in ("minio", "r2", "s3"):
            self._s3_client.put_object(
                Bucket=settings.MINIO_BUCKET,
                Key=clean_key,
                Body=content,
                ContentType=content_type,
            )
        else:
            dest = self.local_dir / clean_key
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(content)
        return clean_key, sha

    def generate_download_url(self, key: str, file_name: str, content_type: str = "application/pdf") -> Tuple[str, int]:
        """Genera una URL de descarga temporal. Devuelve (url, expira_en_segundos)."""
        clean_key = _sanitize_key(key)
        expires = min(max(settings.DOCUMENTO_URL_EXPIRACION, 60), 900)

        if self.backend in ("minio", "r2", "s3"):
            url = self._s3_client.generate_presigned_url(
                "get_object",
                Params={"Bucket": settings.MINIO_BUCKET, "Key": clean_key},
                ExpiresIn=expires,
            )
            return url, expires

        # Backend local: URL del servicio FastAPI autenticado (sin criterios de expiración real;
        # el acceso se controla con JWT). El `expira_en` conserva el contrato.
        base = settings.STORAGE_PUBLIC_BASE_URL.rstrip("/")
        safe_name = quote(file_name)
        url = f"{base}/api/v1/documentos/file/{quote(clean_key, safe='')}?nombre={safe_name}"
        return url, expires

    def read(self, key: str) -> Optional[bytes]:
        """Lee el contenido de un archivo (usado por el backend local y servicios de descarga)."""
        try:
            clean_key = _sanitize_key(key)
        except StorageError:
            return None

        if self.backend in ("minio", "r2", "s3"):
            try:
                resp = self._s3_client.get_object(Bucket=settings.MINIO_BUCKET, Key=clean_key)
                return resp["Body"].read()
            except Exception:
                return None

        file_path = (self.local_dir / Path(clean_key)).resolve()
        if not file_path.is_relative_to(self.local_dir) or not file_path.is_file():
            return None
        return file_path.read_bytes()

    def delete(self, key: str) -> bool:
        """Elimina un archivo del storage (usado en compensación por rollback o limpieza)."""
        try:
            clean_key = _sanitize_key(key)
        except StorageError:
            return False

        if self.backend in ("minio", "r2", "s3"):
            try:
                self._s3_client.delete_object(Bucket=settings.MINIO_BUCKET, Key=clean_key)
                return True
            except Exception:
                return False

        file_path = (self.local_dir / Path(clean_key)).resolve()
        if not file_path.is_relative_to(self.local_dir) or not file_path.is_file():
            return False
        try:
            file_path.unlink()
            return True
        except Exception:
            return False


storage = DocumentStorage()
