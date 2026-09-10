from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Base de Datos PostgreSQL
    DB_NAME: str = "telemedicina"
    DB_USER: str = "postgres"
    DB_PASSWORD: str = "12345"
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432

    # JWT
    JWT_SECRET_KEY: str = "clave_secreta_super_segura_telemedicina_2026_jwt_access"
    JWT_REFRESH_SECRET_KEY: str = "clave_secreta_super_segura_telemedicina_2026_jwt_refresh"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Recuperación de contraseña (CU23)
    # Clave usada para derivar el código de 6 dígitos con HMAC (sin BD)
    JWT_RESET_SECRET_KEY: str = "clave_secreta_super_segura_telemedicina_2026_reset_code"
    # Ventana de validez del código (minutos)
    RESET_CODE_TTL_MINUTES: int = 30
    # Intentos fallidos permitidos antes del bloqueo
    RESET_CODE_MAX_ATTEMPTS: int = 5
    # Tiempo de bloqueo tras exceder intentos (minutos)
    RESET_CODE_LOCKOUT_MINUTES: int = 15

    # Envío de correo (SMTP). Con EMAIL_ENABLED=False el código se muestra en consola.
    EMAIL_ENABLED: bool = False
    EMAIL_FROM_NAME: str = "Telemedicina - Hospital San Juan de Dios"
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "no-reply@telemedicina.com"

    # CORS
    CORS_ORIGINS: str = "http://localhost:4200"

    # Almacenamiento de documentos (CU12)
    STORAGE_BACKEND: str = "local"  # local | minio
    STORAGE_LOCAL_DIR: str = "storage_documents"
    STORAGE_PUBLIC_BASE_URL: str = "http://localhost:8000"
    # MinIO (S3-compatible)
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = ""
    MINIO_SECRET_KEY: str = ""
    MINIO_BUCKET: str = "telemedicina-documentos"
    MINIO_SECURE: bool = False
    # Expiración de URL firmada en segundos (máximo 900)
    DOCUMENTO_URL_EXPIRACION: int = 900

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @property
    def DATABASE_URL(self) -> str:
        return f"postgresql://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

    @property
    def cors_origins_list(self) -> List[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]


settings = Settings()
