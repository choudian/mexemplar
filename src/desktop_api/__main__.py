from __future__ import annotations

import argparse
import os
import secrets

import uvicorn

from src.desktop_api.app import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Mexemplar desktop sidecar API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument(
        "--token", default=os.environ.get("MEXEMPLAR_DESKTOP_TOKEN") or secrets.token_urlsafe(32)
    )
    args = parser.parse_args()
    os.environ["MEXEMPLAR_DESKTOP_TOKEN"] = args.token
    uvicorn.run(create_app(args.token), host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
