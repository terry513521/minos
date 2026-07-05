from __future__ import annotations

from urllib.parse import urlparse, urlunparse


def _strip_trailing_slash(url: str) -> str:
    return url.strip().rstrip("/")


def base_url_from_health_url(health_url: str) -> str | None:
    """Derive worker API root from a health URL (e.g. …:8080/health → …:8080)."""
    cleaned = _strip_trailing_slash(health_url)
    if cleaned.lower().endswith("/health"):
        return cleaned[: -len("/health")] or None
    parsed = urlparse(cleaned)
    # Bare origin (http://host:port) — common when base_url was omitted at register.
    if parsed.scheme and parsed.netloc and (not parsed.path or parsed.path == "/"):
        return cleaned
    return None


def normalize_worker_urls(
    health_url: str | None,
    base_url: str | None,
) -> tuple[str | None, str | None]:
    """Normalize worker endpoints and infer base_url port from health_url when missing."""
    health = _strip_trailing_slash(health_url) if health_url else None
    base = _strip_trailing_slash(base_url) if base_url else None

    if not base and health:
        base = base_url_from_health_url(health)

    if health and base:
        health_parsed = urlparse(health)
        base_parsed = urlparse(base)
        if (
            health_parsed.hostname
            and base_parsed.hostname
            and health_parsed.hostname == base_parsed.hostname
            and health_parsed.port
            and not base_parsed.port
            and health_parsed.scheme == base_parsed.scheme
        ):
            netloc = health_parsed.netloc
            base = urlunparse(
                (
                    base_parsed.scheme,
                    netloc,
                    base_parsed.path or "",
                    "",
                    "",
                    "",
                )
            ).rstrip("/")

    return health, base


def resolve_worker_base_url(health_url: str | None, base_url: str | None) -> str | None:
    """Return the URL used for worker API calls (optimize, best)."""
    _, normalized_base = normalize_worker_urls(health_url, base_url)
    return normalized_base
