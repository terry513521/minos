from __future__ import annotations

from app.assets import parse_window


def format_window(chrom: str, start: int, end: int) -> str:
    return f"{chrom}:{start}-{end}"


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


def resolve_benchmark_window(window: str, subwindow_mb: int) -> tuple[str, str | None]:
    """(benchmark_window, source_window_if_shrunk)."""
    source = window.strip()
    if subwindow_mb <= 0:
        return source, None
    benchmark = shrink_window_center(source, subwindow_mb * 1_000_000)
    if benchmark == source:
        return source, None
    return benchmark, source
