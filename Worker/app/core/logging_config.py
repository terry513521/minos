"""Worker logging setup — readable app logs, quieter poll endpoints."""

from __future__ import annotations

import logging
import os


class QuietAccessFilter(logging.Filter):
    """Drop high-frequency health/best polls from uvicorn access logs."""

    def __init__(self, quiet_paths: tuple[str, ...] | None = None) -> None:
        super().__init__()
        if quiet_paths is None:
            raw = os.getenv("WORKER_QUIET_ACCESS_PATHS", "/best,/health").strip()
            quiet_paths = tuple(p.strip() for p in raw.split(",") if p.strip())
        self.quiet_paths = quiet_paths

    def filter(self, record: logging.LogRecord) -> bool:
        if not self.quiet_paths:
            return True
        message = record.getMessage()
        for path in self.quiet_paths:
            if f" {path} " in message or f'"{path}' in message:
                return False
        return True


def configure_worker_logging(
    log_level: str | None = None,
    *,
    quiet_paths: tuple[str, ...] | None = None,
) -> None:
    level_name = (log_level or os.getenv("WORKER_LOG_LEVEL", "info")).upper()
    level = getattr(logging, level_name, logging.INFO)

    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(
            level=level,
            format="%(levelname)s:     %(message)s",
        )
    else:
        root.setLevel(level)

    for name in ("app", "tuning", "utils", "templates"):
        logging.getLogger(name).setLevel(level)

    access_logger = logging.getLogger("uvicorn.access")
    access_logger.addFilter(QuietAccessFilter(quiet_paths))
