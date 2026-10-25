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
    # Browser origins allowed to call the API: the gods-eye-view globe, and the frontend
    # when it's hosted on another site, e.g. https://<user>.github.io (no path).
    cors_origins: str = "http://localhost:4173,http://127.0.0.1:4173"
    # Screen GDELT violence with the headline model (app.headline_model) as well as the word
    # rules, when fastembed is installed (the "screen" extra).
    gdelt_headline_model: bool = True
    # NASA FIRMS map key for `python -m app.live firms` (free, firms.modaps.eosdis.nasa.gov).
    firms_map_key: str | None = None

    # Hosting (app.security, app.publish). With ADMIN_TOKEN set, every request that changes
    # data must send it as `Authorization: Bearer <token>`. PUBLIC_MODE marks a public
    # deployment: writes are refused without the token, and the API won't start if the
    # database holds ACLED events, whose license forbids showing them on a public site.
    admin_token: str | None = None
    public_mode: bool = False

    # Accounts (app.auth). People sign up with an email and password and keep their own
    # watchlist, tasks, boards and saved searches. A sign-in lasts SESSION_DAYS. Session
    # cookies are marked Secure (HTTPS only) on a public deployment unless SECURE_COOKIES
    # says otherwise. SIGNUPS_OPEN=false stops new accounts but lets existing ones sign in.
    session_days: int = 30
    secure_cookies: bool | None = None
    signups_open: bool = True
    # The built frontend (frontend/dist) for app.site to serve beside the API.
    static_dir: str | None = None

    @property
    def allowed_origins(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
