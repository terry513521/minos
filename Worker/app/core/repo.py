"""Import path setup for minos_subnet templates and scoring."""

from __future__ import annotations

import sys

from app.paths import WORKER_ROOT, get_repo_root


def ensure_repo_imports() -> Path:
    root = get_repo_root()
    root_str = str(root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    templates_dir = root / "templates"
    if not templates_dir.exists():
        raise RuntimeError(
            f"Minos templates not found at {templates_dir}. "
            "Set WORKER_REPO_ROOT to the minos_subnet checkout."
        )
    return root
