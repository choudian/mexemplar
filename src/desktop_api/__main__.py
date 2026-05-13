from __future__ import annotations

import argparse
import os
import secrets
import sys

import uvicorn

from src.desktop_api.app import create_app


def main() -> None:
    # Windows 上 Python 信号处理器只在主线程 Python 字节码间隙执行；
    # LLM 阻塞调用期间信号被吞掉，os._exit 反而让 Ctrl+C 失效。
    # 改用 uvicorn 原生 shutdown + LLM 超时来保证可退出。

    parser = argparse.ArgumentParser(description="Mexemplar desktop sidecar API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--verbose", "-v", action="store_true", help="显示 Agent 详细日志")
    parser.add_argument(
        "--token", default=os.environ.get("MEXEMPLAR_DESKTOP_TOKEN") or secrets.token_urlsafe(32)
    )
    args = parser.parse_args()
    os.environ["MEXEMPLAR_DESKTOP_TOKEN"] = args.token

    if args.verbose:
        import logging

        handler = logging.StreamHandler(sys.stderr)
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
        )
        for name in (
            "src.business.agents",
            "src.business.ai",
            "src.business.orchestration",
        ):
            lg = logging.getLogger(name)
            lg.setLevel(logging.DEBUG)
            lg.addHandler(handler)

    uvicorn.run(
        create_app(args.token),
        host=args.host,
        port=args.port,
        log_level="info",
        timeout_graceful_shutdown=3,
    )


if __name__ == "__main__":
    main()
