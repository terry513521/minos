"""Remove duplicate round_history rows, keeping one row per (run_id, window, tool)."""

from __future__ import annotations

import argparse
import sqlite3
from collections import defaultdict
from pathlib import Path


INSTANCE_SUFFIXES = frozenset({"gatk", "newgatk", "bcftools", "deepvariant", "freebayes"})


def _instance_suffix(source_key: str | None) -> str:
    if not source_key:
        return ""
    last = source_key.rsplit(":", 1)[-1]
    return last if last in INSTANCE_SUFFIXES else ""


def canonical_source_key(
    run_id: str | None,
    window: str,
    tool: str,
    source_key: str | None,
) -> str | None:
    if not run_id:
        return source_key
    instance_id = _instance_suffix(source_key)
    base = f"{tool}:{run_id}:{window}"
    return f"{base}:{instance_id}" if instance_id else base


def _source_priority(source_key: str | None) -> int:
    if not source_key:
        return 99
    if source_key.startswith("api:"):
        return 0
    if source_key.startswith("tuning:") or source_key.startswith("gatk:") or source_key.startswith("newgatk:"):
        return 1
    if source_key.startswith("run:"):
        return 3
    if "round_history (2)" in source_key:
        return 10
    if source_key.startswith("round_history"):
        return 5
    return 4


def dedup_database(db_path: Path, *, dry_run: bool = False) -> dict[str, int]:
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT id, run_id, window, tool, source_key, created_at FROM round_history"
    ).fetchall()

    groups: dict[tuple[str, str, str, str], list[tuple]] = defaultdict(list)
    solo: list[tuple] = []
    for row in rows:
        row_id, run_id, window, tool, source_key, created_at = row
        if run_id is None:
            solo.append(row)
            continue
        groups[(run_id, window, tool, _instance_suffix(source_key))].append(row)

    delete_ids: list[str] = []
    for group in groups.values():
        group.sort(key=lambda item: (_source_priority(item[4]), item[5] or ""))
        delete_ids.extend(item[0] for item in group[1:])

    if not dry_run and delete_ids:
        conn.executemany("DELETE FROM round_history WHERE id = ?", [(row_id,) for row_id in delete_ids])

    if not dry_run:
        for row_id, run_id, window, tool, source_key, _created_at in conn.execute(
            "SELECT id, run_id, window, tool, source_key, created_at FROM round_history"
        ):
            new_key = canonical_source_key(run_id, window, tool, source_key)
            if new_key and new_key != source_key:
                conn.execute(
                    "UPDATE round_history SET source_key = ? WHERE id = ?",
                    (new_key, row_id),
                )

    if not dry_run:
        conn.commit()

    remaining = len(rows) - len(delete_ids)
    conn.close()
    return {
        "total": len(rows),
        "deleted": len(delete_ids),
        "remaining": remaining,
        "solo_rows": len(solo),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "databases",
        nargs="*",
        type=Path,
        help="SQLite database paths (default: main.db and fish.db next to this script)",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    backend = Path(__file__).resolve().parents[1]
    paths = args.databases or [backend / "main.db", backend / "fish.db"]

    for path in paths:
        if not path.is_file():
            print(f"{path}: skip (not found)")
            continue
        stats = dedup_database(path, dry_run=args.dry_run)
        mode = "would delete" if args.dry_run else "deleted"
        print(
            f"{path}: {stats['total']} rows -> {stats['remaining']} remaining "
            f"({mode} {stats['deleted']}, kept {stats['solo_rows']} rows without run_id)"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
