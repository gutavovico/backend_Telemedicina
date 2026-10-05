from typing import List
from pathlib import Path
from pydantic import SecretStr
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

    # ------------------------------------------------------------------ #
    # CU23 - Control de inactividad y cierre automático de sesión
    # ------------------------------------------------------------------ #
    # Ventana de inactividad por sesión. Al superarla, el backend revoca el `jti`
    # de ESA sesión y devuelve 401, sin afectar a los demás dispositivos del
    # usuario que sigan activos.
    INACTIVITY_TIMEOUT_MINUTES: int = 15
    # Margen con el que las interfaces avisan antes del cierre, para que el
    # usuario pueda seguir la sesión. El contador se calcula sobre el servidor.
    INACTIVITY_WARNING_SECONDS: int = 60
    # No se escribe `ultima_actividad` en cada petición si la marca es más
    # reciente que este intervalo: acota el coste de una escritura por petición.
    INACTIVITY_TOUCH_INTERVAL_SECONDS: int = 60

    # ------------------------------------------------------------------ #
    # CU23 - Canal de recuperación por SMS (deshabilitado - solo email)
    # ------------------------------------------------------------------ #
    # Proveedor de SMS: "console" (valor por defecto, no llama a terceros) o
    # "twilio". Se elige por configuracion y ambos cumplen el mismo puerto.
    SMS_PROVIDER: str = "console"
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_FROM_NUMBER: str = ""
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = "admin.telemedicina@gmail.com"
    SMTP_PASSWORD: str = "tzwmnnlzksgsonjq"
    SMTP_FROM: str = "admin.telemedicina@gmail.com"

    # CORS
    CORS_ORIGINS: str = "http://localhost:4200,https://frontend-telemedicina-weld.vercel.app"

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

    # Recetas médicas digitales CU16 (firma Ed25519 + canonicalización RFC 8785/JCS + QR).
    # Las claves privadas nunca se almacenan en la base ni en el repositorio.
    # Ver specs/openspec/contracts/prescriptions.md §5.
    PRESCRIPTION_SIGNING_PRIVATE_KEY_BASE64: str = ""
    PRESCRIPTION_SIGNING_KEY_ID: str = "prescriptions-2026-01"
    PRESCRIPTION_VERIFICATION_KEYS_JSON: str = "{}"
    PRESCRIPTION_TELEMETRY_HMAC_KEY: str = ""
    PRESCRIPTION_PUBLIC_BASE_URL: str = "http://localhost:8000"
    PRESCRIPTION_DEFAULT_VALIDITY_DAYS: int = 90
    # Proxies de confianza para resolver IP real tras X-Forwarded-For.
    # Vacía por defecto: no se confía en ningún proxy y se ignora el encabezado.
    # Ejemplo: "10.0.0.1, 192.168.1.10". Ver CU16 decisión 5.
    TRUSTED_PROXY_IPS: str = ""

    # CU22: interpretación de texto con Groq (nunca se envía al cliente).
    GROQ_API_KEY: SecretStr = SecretStr("")
    GROQ_MODEL: str = "openai/gpt-oss-20b"
    GROQ_TIMEOUT_SECONDS: float = 10.0
    GROQ_MAX_OUTPUT_TOKENS: int = 1000
    GROQ_TRANSCRIPTION_MODEL: str = "whisper-large-v3"
    GROQ_TRANSCRIPTION_TIMEOUT_SECONDS: float = 30.0

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
        env_file=Path(__file__).resolve().parents[2] / ".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @property
    def DATABASE_URL(self) -> str:
        return f"postgresql+psycopg2://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

    @property
    def cors_origins_list(self) -> List[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]


settings = Settings()
