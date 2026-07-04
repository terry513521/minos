from app.optimization.optimizer import _runtime_resources


def test_runtime_resources_reads_base_conf():
    settings = type("S", (), {"trial_threads": 4, "trial_memory_gb": 6})()
    threads, memory_gb = _runtime_resources({"threads": 8, "memory_gb": 12}, settings)
    assert threads == 8
    assert memory_gb == 12


def test_runtime_resources_falls_back_to_settings():
    settings = type("S", (), {"trial_threads": 4, "trial_memory_gb": 6})()
    threads, memory_gb = _runtime_resources({"gatk_options": {}}, settings)
    assert threads == 4
    assert memory_gb == 6
