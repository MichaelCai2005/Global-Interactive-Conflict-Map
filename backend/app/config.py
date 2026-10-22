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

    # Link boards (app.boards). "auto" uses Claude when Anthropic credentials are set
    # (ANTHROPIC_API_KEY or an `ant auth login` profile) and the gazetteer otherwise.
    board_extractor: str = "auto"
    board_claude_model: str = "claude-opus-5-5"
    # Look up places Claude finds that the events table has never seen (OpenStreetMap).
    board_geocoder: str = "nominatim"
    # Ground heights for exported scenes, so points sit on the terrain (Open-Meteo).
    board_elevation: str = "open-meteo"
    # Browser origins allowed to call the API, e.g. the gods-eye-view globe.
    cors_origins: str = "http://localhost:4173,http://127.0.0.1:4173"
    # NASA FIRMS map key for `python -m app.live firms` (free, firms.modaps.eosdis.nasa.gov).
    firms_map_key: str | None = None

    # Hosting (app.security, app.publish). With ADMIN_TOKEN set, every request that changes
    # data must send it as `Authorization: Bearer <token>`. PUBLIC_MODE marks a public
    # deployment: writes are refused without the token, and the API won't start if the
    # database holds ACLED events, whose license forbids showing them on a public site.
    admin_token: str | None = None
    public_mode: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
