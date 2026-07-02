"""Minimal Minos platform client for round-status polling (no bittensor-wallet)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, TypeVar

import httpx
from substrateinterface import Keypair

logger = logging.getLogger(__name__)

T = TypeVar("T")

_AUTH_HEADERS = {"X-Minos-Auth-Version": "2"}
_DEFAULT_DEMO_URI = "//main-platform-poll"


class PlatformClientError(Exception):
    """Base exception for platform client errors."""


class AuthenticationError(PlatformClientError):
    """Authentication failed."""


@dataclass
class PlatformConfig:
    base_url: str
    timeout: float = 60.0


def load_keypair(wallet_uri: str | None) -> Keypair:
    """Load an SR25519 keypair from a substrate URI (default: ephemeral demo key)."""
    return Keypair.create_from_uri(wallet_uri or _DEFAULT_DEMO_URI)


def sign_request(
    keypair: Keypair,
    method: str,
    path: str,
    body: dict[str, Any],
    timestamp: int,
    nonce: str,
) -> str:
    canonical_body = {k: v for k, v in sorted(body.items()) if k not in ("signature", "nonce")}
    body_hash = hashlib.sha256(
        json.dumps(canonical_body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    canonical = f"{method.upper()}|{path}|{body_hash}|{timestamp}|{nonce}"
    return keypair.sign(canonical.encode()).hex()


def _auth_body(keypair: Keypair, method: str, path: str, **fields: Any) -> dict[str, Any]:
    timestamp = int(time.time())
    nonce = uuid.uuid4().hex
    body = {**fields, "timestamp": timestamp}
    body["signature"] = sign_request(keypair, method, path, body, timestamp, nonce)
    body["nonce"] = nonce
    return body


async def _retry_async(
    func: Callable[[], Any],
    *,
    max_retries: int = 2,
    base_delay: float = 1.0,
    retryable_exceptions: tuple[type[Exception], ...] = (
        httpx.TimeoutException,
        httpx.ConnectError,
        httpx.ReadError,
    ),
) -> T:
    last_exception: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            return await func()
        except retryable_exceptions as exc:
            last_exception = exc
            if attempt < max_retries:
                delay = base_delay * (2**attempt)
                logger.warning("Retry %s/%s after %.1fs: %s", attempt + 1, max_retries, delay, exc)
                await asyncio.sleep(delay)
    if last_exception is not None:
        raise last_exception
    raise RuntimeError("retry_async exhausted without exception")


def _validate_base_url(base_url: str) -> str:
    url = base_url.rstrip("/")
    if not url.startswith("https://") and not any(
        url.startswith(f"http://{host}") for host in ("localhost", "127.0.0.1", "[::1]")
    ):
        raise ValueError(f"PLATFORM_URL must use HTTPS (got {url})")
    return url


async def get_round_status(
    *,
    config: PlatformConfig,
    keypair: Keypair,
    demo: bool = False,
) -> dict[str, Any]:
    """Poll Minos round-status (demo or live endpoint)."""
    base_url = _validate_base_url(config.base_url)
    path = "/v2/demo/round-status" if demo else "/v2/round-status"

    async def _do_request() -> dict[str, Any]:
        body = _auth_body(keypair, "POST", path, hotkey=keypair.ss58_address)
        async with httpx.AsyncClient(base_url=base_url, timeout=config.timeout) as client:
            response = await client.post(path, json=body, headers=_AUTH_HEADERS)
            if response.status_code == 401:
                raise AuthenticationError("Invalid signature or miner not registered on subnet")
            if response.status_code != 200:
                raise PlatformClientError(f"Failed to get round status: {response.text}")
            return response.json()

    return await _retry_async(_do_request, max_retries=2)
