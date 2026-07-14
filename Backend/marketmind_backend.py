"""Executable entry point for the MarketMind local API service."""

from __future__ import annotations

import argparse

import uvicorn

from app.main import app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the MarketMind AI local API.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8000, type=int)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()