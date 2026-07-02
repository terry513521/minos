from app.core.window import resolve_benchmark_window, shrink_window_center


def test_shrink_window_center():
    window = "chr21:1000000-6000000"
    shrunk = shrink_window_center(window, 2_000_000)
    assert shrunk == "chr21:2500000-4500000"


def test_resolve_benchmark_window_no_crop():
    benchmark, source = resolve_benchmark_window("chr21:1-5000000", 0)
    assert benchmark == "chr21:1-5000000"
    assert source is None


def test_resolve_benchmark_window_crops():
    benchmark, source = resolve_benchmark_window("chr21:1-5000000", 2)
    assert source == "chr21:1-5000000"
    assert benchmark != source
