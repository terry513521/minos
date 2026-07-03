from app.core.window import (
    parse_window,
    resolve_benchmark_window,
    shrink_window_center,
    shrink_window_random,
)


def test_shrink_window_center():
    window = "chr21:1000000-6000000"
    shrunk = shrink_window_center(window, 2_000_000)
    assert shrunk == "chr21:2500000-4500000"


def test_shrink_window_random_deterministic():
    window = "chr21:1000000-6000000"
    a = shrink_window_random(window, 3_000_000, seed="job-abc")
    b = shrink_window_random(window, 3_000_000, seed="job-abc")
    assert a == b
    assert a != window


def test_shrink_window_random_inside_parent():
    window = "chr21:1-5000000"
    shrunk = shrink_window_random(window, 3_000_000, seed="job-xyz")
    chrom, start, end = parse_window(shrunk)
    parent_chrom, parent_start, parent_end = parse_window(window)
    assert chrom == parent_chrom
    assert end - start == 3_000_000
    assert start >= parent_start
    assert end <= parent_end


def test_resolve_benchmark_window_no_crop():
    benchmark, source = resolve_benchmark_window("chr21:1-5000000", 0)
    assert benchmark == "chr21:1-5000000"
    assert source is None


def test_resolve_benchmark_window_full_5m_round():
    benchmark, source = resolve_benchmark_window("chr21:1-5000000", 5, seed="job-1")
    assert benchmark == "chr21:1-5000000"
    assert source is None


def test_resolve_benchmark_window_random_slice():
    benchmark, source = resolve_benchmark_window("chr21:1-5000000", 3, seed="job-1")
    assert source == "chr21:1-5000000"
    _, start, end = parse_window(benchmark)
    assert end - start == 3_000_000
    assert start >= 1
    assert end <= 5_000_000
