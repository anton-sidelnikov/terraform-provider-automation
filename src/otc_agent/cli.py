from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .catalog import Catalog, default_catalog_path
from .domain import ChangeKind, ChangeRequest
from .evals import run_evaluation
from .orchestrator import Planner
from .service import serve
from .telemetry import configure_logging


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="otc-agent")
    parser.add_argument("--catalog", type=Path, default=default_catalog_path())
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan")
    plan.add_argument("--service", help="Optional reviewed service key; required only for ambiguous mapped variants")
    plan.add_argument("--kind", choices=[item.value for item in ChangeKind], required=True)
    plan.add_argument("--description", required=True)
    plan.add_argument("--docs-repository")
    plan.add_argument("--issue-url")
    plan.add_argument("--output", type=Path)
    evaluate = sub.add_parser("eval")
    evaluate.add_argument("--mode", choices=("offline", "online"), required=True)
    evaluate.add_argument("--dataset", type=Path, required=True)
    evaluate.add_argument("--output", type=Path, required=True)
    evaluate.add_argument("--baseline", type=Path)
    sub.add_parser("catalog-check")
    server = sub.add_parser("serve")
    server.add_argument("--host", default="127.0.0.1")
    server.add_argument("--port", type=int, default=8080)
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = _parser().parse_args(argv)
    catalog = Catalog.load(args.catalog)
    if args.command == "catalog-check":
        print(json.dumps({"status": "ok", "mappings": len(catalog.mappings), "api_ref_repositories": len(catalog.eligible_docs_repositories)}))
        return 0
    if args.command == "plan":
        plan = Planner(catalog).plan(
            ChangeRequest(
                service=args.service,
                kind=ChangeKind(args.kind),
                description=args.description,
                docs_repository=args.docs_repository,
                issue_url=args.issue_url,
            )
        )
        output = json.dumps(plan.as_dict(), indent=2, sort_keys=True) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(output, encoding="utf-8")
        else:
            sys.stdout.write(output)
        return 0
    if args.command == "eval":
        endpoint = os.environ.get("OTC_AGENT_EVAL_URL") if args.mode == "online" else None
        baseline_score = None
        if args.baseline:
            baseline_value = json.loads(args.baseline.read_text(encoding="utf-8"))
            baseline_score = float(baseline_value[args.mode]["score"])
        report = run_evaluation(
            args.dataset,
            catalog,
            mode=args.mode,
            endpoint=endpoint,
            baseline_score=baseline_score,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report.as_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(report.as_dict(), sort_keys=True))
        return 0 if report.passed else 2
    if args.command == "serve":
        serve(args.host, args.port, catalog)
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
