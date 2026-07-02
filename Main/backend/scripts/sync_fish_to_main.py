#!/usr/bin/env python3
"""Copy round_history (and workers) from fish.db into main.db when main is empty."""

from __future__ import annotations

import sqlite3
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
MAIN = BACKEND / "main.db"
FISH = BACKEND / "fish.db"


def _count(conn: sqlite3.Connection, table: str) -> int:
    try:
        return int(conn.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()[0])
    except sqlite3.OperationalError:
        return -1


def main() -> int:
    if not FISH.is_file():
        print("fish.db not found — nothing to sync")
        return 0

    main = sqlite3.connect(MAIN)
    fish = sqlite3.connect(FISH)

    fish_history = _count(fish, "round_history")
    main_history = _count(main, "round_history")
    if fish_history <= 0:
        print("fish.db has no round_history rows")
        return 0
    if main_history > 0:
        print(f"main.db already has {main_history} history rows — skipped")
        return 0

    cols = [r[1] for r in fish.execute("PRAGMA table_info(round_history)")]
    col_list = ", ".join(f"[{c}]" for c in cols)
    main.execute(f"ATTACH DATABASE ? AS fish", (str(FISH),))
    main.execute(
        f"INSERT OR IGNORE INTO round_history ({col_list}) "
        f"SELECT {col_list} FROM fish.round_history"
    )
    main.commit()
    copied = _count(main, "round_history")
    print(f"Synced {copied} round_history rows from fish.db -> main.db")

    if _count(fish, "workers") > 0 and _count(main, "workers") == 0:
        wcols = [r[1] for r in fish.execute("PRAGMA table_info(workers)")]
        wlist = ", ".join(f"[{c}]" for c in wcols)
        main.execute(
            f"INSERT OR IGNORE INTO workers ({wlist}) SELECT {wlist} FROM fish.workers"
        )
        main.commit()
        print(f"Synced {_count(main, 'workers')} workers")

    main.close()
    fish.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
