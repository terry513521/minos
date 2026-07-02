#!/usr/bin/env python3
"""Import round_history.json files into main.db (use --replace to refresh)."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import get_settings
from app.database import async_sessionmaker, engine, init_db
from app.services.history_import import import_history_files


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Clear round_history before import",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Optional JSON paths (default: MAIN_HISTORY_JSON_PATHS)",
    )
    args = parser.parse_args()

    settings = get_settings()
    paths = [Path(p) for p in args.paths] if args.paths else settings.history_path_list
    missing = [p for p in paths if not p.is_file()]
    if missing:
        for path in missing:
            print(f"error: file not found: {path}", file=sys.stderr)
        return 1

    await init_db()
    async with async_sessionmaker(engine)() as db:
        result = await import_history_files(db, paths, replace=args.replace)

    print(f"files: {result.files}")
    print(f"parsed: {result.parsed}")
    print(f"imported: {result.imported}")
    print(f"skipped_unscored: {result.skipped_unscored}")
    print(f"skipped_invalid: {result.skipped_invalid}")
    print(f"skipped_duplicate: {result.skipped_duplicate}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
