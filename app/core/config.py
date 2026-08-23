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

    # CORS
    CORS_ORIGINS: str = "http://localhost:4200"

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
