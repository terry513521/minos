from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
engine = create_async_engine(settings.database_url, echo=False)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session


async def init_db() -> None:
    from app import models  # noqa: F401
    from app.config import get_settings
    from app.services.history_import import maybe_import_default_history

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _ensure_history_columns(conn)
        await _ensure_worker_columns(conn)

    await _maybe_sync_fish_database()

    settings = get_settings()
    if settings.history_path_list:
        async with SessionLocal() as session:
            await maybe_import_default_history(session, settings.history_path_list)


async def _ensure_history_columns(conn) -> None:
    """Add columns introduced after first deploy (SQLite has no auto-migrate)."""
    from sqlalchemy import text

    def _migrate(sync_conn):
        cols = {row[1] for row in sync_conn.execute(text("PRAGMA table_info(round_history)"))}
        if "source_key" not in cols:
            sync_conn.execute(
                text("ALTER TABLE round_history ADD COLUMN source_key VARCHAR(256)")
            )
            sync_conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS ix_round_history_source_key "
                    "ON round_history (source_key)"
                )
            )

    await conn.run_sync(_migrate)


async def _maybe_sync_fish_database() -> None:
    """One-time copy of round_history from fish.db when main.db is still empty."""
    import sqlite3
    from pathlib import Path

    backend = Path(__file__).resolve().parents[1]
    main_path = backend / "main.db"
    fish_path = backend / "fish.db"
    if not fish_path.is_file():
        return

    def _sync(_sync_conn) -> None:
        main = sqlite3.connect(main_path)
        try:
            main_history = main.execute("SELECT COUNT(*) FROM round_history").fetchone()[0]
            if main_history > 0:
                return
            fish = sqlite3.connect(fish_path)
            try:
                fish_history = fish.execute("SELECT COUNT(*) FROM round_history").fetchone()[0]
                if fish_history <= 0:
                    return
                cols = [r[1] for r in fish.execute("PRAGMA table_info(round_history)")]
                col_list = ", ".join(f"[{c}]" for c in cols)
                main.execute("ATTACH DATABASE ? AS fish", (str(fish_path),))
                main.execute(
                    f"INSERT OR IGNORE INTO round_history ({col_list}) "
                    f"SELECT {col_list} FROM fish.round_history"
                )
                main.commit()
            finally:
                fish.close()
        finally:
            main.close()

    async with engine.begin() as conn:
        await conn.run_sync(lambda _: _sync(conn))


async def _ensure_worker_columns(conn) -> None:
    """Add worker columns introduced after first deploy."""
    from sqlalchemy import text

    def _migrate(sync_conn):
        cols = {row[1] for row in sync_conn.execute(text("PRAGMA table_info(workers)"))}
        if "health_url" not in cols:
            sync_conn.execute(text("ALTER TABLE workers ADD COLUMN health_url VARCHAR(512)"))

    await conn.run_sync(_migrate)
