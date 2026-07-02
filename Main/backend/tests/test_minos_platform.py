"""Tests for Minos platform request signing."""

import hashlib
import json
import unittest

from substrateinterface import Keypair

from app.services.minos_platform import sign_request


class MinosPlatformSignTests(unittest.TestCase):
    def test_signature_verifies(self) -> None:
        keypair = Keypair.create_from_uri("//main-platform-poll")
        body = {"hotkey": keypair.ss58_address, "round_id": "r1"}
        timestamp = 1_700_000_000
        nonce = "deadbeef1234"
        sig_hex = sign_request(keypair, "POST", "/v2/demo/round-status", body, timestamp, nonce)
        canonical_body = {k: v for k, v in sorted(body.items()) if k not in ("signature", "nonce")}
        body_hash = hashlib.sha256(
            json.dumps(canonical_body, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        canonical = f"POST|/v2/demo/round-status|{body_hash}|{timestamp}|{nonce}".encode()
        self.assertTrue(keypair.verify(canonical, bytes.fromhex(sig_hex)))


if __name__ == "__main__":
    unittest.main()
