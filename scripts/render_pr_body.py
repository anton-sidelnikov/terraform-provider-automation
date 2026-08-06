#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--run-url", required=True)
    parser.add_argument("--sdk-pr-url")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    evidence = json.loads(args.evidence.read_text(encoding="utf-8"))
    classification = plan["classification"]
    mapping = plan["mapping"]
    request = plan["request"]
    citations = "\n".join(
        f"- `{item['path']}:{item['line_start']}-{item['line_end']}`"
        for item in evidence["citations"]
    )
    commands = "\n".join(
        f"- `{' '.join(item['argv'])}` — exit `{item['returncode']}` ({item['duration_seconds']:.2f}s)"
        for item in evidence["commands"]
    )
    dependency = f"\n- Approved SDK PR: {args.sdk_pr_url}\n" if args.sdk_pr_url else ""
    policies = ", ".join(
        f"`{item['id']}@{item['version']}`"
        for item in evidence["policies"]
    )
    body = f"""## Agent-generated change

**Classification:** `{classification['kind']}` (confidence `{classification['confidence']}`)  
**Documentation:** `opentelekomcloud-docs/{mapping['docs']}`  
**Automation run:** {args.run_url}
{dependency}
### Request

{request['description']}

### Summary

{evidence['summary']}

### API-reference evidence

{citations}

### Validation

{commands}

### Audit metadata

- Base revision: `{evidence['repository_revision']}`
- Documentation revision: `{evidence['documentation_revision']}`
- Patch SHA-256: `{evidence['patch_sha256']}`
- Skill: `{evidence['skill']['id']}@{evidence['skill']['version']}`
- Policies: {policies}
- Model route: `{evidence['model']}`
- Estimated model cost: `${evidence['cost_usd']:.6f}`

This is a draft produced by a governed automation workflow. Human review is required; the workflow cannot merge it.

<!-- otc-agent-metadata
{json.dumps({'schema_version': 2, 'classification': classification['kind'], 'docs_repository': mapping['docs'], 'sdk': mapping['sdk'], 'provider': mapping['provider'], 'automation_run': args.run_url, 'skill': evidence['skill'], 'policies': evidence['policies']}, sort_keys=True)}
-->
"""
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(body, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
