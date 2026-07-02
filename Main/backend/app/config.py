from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_prefix="MAIN_",
    )

    database_url: str = "sqlite+aiosqlite:///./main.db"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    api_prefix: str = "/api/v1"
    host: str = "0.0.0.0"
    port: int = 8000
    serve_frontend: bool = True

    # Minos platform round polling (optional)
    platform_enabled: bool = True
    platform_url: str = "https://api.theminos.ai"
    platform_timeout: float = 60.0
    platform_poll_seconds: int = 10
    platform_demo_mode: bool = True
    platform_wallet_uri: str | None = None
    platform_wallet_name: str | None = None
    platform_wallet_hotkey: str | None = None

    # Comma-separated Minos tuning round_history.json paths (imported on first startup)
    history_json_paths: str = (
        "/root/workspacke/minos/instances/gatk/tuning/data/round_history.json,"
        "/root/workspacke/minos/instances/newgatk/tuning/data/round_history.json"
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def history_path_list(self) -> list["Path"]:
        from pathlib import Path

        return [Path(p.strip()) for p in self.history_json_paths.split(",") if p.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
