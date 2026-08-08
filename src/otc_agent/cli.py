from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

from .budget import Budget
from .catalog import Catalog, default_catalog_path
from .domain import ChangeKind, ChangeRequest
from .evals import run_evaluation
from .generation import generate_provider_candidate, generate_sdk_candidate, provider_publish_policy
from .model import model_from_environment
from .orchestrator import Planner
from .patching import provider_policy, sdk_policy, validate_patch
from .policy import PolicyContract, default_policy_root, load_policy_registry
from .pr_iteration import (
    append_repair_commit,
    authorize_iteration,
    classify_feedback,
    complete_iteration_state,
    fetch_incremental_feedback,
    find_iteration_command,
    generate_reviewed_repair,
    load_iteration_artifacts,
    load_iteration_state,
    reply_to_addressed_feedback,
)
from .publishing import (
    build_sdk_pull_request_body,
    build_publication_metadata,
    verify_append_only_history,
    verify_publish_preflight,
)
from .review import build_review_bundle, build_review_history, run_independent_review
from .routing import AuthorRouteIdentity, ModelRouter, parse_model_tier
from .sdk_layout import analyze_sdk_layout
from .sdk_refactor import (
    apply_operation_file_migration,
    build_operation_migration_plan,
    capture_exported_api,
    capture_semantic_snapshot,
    select_migration,
    validate_exported_api_compatibility,
    validate_operation_file_correspondence,
    validate_semantic_preservation,
    verify_refactor_behavior,
)
from .service import serve
from .skill import (
    default_skill_registry_path,
    find_skill,
    load_skill_registry,
    SkillManifest,
    skill_identity,
    validate_skill_input,
)
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
    policy_check.add_argument("--root", type=Path, default=default_policy_root())
    skill_check = sub.add_parser("skill-check")
    skill_check.add_argument("--registry", type=Path, default=default_skill_registry_path())
    skill_check.add_argument("--policy-root", type=Path, default=default_policy_root())
    analyze = sub.add_parser("analyze")
    analyze.add_argument("--service", required=True)
    analyze.add_argument("--description", required=True)
    analyze.add_argument("--docs-repository")
    analyze.add_argument("--issue-url")
    analyze.add_argument("--sdk-root", type=Path)
    analyze.add_argument("--output", type=Path)
    for skill_id in ("spec", "refactor-sdk", "review", "verify", "publish", "iterate-pr", "resume"):
        command = sub.add_parser(skill_id)
        command.add_argument("--input", type=Path, required=True)
        command.add_argument("--output", type=Path)
        if skill_id == "review":
            command.add_argument("--execute", action="store_true")
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
        policies = load_policy_registry(args.root)
        print(json.dumps({"status": "ok", "policies": [{"id": item.policy_id, "version": item.version} for item in policies]}, sort_keys=True))
        return 0
    if args.command == "skill-check":
        policies = load_policy_registry(args.policy_root)
        skills = load_skill_registry(args.registry, policies)
        print(json.dumps({"status": "ok", "skills": [{"id": item.skill_id, "version": item.version} for item in skills]}, sort_keys=True))
        return 0
    if args.command == "analyze":
        policies, skills = _skill_contracts()
        skill = find_skill(skills, "analyze")
        payload: dict[str, object] = {
            "service": args.service,
            "description": args.description,
        }
        if args.docs_repository:
            payload["docs_repository"] = args.docs_repository
        if args.issue_url:
            payload["issue_url"] = args.issue_url
        if args.sdk_root:
            payload["sdk_root"] = str(args.sdk_root)
        validate_skill_input(skill, payload)
        plan = Planner(catalog).plan(
            ChangeRequest(
                service=args.service,
                kind=None,
                description=args.description,
                docs_repository=args.docs_repository,
                issue_url=args.issue_url,
            ),
            sdk_root=args.sdk_root,
        )
        layout = None
        if args.sdk_root and plan.mapping.sdk:
            layout = analyze_sdk_layout(args.sdk_root, plan.mapping.sdk).as_dict()
        result = {
            "status": plan.status.value,
            "skill": skill_identity(skill, policies),
            "classification": plan.classification,
            "layout": layout,
            "gaps": plan.warnings,
            "plan": plan.as_dict(),
        }
        _write_json(result, args.output)
        return 0 if plan.status.value != "blocked" else 3
    if args.command == "review":
        policies, skills = _skill_contracts()
        skill = find_skill(skills, "review")
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        validate_skill_input(skill, payload)
        bundle = build_review_bundle(
            payload["evidence"],
            payload["patch"],
            payload.get("diagnostics"),
        )
        result: dict[str, object] = {
            "status": "ready_for_independent_review",
            "skill": skill_identity(skill, policies),
            "review_bundle": bundle.as_dict(),
        }
        if args.execute:
            evidence = payload["evidence"]
            author_skill = evidence.get("skill")
            if not isinstance(author_skill, dict):
                raise ValueError("generation evidence is missing author skill identity")
            author_model = evidence.get("model")
            if not isinstance(author_model, str) or not author_model:
                raise ValueError("generation evidence is missing author model identity")
            router = ModelRouter.from_environment()
            route = router.select_reviewer(
                AuthorRouteIdentity(
                    model=author_model,
                    tier=parse_model_tier(author_skill.get("model_tier")),
                    provider=evidence.get("model_provider")
                    if isinstance(evidence.get("model_provider"), str)
                    else None,
                    endpoint=evidence.get("model_endpoint") if isinstance(evidence.get("model_endpoint"), str) else None,
                )
            )
            review = run_independent_review(
                bundle,
                model=route.build_model(),
                route=route,
                budget=Budget(
                    max_model_calls=skill.budget.max_model_calls,
                    max_input_tokens=skill.budget.max_input_tokens,
                    max_output_tokens=skill.budget.max_output_tokens,
                    max_cost_usd=skill.budget.max_cost_usd,
                    max_wall_seconds=skill.budget.max_wall_seconds,
                ),
            )
            result["status"] = "reviewed"
            result["review"] = review.as_dict()
            result["review_history"] = build_review_history(bundle, review).as_dict()
        _write_json(result, args.output)
        return 0
    if args.command == "refactor-sdk":
        policies, skills = _skill_contracts()
        skill = find_skill(skills, "refactor-sdk")
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        validate_skill_input(skill, payload)
        sdk_root = Path(payload["sdk_root"])
        specification = payload["specification"]
        expected_layout = payload["layout"]
        if not isinstance(expected_layout, dict):
            raise ValueError("refactor-sdk layout must be an object")
        service = expected_layout.get("service")
        if not isinstance(service, str) or not service:
            raise ValueError("refactor-sdk layout is missing service")
        current_layout = analyze_sdk_layout(sdk_root, service)
        if json.dumps(current_layout.as_dict(), sort_keys=True) != json.dumps(expected_layout, sort_keys=True):
            raise ValueError("refactor-sdk layout analysis is stale or does not match the SDK checkout")
        migration_plan = build_operation_migration_plan(sdk_root, current_layout, specification)
        selected_plan = migration_plan
        migration_id = payload.get("migration_id")
        if isinstance(migration_id, str):
            selected_plan = select_migration(migration_plan, migration_id)
        status = migration_plan.status
        compatibility = None
        semantics = None
        operation_files = None
        behavior = None
        applied_migration = None
        candidate_sdk_root = payload.get("candidate_sdk_root")
        apply_migration = payload.get("apply", False)
        if apply_migration and candidate_sdk_root:
            raise ValueError("refactor-sdk cannot combine apply with candidate_sdk_root")
        if apply_migration:
            if len(migration_plan.operations) > 1 and not migration_id:
                raise ValueError("refactor-sdk apply requires migration_id for a multi-operation plan")
            applied_migration = apply_operation_file_migration(sdk_root, selected_plan)
            compatibility = applied_migration.compatibility
            semantics = applied_migration.semantics
            operation_files = applied_migration.operation_files
            behavior = applied_migration.behavior
        elif isinstance(candidate_sdk_root, str):
            candidate_root = Path(candidate_sdk_root)
            candidate = capture_exported_api(candidate_root, service)
            compatibility = validate_exported_api_compatibility(
                migration_plan.exported_api,
                candidate,
                migration_plan.approved_api_changes,
            )
            if not compatibility.compatible:
                status = "blocked"
            semantics = validate_semantic_preservation(
                migration_plan.semantic_snapshot,
                capture_semantic_snapshot(candidate_root, service),
                migration_plan.approved_behavior_changes,
            )
            if not semantics.compatible:
                status = "blocked"
            operation_files = validate_operation_file_correspondence(
                candidate_root,
                service,
                tuple(item.operation for item in selected_plan.operations) if migration_id else None,
            )
            if not operation_files.valid:
                status = "blocked"
            behavior = verify_refactor_behavior(
                candidate_root,
                service,
                selected_plan.behavior_requirements,
            )
            if not behavior.valid:
                status = "blocked"
        result = {
            "status": status,
            "skill": skill_identity(skill, policies),
            "specification_sha256": hashlib.sha256(
                json.dumps(specification, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
            "migration_plan": migration_plan.as_dict(),
            "selected_migration": selected_plan.batches[0].as_dict() if migration_id else None,
            "compatibility": compatibility.as_dict() if compatibility else None,
            "semantics": semantics.as_dict() if semantics else None,
            "operation_files": operation_files.as_dict() if operation_files else None,
            "behavior": behavior.as_dict() if behavior else None,
            "applied_migration": applied_migration.as_dict() if applied_migration else None,
        }
        _write_json(result, args.output)
        return 0 if status == "ready" else 3
    if args.command == "publish":
        policies, skills = _skill_contracts()
        skill = find_skill(skills, "publish")
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        validate_skill_input(skill, payload)
        documentation = catalog.resolve_documentation(payload["documentation_repository"])
        preflight = verify_publish_preflight(
            artifact=Path(payload["artifact"]),
            repository=payload["repository"],
            base_sha=payload["base_sha"],
            issue=payload["issue"],
            routes=tuple(payload["routes"]),
        )
        history = verify_append_only_history(
            worktree=Path(payload["worktree"]),
            base_sha=payload["base_sha"],
            candidate_head_sha=payload["candidate_head_sha"],
            previous_head_sha=payload.get("previous_head_sha"),
        )
        publisher_skill = skill_identity(skill, policies)
        metadata = build_publication_metadata(
            artifact=Path(payload["artifact"]),
            preflight=preflight,
            history=history,
            publisher_skill=publisher_skill,
        )
        pull_request_body = build_sdk_pull_request_body(
            payload["pull_request_body"],
            preflight.issue,
            documentation.docs,
            tuple(payload.get("depends_on", [])),
            metadata,
        )
        result = {
            "status": "approved_for_publish",
            "skill": publisher_skill,
            "preflight": preflight.as_dict(),
            "history": history.as_dict(),
            "metadata": metadata,
            "pull_request_body": pull_request_body,
        }
        _write_json(result, args.output)
        return 0
    if args.command == "iterate-pr":
        policies, skills = _skill_contracts()
        skill = find_skill(skills, "iterate-pr")
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        validate_skill_input(skill, payload)
        command = find_iteration_command(payload["comments"])
        metadata = authorize_iteration(
            command=command,
            repository=payload["repository"],
            pull_request=payload["pull_request"],
            head_branch=payload["head_branch"],
            pull_request_body=payload["pull_request_body"],
        )
        state_path = Path(payload["state_path"])
        state = load_iteration_state(
            state_path,
            run_id=payload["run_id"],
            repository=payload["repository"],
            pull_request=payload["pull_request"],
        )
        completed = state.completed_commands.get(str(command.comment_id))
        if completed is not None:
            _write_json(
                {
                    "status": "already_processed",
                    "skill": skill_identity(skill, policies),
                    "run_id": payload["run_id"],
                    "pull_request": payload["pull_request"],
                    "command": command.as_dict(),
                    "completion": completed,
                    "state": state.as_dict(),
                },
                args.output,
            )
            return 0
        artifacts = load_iteration_artifacts(Path(payload["artifact"]), metadata)
        feedback = fetch_incremental_feedback(
            repository=payload["repository"],
            pull_request=payload["pull_request"],
            after_issue_comment_id=state.issue_comment_cursor,
            after_review_comment_id=state.review_comment_cursor,
        )
        classifications = classify_feedback(
            feedback=feedback,
            artifacts=artifacts,
            model=model_from_environment()
            if feedback.issue_comments or feedback.review_comments
            else None,
            budget=Budget(
                max_model_calls=skill.budget.max_model_calls,
                max_input_tokens=skill.budget.max_input_tokens,
                max_output_tokens=skill.budget.max_output_tokens,
                max_cost_usd=skill.budget.max_cost_usd,
                max_wall_seconds=skill.budget.max_wall_seconds,
            ),
        )
        repair = None
        repair_commit = None
        replies = ()
        if any(item.category == "actionable" for item in classifications.classifications):
            if payload["stage"] not in {"sdk", "provider"}:
                raise ValueError("iteration stage must be sdk or provider")
            author_skill = artifacts.evidence.get("skill")
            if not isinstance(author_skill, dict):
                raise ValueError("iteration artifact is missing author skill identity")
            author_model = artifacts.evidence.get("model")
            if not isinstance(author_model, str) or not author_model:
                raise ValueError("iteration artifact is missing author model identity")
            route = ModelRouter.from_environment().select_reviewer(
                AuthorRouteIdentity(
                    model=author_model,
                    tier=parse_model_tier(author_skill.get("model_tier")),
                    provider=artifacts.evidence.get("model_provider")
                    if isinstance(artifacts.evidence.get("model_provider"), str)
                    else None,
                    endpoint=artifacts.evidence.get("model_endpoint")
                    if isinstance(artifacts.evidence.get("model_endpoint"), str)
                    else None,
                )
            )
            patch_policy = (
                sdk_policy(payload["service"])
                if payload["stage"] == "sdk"
                else provider_policy(payload["service"])
            )

            def validate_iteration_repair(patch: str, _iteration: int) -> list[object]:
                paths = validate_patch(patch, patch_policy)
                return [
                    {
                        "tool": "patch.validate",
                        "status": "passed",
                        "summary": f"validated {len(paths)} changed paths",
                        "sha256": hashlib.sha256(patch.encode("utf-8")).hexdigest(),
                    }
                ]

            repair = generate_reviewed_repair(
                feedback=feedback,
                classifications=classifications,
                artifacts=artifacts,
                current_patch=payload["current_patch"],
                diagnostics=payload.get("diagnostics", []),
                repair_model=model_from_environment(),
                reviewer_model=route.build_model(),
                reviewer_route=route,
                repair_budget=Budget(
                    max_model_calls=1,
                    max_input_tokens=skill.budget.max_input_tokens,
                    max_output_tokens=skill.budget.max_output_tokens,
                    max_cost_usd=skill.budget.max_cost_usd,
                    max_wall_seconds=skill.budget.max_wall_seconds,
                ),
                reviewer_budget=Budget(
                    max_model_calls=1,
                    max_input_tokens=skill.budget.max_input_tokens,
                    max_output_tokens=skill.budget.max_output_tokens,
                    max_cost_usd=skill.budget.max_cost_usd,
                    max_wall_seconds=skill.budget.max_wall_seconds,
                ),
                validate_repair=validate_iteration_repair,
            )
            if repair and repair.status == "approved":
                source_revisions = metadata.get("source_revisions")
                if not isinstance(source_revisions, dict):
                    raise ValueError("pull request metadata is missing source revisions")
                base_sha = source_revisions.get("base")
                if not isinstance(base_sha, str):
                    raise ValueError("pull request metadata is missing its base revision")
                for field in ("worktree", "previous_head_sha", "commit_message"):
                    if not isinstance(payload.get(field), str) or not payload[field]:
                        raise ValueError(f"approved repair requires {field}")
                repair_commit = append_repair_commit(
                    worktree=Path(payload["worktree"]),
                    branch=payload["head_branch"],
                    base_sha=base_sha,
                    previous_head_sha=payload["previous_head_sha"],
                    current_patch=payload["current_patch"],
                    replacement_patch=repair.patch,
                    commit_message=payload["commit_message"],
                )
                replies = reply_to_addressed_feedback(
                    repository=payload["repository"],
                    pull_request=payload["pull_request"],
                    feedback=feedback,
                    classifications=classifications,
                    repair=repair,
                    commit=repair_commit,
                )
        status = (
            "repair_approved"
            if repair and repair.status == "approved"
            else "repair_blocked"
            if repair
            else "feedback_classified"
        )
        state = complete_iteration_state(
            state_path,
            state=state,
            command=command,
            feedback=feedback,
            repair_commit=repair_commit,
            replies=replies,
            status=status,
        )
        result = {
            "status": status,
            "skill": skill_identity(skill, policies),
            "run_id": payload["run_id"],
            "pull_request": payload["pull_request"],
            "command": command.as_dict(),
            "metadata": metadata,
            "artifacts": artifacts.as_dict(),
            "feedback": feedback.as_dict(),
            "classifications": classifications.as_dict(),
            "repair": repair.as_dict() if repair else None,
            "repair_commit": repair_commit.as_dict() if repair_commit else None,
            "replies": [reply.as_dict() for reply in replies],
            "state": state.as_dict(),
        }
        _write_json(result, args.output)
        return 0
    if args.command in {"spec", "verify", "resume"}:
        policies, skills = _skill_contracts()
        skill = find_skill(skills, args.command)
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        validate_skill_input(skill, payload)
        result = {
            "status": "not_implemented",
            "skill": skill_identity(skill, policies),
            "input": payload,
            "reason": "The command contract is active; execution is delivered by its roadmap milestone.",
        }
        _write_json(result, args.output)
        return 4
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
            model=model_from_environment(),
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
            model=model_from_environment(),
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


def _skill_contracts() -> tuple[tuple[PolicyContract, ...], tuple[SkillManifest, ...]]:
    policies = load_policy_registry(default_policy_root())
    return policies, load_skill_registry(default_skill_registry_path(), policies)


def _write_json(value: dict[str, object], output: Path | None) -> None:
    content = json.dumps(value, indent=2, sort_keys=True) + "\n"
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content, encoding="utf-8")
    else:
        sys.stdout.write(content)


if __name__ == "__main__":
    raise SystemExit(main())
