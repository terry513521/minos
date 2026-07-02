from __future__ import annotations

import hashlib
import random
import re

WINDOW_RE = re.compile(r"^(chr(?:[1-9]|1[0-9]|2[0-2]|X|Y|M)):(\d+)-(\d+)$", re.IGNORECASE)


def parse_window(window: str) -> tuple[str, int, int]:
    match = WINDOW_RE.match(window.strip())
    if not match:
        raise ValueError(f"Invalid window format: {window}")
    chrom = match.group(1)
    start = int(match.group(2))
    end = int(match.group(3))
    if start >= end:
        raise ValueError(f"Invalid window coordinates: {window}")
    return chrom, start, end


def format_window(chrom: str, start: int, end: int) -> str:
    return f"{chrom}:{start}-{end}"


def _rng_for_seed(seed: str | int) -> random.Random:
    if isinstance(seed, int):
        return random.Random(seed)
    digest = hashlib.sha256(str(seed).encode()).hexdigest()
    return random.Random(int(digest[:16], 16))


def shrink_window_center(window: str, target_bp: int) -> str:
    """Return a centered sub-window of at most target_bp inside window."""
    if target_bp <= 0:
        return window.strip()

    chrom, start, end = parse_window(window)
    span = end - start
    if span <= target_bp:
        return format_window(chrom, start, end)

    center = start + span // 2
    half = target_bp // 2
    sub_start = max(start, center - half)
    sub_end = sub_start + target_bp
    if sub_end > end:
        sub_end = end
        sub_start = max(start, sub_end - target_bp)

    return format_window(chrom, sub_start, sub_end)


def shrink_window_random(window: str, target_bp: int, *, seed: str | int) -> str:
    """Return a random sub-window of at most target_bp inside window (seed-stable)."""
    if target_bp <= 0:
        return window.strip()

    chrom, start, end = parse_window(window)
    span = end - start
    if span <= target_bp:
        return format_window(chrom, start, end)

    max_offset = span - target_bp
    offset = _rng_for_seed(seed).randint(0, max_offset)
    sub_start = start + offset
    sub_end = sub_start + target_bp
    return format_window(chrom, sub_start, sub_end)


def resolve_benchmark_window(
    window: str,
    subwindow_mb: int,
    *,
    seed: str | int | None = None,
) -> tuple[str, str | None]:
    """(benchmark_window, source_window_if_shrunk).

    When subwindow_mb > 0 and the dispatched window is larger, pick a random
    sub-window of that size inside the dispatch region. The same seed always
    yields the same slice (use job_id so all trials in one job share one region).
    """
    source = window.strip()
    if subwindow_mb <= 0:
        return source, None
    slice_seed = seed if seed is not None else source
    benchmark = shrink_window_random(source, subwindow_mb * 1_000_000, seed=slice_seed)
    if benchmark == source:
        return source, None
    return benchmark, source
