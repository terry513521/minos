from app.worker_urls import normalize_worker_urls, resolve_worker_base_url


def test_infer_base_port_from_health_url():
    health = "http://194.163.164.157:8080/health"
    base = "http://194.163.164.157"
    _, normalized = normalize_worker_urls(health, base)
    assert normalized == "http://194.163.164.157:8080"


def test_derive_base_from_health_only():
    health = "http://192.168.1.10:8080/health"
    _, base = normalize_worker_urls(health, None)
    assert base == "http://192.168.1.10:8080"


def test_resolve_worker_base_url():
    url = resolve_worker_base_url(
        "http://194.163.164.157:8080/health",
        "http://194.163.164.157",
    )
    assert url == "http://194.163.164.157:8080"
