from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.conf_hash import conf_cache_key
from app.config import Settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VcfCacheHit:
    key: str
    vcf_path: Path
    score: float
    raw_score: float
    variant_count: int

    def to_result_fields(self) -> dict[str, Any]:
        return {
            "success": True,
            "score": self.score,
            "raw_score": self.raw_score,
            "variant_count": self.variant_count,
            "cached": True,
        }


class VcfCache:
    def __init__(self, settings: Settings) -> None:
        root = Path(settings.data_dir)
        if not root.is_absolute():
            from app.assets import WORKER_ROOT

            root = WORKER_ROOT / root
        self._root = (root / settings.vcf_cache_dir).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    def _entry_dir(self, key: str) -> Path:
        return self._root / key[:2] / key

    def lookup(
        self,
        *,
        window: str,
        tool: str,
        bam_path: str,
        conf: dict[str, Any],
    ) -> VcfCacheHit | None:
        key = conf_cache_key(window=window, tool=tool, bam_path=bam_path, conf=conf)
        entry_dir = self._entry_dir(key)
        meta_path = entry_dir / "meta.json"
        vcf_path = entry_dir / "query.vcf.gz"
        if not meta_path.exists() or not vcf_path.exists():
            return None

        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

        return VcfCacheHit(
            key=key,
            vcf_path=vcf_path,
            score=float(meta["score"]),
            raw_score=float(meta["raw_score"]),
            variant_count=int(meta.get("variant_count") or 0),
        )

    def store(
        self,
        *,
        window: str,
        tool: str,
        bam_path: str,
        conf: dict[str, Any],
        source_vcf: Path,
        score: float,
        raw_score: float,
        variant_count: int,
    ) -> str:
        key = conf_cache_key(window=window, tool=tool, bam_path=bam_path, conf=conf)
        entry_dir = self._entry_dir(key)
        entry_dir.mkdir(parents=True, exist_ok=True)
        target_vcf = entry_dir / "query.vcf.gz"
        shutil.copy2(source_vcf, target_vcf)
        meta = {
            "window": window,
            "tool": tool,
            "bam_path": bam_path,
            "conf": conf,
            "score": score,
            "raw_score": raw_score,
            "variant_count": variant_count,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        (entry_dir / "meta.json").write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")
        logger.info("VCF cache store: %s (score %.4f)", key[:12], score)
        return key
