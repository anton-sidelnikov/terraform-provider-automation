#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pull-request", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    args = parser.parse_args()
    pull = json.loads(args.pull_request.read_text(encoding="utf-8"))
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    if pull.get("merged_at") is None or not pull.get("merged"):
        raise SystemExit("SDK pull request is not merged")
    if pull.get("base", {}).get("repo", {}).get("full_name") != "opentelekomcloud/gophertelekomcloud":
        raise SystemExit("SDK pull request targets an unexpected repository")
    if pull.get("base", {}).get("ref") != "main":
        raise SystemExit("SDK pull request must target main")
    if pull.get("user", {}).get("type") != "Bot":
        raise SystemExit("SDK pull request must be authored by the automation App")
    if not str(pull.get("head", {}).get("ref", "")).startswith("agent/"):
        raise SystemExit("SDK pull request must originate from an agent/* branch")
    sha = str(pull.get("merge_commit_sha", ""))
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise SystemExit("SDK merge commit SHA is invalid")
    body = pull.get("body") or ""
    match = re.search(r"<!-- otc-agent-metadata\s*(\{.*?\})\s*-->", body, re.DOTALL)
    if not match:
        raise SystemExit("SDK pull request lacks workflow metadata")
    metadata = json.loads(match.group(1))
    mapping = plan["mapping"]
    classification = plan["classification"]
    for key in ("docs_repository", "sdk", "provider"):
        expected_key = "docs" if key == "docs_repository" else key
        if metadata.get(key) != mapping.get(expected_key):
            raise SystemExit(f"SDK PR metadata mismatch for {key}")
    if metadata.get("classification") != classification.get("kind"):
        raise SystemExit("SDK PR classification does not match provider plan")
    print(f"sha={sha}")
    print(f"url={pull['html_url']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
