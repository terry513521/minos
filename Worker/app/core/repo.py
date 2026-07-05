"""Import path setup for bundled Worker vendor libraries."""

from __future__ import annotations

import sys
from pathlib import Path

from app.paths import get_vendor_root


def ensure_repo_imports() -> Path:
    """Ensure bundled templates/utils/tuning are importable."""
    root = get_vendor_root()
    templates_dir = root / "templates"
    tuning_giab = root / "tuning" / "giab" / "data.py"
    if not templates_dir.is_dir() or not tuning_giab.is_file():
        raise RuntimeError(
            f"Worker vendor bundle incomplete at {root}. "
            "Expected vendor/templates/ and vendor/tuning/giab/."
        )
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    return root
