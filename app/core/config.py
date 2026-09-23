from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="APP_", extra="ignore")

    env: str = "development"
    secret_key: str = Field(min_length=32)
    credential_encryption_key: str
    database_url: str = "postgresql+asyncpg://efakture:efakture@localhost:5432/efakture"
    access_token_minutes: int = Field(default=30, ge=5, le=1440)
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


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
