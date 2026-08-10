#!/usr/bin/env python3
"""
MarketMind license generator — OWNER TOOL. Do NOT ship this file.

It holds (or reads) the PRIVATE key and mints signed license keys. The app only
carries the matching PUBLIC key, so keys can be verified offline but never forged.

Usage
-----
  # 1) one-time: make a keypair. Save the private key somewhere safe (a file,
  #    a password manager) and paste the public key into app/licensing.py.
  python tools/license_gen.py keygen

  # 2) issue a key for a customer (set the private key first):
  set MM_LICENSE_PRIVKEY=<hex from keygen>
  python tools/license_gen.py issue --email malik@x.com --days 30 --tier pro
  python tools/license_gen.py issue --email bob@x.com  --days 365 --machine <id>

The customer pastes the printed key into the app (Settings) or a license.key file.
To machine-lock, ask the buyer for their machine id (the app shows it) and pass
--machine.
"""
import argparse
import base64
import json
import os
import sys
import time

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def keygen() -> None:
    priv = Ed25519PrivateKey.generate()
    priv_hex = priv.private_bytes_raw().hex()
    pub_hex = priv.public_key().public_bytes_raw().hex()
    print("KEYPAIR GENERATED — keep the private key secret.\n")
    print(f"  PRIVATE KEY (owner only):  {priv_hex}")
    print(f"  PUBLIC KEY  (into app):    {pub_hex}\n")
    print("Next:")
    print("  * set MM_LICENSE_PRIVKEY to the private key when issuing")
    print("  * paste PUBLIC_KEY_HEX into Backend/app/licensing.py (or set")
    print("    MARKETMIND_LICENSE_PUBKEY) so the app verifies these keys")


def issue(args) -> None:
    priv_hex = os.getenv("MM_LICENSE_PRIVKEY", "").strip()
    if not priv_hex:
        sys.exit("set MM_LICENSE_PRIVKEY to your private key (from keygen) first")
    priv = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(priv_hex))

    now = int(time.time())
    payload = {
        "customer": args.email,
        "tier": args.tier,
        "issued": now,
        "expires": now + args.days * 86400,
    }
    if args.machine:
        payload["machine"] = args.machine

    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    sig = priv.sign(payload_bytes)
    key = f"{_b64(payload_bytes)}.{_b64(sig)}"

    print("LICENSE KEY (give this to the customer):\n")
    print(key)
    print()
    print(f"  customer : {args.email}")
    print(f"  tier     : {args.tier}")
    print(f"  expires  : {time.strftime('%Y-%m-%d', time.localtime(payload['expires']))} "
          f"({args.days} days)")
    print(f"  machine  : {args.machine or 'any (not locked)'}")


def main() -> None:
    ap = argparse.ArgumentParser(description="MarketMind license generator (owner tool)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("keygen", help="generate a new signing keypair")
    iss = sub.add_parser("issue", help="issue a signed license key")
    iss.add_argument("--email", required=True, help="customer email / name")
    iss.add_argument("--days", type=int, default=30, help="validity in days")
    iss.add_argument("--tier", default="pro", choices=["lite", "pro", "elite"])
    iss.add_argument("--machine", default="", help="optional machine id to lock to")
    args = ap.parse_args()
    if args.cmd == "keygen":
        keygen()
    elif args.cmd == "issue":
        issue(args)


if __name__ == "__main__":
    main()
