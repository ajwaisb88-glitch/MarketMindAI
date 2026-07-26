"""
License verification — Ed25519 signed keys with an expiry date.

How it protects the product:
  * A license key is a signed token: base64(payload).base64(signature).
  * The OWNER holds the PRIVATE key (in tools/license_gen.py, never shipped).
  * This module carries only the PUBLIC key, so the app can verify a key OFFLINE
    but nobody can forge one or change the expiry — any edit breaks the signature.

Payload fields: customer, issued (unix), expires (unix), tier, and an optional
machine id for one-PC binding. The verifier checks the signature, the expiry,
and — if present — the machine id.

No desktop app is 100% crack-proof; this stops casual sharing and expiry-cheating,
which is the realistic goal for selling to friends / small numbers of customers.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import time
import uuid
from dataclasses import dataclass
from typing import Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

# ── The product's PUBLIC key (hex). Replace with your own from license_gen keygen.
# This placeholder is a real, published test key — regenerate before selling.
PUBLIC_KEY_HEX = os.getenv(
    "MARKETMIND_LICENSE_PUBKEY",
    "3b6a27bcceb6a42d62a3a8d02a6f0d73653215771de243a63ac048a18b59da29",
)

# Require a valid license? Off in dev so the app runs; the product build sets it on.
REQUIRE_LICENSE = os.getenv("MARKETMIND_REQUIRE_LICENSE", "0") == "1"


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


@dataclass
class LicenseStatus:
    valid: bool
    reason: str
    customer: Optional[str] = None
    tier: str = "none"
    expires: Optional[int] = None
    days_left: Optional[int] = None
    machine_locked: bool = False

    def as_dict(self) -> dict:
        return {
            "valid": self.valid, "reason": self.reason, "customer": self.customer,
            "tier": self.tier, "expires": self.expires, "days_left": self.days_left,
            "machine_locked": self.machine_locked, "required": REQUIRE_LICENSE,
        }


def machine_id() -> str:
    """Stable per-machine fingerprint (hashed MAC) for optional one-PC binding."""
    raw = f"{uuid.getnode()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _pubkey() -> Ed25519PublicKey:
    return Ed25519PublicKey.from_public_bytes(bytes.fromhex(PUBLIC_KEY_HEX))


def verify_key(license_str: str) -> LicenseStatus:
    """Verify a license string: signature, expiry, and optional machine lock."""
    if not license_str or "." not in license_str:
        return LicenseStatus(False, "no license key")
    try:
        payload_b64, sig_b64 = license_str.strip().split(".", 1)
        payload_bytes = _b64d(payload_b64)
        _pubkey().verify(_b64d(sig_b64), payload_bytes)   # raises on tamper/forgery
    except InvalidSignature:
        return LicenseStatus(False, "invalid signature — key is forged or corrupted")
    except Exception as exc:  # noqa: BLE001
        return LicenseStatus(False, f"malformed license: {exc}")

    try:
        p = json.loads(payload_bytes)
    except Exception:
        return LicenseStatus(False, "malformed license payload")

    now = int(time.time())
    exp = int(p.get("expires", 0))
    customer, tier = p.get("customer"), p.get("tier", "pro")
    locked = bool(p.get("machine"))

    if exp and now > exp:
        return LicenseStatus(False, "license expired", customer, tier, exp, 0, locked)
    if locked and p.get("machine") != machine_id():
        return LicenseStatus(False, "license is locked to a different machine",
                             customer, tier, exp, None, True)

    days_left = max(0, (exp - now) // 86400) if exp else None
    return LicenseStatus(True, "ok", customer, tier, exp, days_left, locked)


def _read_license() -> str:
    """License from env, else a license.key file next to the app."""
    env = os.getenv("MARKETMIND_LICENSE", "").strip()
    if env:
        return env
    for path in (os.getenv("MARKETMIND_LICENSE_FILE", "license.key"),
                 os.path.join(os.path.dirname(__file__), "..", "license.key")):
        try:
            if os.path.exists(path):
                return open(path, encoding="utf-8").read().strip()
        except Exception:
            pass
    return ""


def current_status() -> LicenseStatus:
    return verify_key(_read_license())


def is_licensed() -> bool:
    """True if features should be unlocked. When licensing isn't required
    (dev), always true; otherwise a valid key is needed."""
    if not REQUIRE_LICENSE:
        return True
    return current_status().valid
