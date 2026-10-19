from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://conflict:conflict@localhost:5432/conflict"
    # Two violent events from different sources within this distance and day window
    # are treated as reports of the same incident.
    link_radius_km: float = 25.0
    link_day_window: int = 1
    # ACLED account login, used by `ingest download acled` to get an API token.
    acled_email: str | None = None
    acled_password: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
