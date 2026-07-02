import pytest

from app.window_utils import resolve_benchmark_window, shrink_window_center


def test_shrink_window_center_5m_to_2m():
    source = "chr21:24742108-29742108"
    shrunk = shrink_window_center(source, 2_000_000)
    assert shrunk == "chr21:26242108-28242108"


def test_shrink_window_noop_when_already_small():
    source = "chr20:10000000-12000000"
    assert shrink_window_center(source, 2_000_000) == source


def test_resolve_benchmark_window_disabled():
    source = "chr21:24742108-29742108"
    benchmark, round_window = resolve_benchmark_window(source, 0)
    assert benchmark == source
    assert round_window is None


def test_resolve_benchmark_window_enabled():
    source = "chr21:24742108-29742108"
    benchmark, round_window = resolve_benchmark_window(source, 2)
    assert round_window == source
    assert benchmark == "chr21:26242108-28242108"


def test_shrink_window_invalid_raises():
    with pytest.raises(ValueError):
        shrink_window_center("not-a-window", 2_000_000)
