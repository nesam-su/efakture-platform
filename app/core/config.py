from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="APP_", extra="ignore")

    env: str = "development"
    secret_key: str = Field(min_length=32)
    credential_encryption_key: str
    database_url: str = "postgresql+asyncpg://efakture:efakture@localhost:5432/efakture"
    access_token_minutes: int = Field(default=30, ge=5, le=1440)
    login_max_attempts: int = Field(default=5, ge=3, le=20)
    login_window_seconds: int = Field(default=900, ge=60, le=86400)
    login_block_seconds: int = Field(default=900, ge=60, le=86400)
    public_base_url: str = "http://localhost:8000"
    password_reset_minutes: int = Field(default=30, ge=10, le=1440)
    smtp_host: str | None = None
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_starttls: bool = True
    smtp_from_email: str = "noreply@localhost"
    allowed_hosts: Annotated[list[str], NoDecode] = ["localhost", "127.0.0.1"]
    cors_origins: Annotated[list[str], NoDecode] = []
    artifact_storage_path: Path = Path("/data/artifacts")
    max_artifact_bytes: int = Field(default=25 * 1024 * 1024, ge=1024, le=250 * 1024 * 1024)
    worker_poll_seconds: float = Field(default=2.0, ge=0.2, le=60)
    worker_lock_timeout_seconds: int = Field(default=300, ge=30, le=3600)
    sync_interval_seconds: int = Field(default=60, ge=10, le=3600)
    sync_initial_lookback_days: int = Field(default=1, ge=0, le=90)
    sync_overlap_seconds: int = Field(default=60, ge=0, le=600)

    @field_validator("allowed_hosts", "cors_origins", mode="before")
    @classmethod
    def split_csv(cls, value: object) -> object:
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    @field_validator("public_base_url")
    @classmethod
    def validate_public_base_url(cls, value: str) -> str:
        value = value.rstrip("/")
        if not value.startswith(("http://", "https://")):
            raise ValueError("public_base_url mora biti HTTP(S) adresa")
        return value

    @model_validator(mode="after")
    def require_https_in_production(self) -> Settings:
        if self.env == "production" and not self.public_base_url.startswith("https://"):
            raise ValueError("public_base_url mora koristiti HTTPS u produkciji")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
