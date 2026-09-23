from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="APP_", extra="ignore")

    env: str = "development"
    secret_key: str = Field(min_length=32)
    credential_encryption_key: str
    database_url: str = "postgresql+asyncpg://efakture:efakture@localhost:5432/efakture"
    access_token_minutes: int = Field(default=30, ge=5, le=1440)
    allowed_hosts: list[str] = ["localhost", "127.0.0.1"]
    cors_origins: list[str] = []

    @field_validator("allowed_hosts", "cors_origins", mode="before")
    @classmethod
    def split_csv(cls, value: object) -> object:
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
