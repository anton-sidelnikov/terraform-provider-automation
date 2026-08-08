from __future__ import annotations

import argparse
from pathlib import Path

from .catalog import Catalog, default_catalog_path
from .environment import load_environment
from .service import serve
from .telemetry import configure_logging


def main(argv: list[str] | None = None) -> int:
    environment_parser = argparse.ArgumentParser(add_help=False)
    environment_parser.add_argument("--env-file", type=Path)
    environment_args, _ = environment_parser.parse_known_args(argv)
    load_environment(environment_args.env_file)
    parser = argparse.ArgumentParser(prog="otc-agent-api")
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--catalog", type=Path, default=default_catalog_path())
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args(argv)
    configure_logging()
    serve(args.host, args.port, Catalog.load(args.catalog))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
