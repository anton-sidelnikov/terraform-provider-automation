from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .catalog import Catalog, default_catalog_path
from .domain import ChangeKind, ChangeRequest
from .evals import run_evaluation
from .generation import generate_provider_candidate, generate_sdk_candidate, provider_publish_policy
from .model import OpenAICompatibleModel
from .orchestrator import Planner
from .patching import provider_policy, sdk_policy, validate_patch
from .policy import load_policy_registry
from .sdk_layout import analyze_sdk_layout
from .service import serve
from .telemetry import configure_logging


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="otc-agent")
    parser.add_argument("--catalog", type=Path, default=default_catalog_path())
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan")
    plan.add_argument("--service", help="Optional reviewed service key; required only for ambiguous mapped variants")
    plan.add_argument("--kind", choices=[item.value for item in ChangeKind], help="Legacy hint; classification is independent")
    plan.add_argument("--description", required=True)
    plan.add_argument("--docs-repository")
    plan.add_argument("--issue-url")
    plan.add_argument("--sdk-root", type=Path, help="Optional SDK checkout used for layout-aware classification")
    plan.add_argument("--output", type=Path)
    analyze_layout = sub.add_parser("analyze-sdk-layout")
    analyze_layout.add_argument("--sdk-root", type=Path, required=True)
    analyze_layout.add_argument("--service", required=True)
    analyze_layout.add_argument("--output", type=Path)
    evaluate = sub.add_parser("eval")
    evaluate.add_argument("--mode", choices=("offline", "online"), required=True)
    evaluate.add_argument("--dataset", type=Path, required=True)
    evaluate.add_argument("--output", type=Path, required=True)
    evaluate.add_argument("--baseline", type=Path)
    sub.add_parser("catalog-check")
    policy_check = sub.add_parser("policy-check")
    policy_check.add_argument("--root", type=Path, default=Path("docs/policy"))
    server = sub.add_parser("serve")
    server.add_argument("--host", default="127.0.0.1")
    server.add_argument("--port", type=int, default=8080)
    sdk = sub.add_parser("generate-sdk")
    sdk.add_argument("--plan", type=Path, required=True)
    sdk.add_argument("--sdk-root", type=Path, required=True)
    sdk.add_argument("--docs-root", type=Path, required=True)
    sdk.add_argument("--output-dir", type=Path, required=True)
    provider = sub.add_parser("generate-provider")
    provider.add_argument("--plan", type=Path, required=True)
    provider.add_argument("--provider-root", type=Path, required=True)
    provider.add_argument("--sdk-root", type=Path, required=True)
    provider.add_argument("--docs-root", type=Path, required=True)
    provider.add_argument("--sdk-revision", required=True)
    provider.add_argument("--sdk-pr-url", required=True)
    provider.add_argument("--output-dir", type=Path, required=True)
    validate = sub.add_parser("validate-patch")
    validate.add_argument("--stage", choices=("sdk", "provider"), required=True)
    validate.add_argument("--service", required=True)
    validate.add_argument("--patch", type=Path, required=True)
    validate.add_argument("--allow-dependency-files", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = _parser().parse_args(argv)
    catalog = Catalog.load(args.catalog)
    if args.command == "catalog-check":
        print(json.dumps({"status": "ok", "mappings": len(catalog.mappings), "api_ref_repositories": len(catalog.eligible_docs_repositories)}))
        return 0
    if args.command == "policy-check":
        contracts = load_policy_registry(args.root)
        print(
            json.dumps(
                {
                    "status": "ok",
                    "policies": [
                        {"id": contract.policy_id, "version": contract.version}
                        for contract in contracts
                    ],
                },
                sort_keys=True,
            )
        )
        return 0
    if args.command == "plan":
        plan = Planner(catalog).plan(
            ChangeRequest(
                service=args.service,
                kind=ChangeKind(args.kind) if args.kind else None,
                description=args.description,
                docs_repository=args.docs_repository,
                issue_url=args.issue_url,
            ),
            sdk_root=args.sdk_root,
        )
        output = json.dumps(plan.as_dict(), indent=2, sort_keys=True) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(output, encoding="utf-8")
        else:
            sys.stdout.write(output)
        return 0 if plan.status.value != "blocked" else 3
    if args.command == "analyze-sdk-layout":
        analysis = analyze_sdk_layout(args.sdk_root, args.service)
        output = json.dumps(analysis.as_dict(), indent=2, sort_keys=True) + "\n"
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
    if args.command == "generate-sdk":
        plan_value = json.loads(args.plan.read_text(encoding="utf-8"))
        record = generate_sdk_candidate(
            plan=plan_value,
            sdk_root=args.sdk_root,
            docs_root=args.docs_root,
            output_dir=args.output_dir,
            model=OpenAICompatibleModel.from_environment(),
        )
        print(json.dumps(record.as_dict(), sort_keys=True))
        return 0
    if args.command == "generate-provider":
        plan_value = json.loads(args.plan.read_text(encoding="utf-8"))
        record = generate_provider_candidate(
            plan=plan_value,
            provider_root=args.provider_root,
            sdk_root=args.sdk_root,
            docs_root=args.docs_root,
            sdk_revision=args.sdk_revision,
            sdk_pr_url=args.sdk_pr_url,
            output_dir=args.output_dir,
            model=OpenAICompatibleModel.from_environment(),
        )
        print(json.dumps(record.as_dict(), sort_keys=True))
        return 0
    if args.command == "validate-patch":
        if args.stage == "sdk":
            policy = sdk_policy(args.service)
        elif args.allow_dependency_files:
            policy = provider_publish_policy(args.service)
        else:
            policy = provider_policy(args.service)
        paths = validate_patch(args.patch.read_text(encoding="utf-8"), policy)
        print(json.dumps({"status": "ok", "paths": paths}))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
