from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _default_history_json_paths() -> str:
    root = _repo_root()
    paths = [
        root / "instances" / "gatk" / "tuning" / "data" / "round_history.json",
        root / "instances" / "newgatk" / "tuning" / "data" / "round_history.json",
    ]
    return ",".join(str(p) for p in paths)


def _backend_dir() -> Path:
    return Path(__file__).resolve().parents[1]


def _history_row_count(db_path: Path) -> int:
    if not db_path.is_file():
        return 0
    try:
        import sqlite3

        conn = sqlite3.connect(db_path)
        count = conn.execute("SELECT COUNT(*) FROM round_history").fetchone()[0]
        conn.close()
        return int(count)
    except Exception:
        return 0


def _default_database_url() -> str:
    """Prefer fish.db when main.db is empty but fish.db has imported history."""
    backend = _backend_dir()
    main_count = _history_row_count(backend / "main.db")
    fish_count = _history_row_count(backend / "fish.db")
    if fish_count > 0 and main_count == 0:
        return "sqlite+aiosqlite:///./fish.db"
    return "sqlite+aiosqlite:///./main.db"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_prefix="MAIN_",
    )

    database_url: str = Field(default_factory=_default_database_url)
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
    # Substrate URI for signed platform requests (default: ephemeral demo key)
    platform_wallet_uri: str | None = None

    # Comma-separated Minos tuning round_history.json paths (imported on first startup)
    history_json_paths: str = Field(default_factory=_default_history_json_paths)
    # Remote portfolio rounds API (merged into round_history on startup and via POST /history/sync-rounds)
    history_api_url: str = "http://192.168.131.16:7860/api/rounds"
    history_api_timeout: float = 60.0
    history_api_sync_on_startup: bool = True

    # Portfolio rounds dashboard (/history/rounds)
    portfolio_rounds_cache_path: str = ""
    portfolio_rounds_poll_seconds: int = 1800
    portfolio_rounds_poll_enabled: bool = True
    portfolio_rounds_sync_on_startup: bool = True

    @property
    def portfolio_rounds_path(self) -> Path:
        root = _repo_root() / "rounds.json"
        return root if root.is_file() else Path()

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def history_path_list(self) -> list[Path]:
        return [Path(p.strip()) for p in self.history_json_paths.split(",") if p.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
