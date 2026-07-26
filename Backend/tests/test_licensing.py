"""Signed-license verification — the guarantees that protect the product."""
import base64
import importlib
import json
import time

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def _b64(b): return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _make_key(priv, **over):
    p = {"customer": "buyer@x.com", "tier": "pro", "issued": int(time.time()),
         "expires": int(time.time()) + 30 * 86400}
    p.update(over)
    pb = json.dumps(p, separators=(",", ":"), sort_keys=True).encode()
    return f"{_b64(pb)}.{_b64(priv.sign(pb))}"


@pytest.fixture
def lic(monkeypatch):
    """A licensing module wired to a fresh throwaway keypair."""
    priv = Ed25519PrivateKey.generate()
    monkeypatch.setenv("MARKETMIND_LICENSE_PUBKEY", priv.public_key().public_bytes_raw().hex())
    import app.licensing as L
    importlib.reload(L)
    return L, priv


def test_valid_key_verifies(lic):
    L, priv = lic
    s = L.verify_key(_make_key(priv))
    assert s.valid and s.tier == "pro" and s.days_left in (29, 30) and s.customer == "buyer@x.com"


def test_tampered_payload_rejected(lic):
    L, priv = lic
    k = _make_key(priv)
    bad = k[:8] + ("A" if k[8] != "A" else "B") + k[9:]
    assert not L.verify_key(bad).valid


def test_expired_key_rejected(lic):
    L, priv = lic
    s = L.verify_key(_make_key(priv, expires=int(time.time()) - 10))
    assert not s.valid and s.reason == "license expired"


def test_key_from_another_signer_rejected(lic):
    L, _ = lic
    other = Ed25519PrivateKey.generate()          # not the app's key
    assert not L.verify_key(_make_key(other)).valid


def test_machine_locked_key_only_valid_on_that_machine(lic):
    L, priv = lic
    good = L.verify_key(_make_key(priv, machine=L.machine_id()))
    assert good.valid and good.machine_locked
    wrong = L.verify_key(_make_key(priv, machine="deadbeefdeadbeef"))
    assert not wrong.valid and "different machine" in wrong.reason


def test_empty_and_garbage_rejected(lic):
    L, _ = lic
    assert not L.verify_key("").valid
    assert not L.verify_key("not-a-key").valid
    assert not L.verify_key("abc.def").valid


def test_is_licensed_true_when_not_required(lic, monkeypatch):
    L, _ = lic
    monkeypatch.setattr(L, "REQUIRE_LICENSE", False)
    assert L.is_licensed() is True                # dev mode never blocks
