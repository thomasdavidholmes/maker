from __future__ import annotations

import argparse
import threading
import webbrowser

import uvicorn

from .app import create_app
from .config import get_settings


def main() -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(prog="maker", description="Launch the Maker Courseware local web app.")
    subparsers = parser.add_subparsers(dest="command")

    serve_parser = subparsers.add_parser("serve", help="Run the local web application.")
    serve_parser.add_argument("--host", default=settings.host)
    serve_parser.add_argument("--port", type=int, default=settings.port)
    serve_parser.add_argument("--reload", action="store_true")
    serve_parser.add_argument("--no-browser", action="store_true")

    args = parser.parse_args()
    if args.command in {None, "serve"}:
        if not args.no_browser:
            url = f"http://{args.host}:{args.port}"
            threading.Timer(1.0, lambda: webbrowser.open(url)).start()
        uvicorn.run(create_app(), host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()

